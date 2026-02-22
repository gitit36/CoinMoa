"""HTTP API client with retries, pagination, and auth handling."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import requests

from config import Settings


@dataclass
class EndpointStatus:
    """Endpoint result metadata for observability."""

    name: str
    success: bool
    records: int
    error: str = ""


class APIClientError(RuntimeError):
    """Raised when API calls fail irrecoverably."""


class APIClient:
    """Resilient API client for full-history extraction."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.endpoint_statuses: list[EndpointStatus] = []
        self._auth_token: Optional[str] = None

    def close(self) -> None:
        """Close HTTP session."""
        self.session.close()

    def __enter__(self) -> "APIClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _build_auth_token(self) -> Optional[str]:
        token = self.settings.read_only_auth_token
        if token:
            return token

        if not self.settings.api_key_private_key or self.settings.api_key_private_key == "your_api_key_private_key_hex":
            return None

        try:
            import lighter  # type: ignore
        except Exception as exc:
            raise APIClientError(
                "Auth token creation needs lighter-sdk when READ_ONLY_AUTH_TOKEN is absent"
            ) from exc

        signer = lighter.SignerClient(
            url=self.settings.base_url,
            api_private_keys={self.settings.api_key_index: self.settings.api_key_private_key},
            account_index=self.settings.account_index,
        )
        out = signer.create_auth_token_with_expiry(deadline=3600, api_key_index=self.settings.api_key_index)
        if isinstance(out, (tuple, list)):
            return str(out[0])
        return str(out)

    def auth_token(self) -> Optional[str]:
        """Lazy auth token getter."""
        if self._auth_token is None:
            self._auth_token = self._build_auth_token()
        return self._auth_token

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        auth_required: bool = False,
    ) -> Any:
        params = dict(params or {})
        headers: dict[str, str] = {}

        token = self.auth_token() if auth_required else None
        if auth_required:
            if not token:
                raise APIClientError("Auth required but no token is available")
            params["auth"] = token
            headers["Authorization"] = f"Bearer {token}" if token.startswith("ro:") else token

        last_error: Optional[Exception] = None
        for attempt in range(self.settings.max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=headers,
                    timeout=self.settings.request_timeout_seconds,
                )

                # read-only token fallback to raw Authorization when Bearer fails.
                if (
                    response.status_code == 401
                    and auth_required
                    and token
                    and token.startswith("ro:")
                    and headers.get("Authorization", "").startswith("Bearer ")
                ):
                    headers["Authorization"] = token
                    response = self.session.request(
                        method=method,
                        url=url,
                        params=params,
                        headers=headers,
                        timeout=self.settings.request_timeout_seconds,
                    )

                if response.status_code in (429, 500, 502, 503, 504):
                    delay = min(self.settings.backoff_base_seconds * (2**attempt), 12.0) + random.uniform(0, 0.25)
                    time.sleep(delay)
                    continue

                if response.status_code >= 400:
                    raise APIClientError(f"HTTP {response.status_code}: {response.text[:400]}")

                time.sleep(self.settings.rate_limit_sleep_seconds)
                if not response.text.strip():
                    return {}
                return response.json()

            except (requests.RequestException, ValueError, APIClientError) as exc:
                last_error = exc
                delay = min(self.settings.backoff_base_seconds * (2**attempt), 12.0) + random.uniform(0, 0.25)
                time.sleep(delay)

        raise APIClientError(f"Request failed after retries: {url}; last_error={last_error}")

    def get_account_snapshot(self) -> dict[str, Any]:
        """Fetch account snapshot."""
        payload = self._request_json(
            "GET",
            f"{self.settings.base_url}/api/v1/account",
            params={"by": "index", "value": str(self.settings.account_index)},
            auth_required=False,
        )
        if isinstance(payload, dict):
            accounts = payload.get("accounts")
            if isinstance(accounts, list) and accounts:
                first = accounts[0]
                if isinstance(first, dict):
                    return first
        return payload if isinstance(payload, dict) else {"raw": payload}

    def _extract_list_payload(self, payload: Any, data_keys: Iterable[str]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if not isinstance(payload, dict):
            return []
        for key in data_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return []

    def paginate_v1(
        self,
        endpoint: str,
        *,
        auth_required: bool,
        base_params: Optional[dict[str, Any]] = None,
        data_keys: Iterable[str] = ("items", "data", "trades", "logs"),
        page_limit: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Offset pagination for /api/v1 endpoints."""
        all_rows: list[dict[str, Any]] = []
        offset = 0
        limit = page_limit or self.settings.page_limit
        pages = max_pages or self.settings.max_pages

        for _ in range(pages):
            params = dict(base_params or {})
            params.update({"limit": limit, "offset": offset})
            payload = self._request_json(
                "GET",
                f"{self.settings.base_url}/api/v1/{endpoint.lstrip('/')}",
                params=params,
                auth_required=auth_required,
            )
            batch = self._extract_list_payload(payload, data_keys)
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < limit:
                break
            offset += len(batch)

        return all_rows

    def paginate_explorer_logs(
        self,
        param: str,
        *,
        page_size: int = 100,
        max_pages: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Explorer pagination for full account logs."""
        all_rows: list[dict[str, Any]] = []
        offset = 0
        pages = max_pages or self.settings.max_pages
        base = f"{self.settings.explorer_base_url}/api/accounts/{param}/logs"

        for _ in range(pages):
            params = {"offset": offset} if offset else {}
            payload = self._request_json("GET", base, params=params, auth_required=False)
            if not isinstance(payload, list) or not payload:
                break
            batch = [x for x in payload if isinstance(x, dict)]
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += len(batch)

        return all_rows


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse common timestamp formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit() and len(text) in (10, 13):
        ts = int(text)
        if len(text) == 13:
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    patterns = (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d-%H-%M-%S",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def utc_iso(dt: Optional[datetime]) -> str:
    """Format datetime as UTC ISO-8601."""
    if dt is None:
        return ""
    fixed = dt.astimezone(timezone.utc)
    return fixed.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_float(value: Any, default: float = 0.0) -> float:
    """Safe float conversion."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
