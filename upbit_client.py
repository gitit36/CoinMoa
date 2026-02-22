"""
Upbit API Client — reusable wrapper with automatic JWT auth.

Usage:
    from upbit_client import UpbitClient

    client = UpbitClient()                    # loads keys from .env automatically
    accounts = client.get("/v1/accounts")     # authenticated GET
    markets  = client.get("/v1/market/all")   # public GET (no auth needed)
    result   = client.post("/v1/orders", body={...})  # authenticated POST
"""

import hashlib
import logging
import os
import time
import uuid
from collections.abc import Mapping
from urllib.parse import unquote, urlencode

import jwt  # PyJWT
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("upbit")

# ---------------------------------------------------------------------------
# Rate Limiter (simple per-second window based on Upbit docs)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Tracks remaining requests from the Remaining-Req response header."""

    def __init__(self, default_rps=8):
        self._remaining = default_rps
        self._default_rps = default_rps
        self._window_start = time.time()

    def wait_if_needed(self):
        """Block until the next window if remaining requests are exhausted."""
        now = time.time()
        elapsed = now - self._window_start
        if elapsed >= 1.0:
            # new window — reset
            self._remaining = self._default_rps
            self._window_start = now
        if self._remaining <= 0:
            sleep_for = 1.0 - elapsed
            if sleep_for > 0:
                logger.debug("Rate limit reached, sleeping %.2fs", sleep_for)
                time.sleep(sleep_for)
            self._remaining = self._default_rps
            self._window_start = time.time()
        self._remaining -= 1

    def update_from_header(self, header_value):
        """Parse the Remaining-Req header: 'group=...; min=N; sec=N'"""
        if not header_value:
            return
        try:
            parts = {
                k.strip(): v.strip()
                for k, v in (p.split("=") for p in header_value.split(";") if "=" in p)
            }
            sec = int(parts.get("sec", self._default_rps))
            self._remaining = sec
        except (ValueError, AttributeError):
            pass

    def mark_exhausted(self):
        self._remaining = 0


# ---------------------------------------------------------------------------
# Upbit Client
# ---------------------------------------------------------------------------

class UpbitClient:
    """
    A reusable Upbit REST API client.

    • Loads keys from .env automatically (or accepts them as arguments).
    • Generates JWT tokens with query_hash when parameters are present.
    • Auto-detects public vs. private endpoints.
    • Handles error responses and rate limits.
    """

    BASE_URL = "https://api.upbit.com"

    # Prefixes that do NOT require authentication
    PUBLIC_PREFIXES = (
        "/v1/market",
        "/v1/ticker",
        "/v1/trades",
        "/v1/candles",
        "/v1/orderbook",
    )

    def __init__(self, access_key=None, secret_key=None, base_url=None):
        load_dotenv()  # reads .env in project root
        self.access_key = access_key or os.getenv("UPBIT_ACCESS_KEY", "")
        self.secret_key = secret_key or os.getenv("UPBIT_SECRET_KEY", "")
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._limiter = _RateLimiter()

    # ----- public helpers ---------------------------------------------------

    def get(self, path, params=None):
        """Send a GET request. `params` can be a dict or list of tuples."""
        query_str = self._build_query_string(params) if params else ""
        url = self._build_url(path, query_str)
        headers = self._auth_headers(path, query_str)
        return self._send(requests.get, url, headers=headers)

    def post(self, path, body=None):
        """Send a POST request with a JSON body."""
        query_str = self._build_query_string(body) if body else ""
        url = self._build_url(path)
        headers = self._auth_headers(path, query_str)
        headers["Content-Type"] = "application/json"
        return self._send(requests.post, url, headers=headers, json=body)

    def delete(self, path, params=None):
        """Send a DELETE request."""
        query_str = self._build_query_string(params) if params else ""
        url = self._build_url(path, query_str)
        headers = self._auth_headers(path, query_str)
        return self._send(requests.delete, url, headers=headers)

    # ----- internals --------------------------------------------------------

    def _build_url(self, path, query_string=""):
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query_string:
            url += f"?{query_string}"
        return url

    @staticmethod
    def _build_query_string(params):
        if params is None:
            return ""
        data = params if isinstance(params, (Mapping, list)) else params
        return unquote(urlencode(data, doseq=True))

    def _requires_auth(self, path):
        return not any(path.startswith(p) for p in self.PUBLIC_PREFIXES)

    def _create_jwt_token(self, query_string=""):
        payload = {
            "access_key": self.access_key,
            "nonce": str(uuid.uuid4()),
        }
        if query_string:
            query_hash = hashlib.sha512(query_string.encode("utf-8")).hexdigest()
            payload["query_hash"] = query_hash
            payload["query_hash_alg"] = "SHA512"
        token = jwt.encode(payload, self.secret_key, algorithm="HS512")
        return token if isinstance(token, str) else token.decode("utf-8")

    def _auth_headers(self, path, query_string=""):
        headers = {}
        if self._requires_auth(path):
            if not self.access_key or not self.secret_key:
                raise ValueError(
                    "인증이 필요한 API입니다. "
                    ".env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY를 설정하세요."
                )
            token = self._create_jwt_token(query_string)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _send(self, method, url, **kwargs):
        self._limiter.wait_if_needed()
        t0 = time.time()
        resp = method(url, **kwargs)
        elapsed_ms = (time.time() - t0) * 1000

        # Update rate limiter from response header
        remaining = resp.headers.get("Remaining-Req", "")
        self._limiter.update_from_header(remaining)
        if resp.status_code == 429:
            self._limiter.mark_exhausted()

        logger.info(
            "%s %s → %d (%.0fms) [%s]",
            resp.request.method, url, resp.status_code, elapsed_ms, remaining,
        )

        # Parse response
        if 200 <= resp.status_code < 300:
            try:
                return resp.json()
            except ValueError:
                return resp.text

        # Error handling
        try:
            ej = resp.json()
            if isinstance(ej, dict) and "error" in ej:
                e = ej["error"]
                error_info = {
                    "status_code": resp.status_code,
                    "error_name": e.get("name"),
                    "error_message": e.get("message"),
                }
                level = logging.DEBUG if resp.status_code == 404 else logging.WARNING
                logger.log(level, "API error: %s", error_info)
                return error_info
            return {"status_code": resp.status_code, "body": ej}
        except ValueError:
            return {"status_code": resp.status_code, "body": resp.text}
