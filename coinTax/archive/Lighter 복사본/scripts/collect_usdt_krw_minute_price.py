"""Collect USDT/KRW spot prices every minute at second 00.

The script polls public ticker endpoints from Upbit and Bithumb, then appends
one row per exchange for each minute boundary.
"""
from __future__ import annotations

import argparse
import csv
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

UPBIT_TICKER_URL = "https://api.upbit.com/v1/ticker"
BITHUMB_V1_TICKER_URL = "https://api.bithumb.com/v1/ticker"
BITHUMB_LEGACY_TICKER_URL = "https://api.bithumb.com/public/ticker/USDT_KRW"


def utc_minute_string(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_csv_header(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["exchange", "market", "timestamp_utc", "price_krw"])


def retry_after_seconds(response: requests.Response) -> float:
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def request_json_with_backoff(
    session: requests.Session,
    *,
    method: str,
    url: str,
    timeout: float,
    params: dict[str, Any] | None = None,
    max_retries: int = 6,
    base_delay: float = 1.0,
) -> Any:
    """Request JSON with rate-limit and transient-error backoff."""
    attempt = 0
    while True:
        try:
            resp = session.request(method, url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"request failed after retries: {exc}") from exc
            delay = min(60.0, base_delay * (2**attempt)) + random.uniform(0, 0.25)
            print(f"[warn] network error ({exc}); retry in {delay:.2f}s")
            time.sleep(delay)
            attempt += 1
            continue

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            if attempt >= max_retries:
                raise RuntimeError(f"HTTP {resp.status_code} from {url}: retry budget exhausted")
            hinted = retry_after_seconds(resp)
            delay = hinted if hinted > 0 else min(60.0, base_delay * (2**attempt))
            delay += random.uniform(0, 0.25)
            print(f"[warn] HTTP {resp.status_code} from {url}; retry in {delay:.2f}s")
            time.sleep(delay)
            attempt += 1
            continue

        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(f"non-JSON response from {url}: {resp.text[:200]}") from exc


def fetch_upbit_price_krw(session: requests.Session, timeout: float) -> float:
    data = request_json_with_backoff(
        session,
        method="GET",
        url=UPBIT_TICKER_URL,
        params={"markets": "KRW-USDT"},
        timeout=timeout,
    )
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"unexpected Upbit payload: {data}")
    price = data[0].get("trade_price")
    if price is None:
        raise RuntimeError(f"missing Upbit trade_price: {data[0]}")
    return float(price)


def fetch_bithumb_price_krw(session: requests.Session, timeout: float) -> float:
    # Prefer v1 endpoint, fallback to legacy public endpoint for compatibility.
    try:
        data = request_json_with_backoff(
            session,
            method="GET",
            url=BITHUMB_V1_TICKER_URL,
            params={"markets": "KRW-USDT"},
            timeout=timeout,
        )
        if isinstance(data, list) and data:
            price = data[0].get("trade_price")
            if price is not None:
                return float(price)
    except Exception as exc:
        print(f"[warn] bithumb v1 ticker failed ({exc}); trying legacy endpoint")

    legacy = request_json_with_backoff(
        session,
        method="GET",
        url=BITHUMB_LEGACY_TICKER_URL,
        timeout=timeout,
    )
    status = str(legacy.get("status", "")) if isinstance(legacy, dict) else ""
    data = legacy.get("data", {}) if isinstance(legacy, dict) else {}
    if status and status != "0000":
        raise RuntimeError(f"Bithumb legacy status is {status}: {legacy}")

    closing_price = data.get("closing_price") if isinstance(data, dict) else None
    if closing_price is None:
        raise RuntimeError(f"missing Bithumb closing_price: {legacy}")
    return float(closing_price)


def append_rows(path: Path, rows: list[tuple[str, str, str, float]]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def next_minute_boundary_epoch(now: float | None = None) -> float:
    now = time.time() if now is None else now
    return (int(now) // 60 + 1) * 60


def run_collector(output: Path, timeout: float, minutes: int | None) -> None:
    ensure_csv_header(output)

    print(f"output: {output}")
    print("collecting KRW-USDT ticker prices at each UTC minute boundary (second 00)")

    collected = 0
    with requests.Session() as session:
        while True:
            target = next_minute_boundary_epoch()
            sleep_for = max(0.0, target - time.time())
            if sleep_for > 0:
                time.sleep(sleep_for)

            ts_str = utc_minute_string(target)

            rows: list[tuple[str, str, str, float]] = []
            try:
                upbit_price = fetch_upbit_price_krw(session, timeout=timeout)
                rows.append(("upbit", "KRW-USDT", ts_str, upbit_price))
            except Exception as exc:
                print(f"[error] upbit fetch failed at {ts_str}: {exc}")

            try:
                bithumb_price = fetch_bithumb_price_krw(session, timeout=timeout)
                rows.append(("bithumb", "KRW-USDT", ts_str, bithumb_price))
            except Exception as exc:
                print(f"[error] bithumb fetch failed at {ts_str}: {exc}")

            if rows:
                append_rows(output, rows)
                print(f"{ts_str} | wrote {len(rows)} row(s): " + ", ".join(f"{r[0]}={r[3]}" for r in rows))
            else:
                print(f"{ts_str} | no rows written")

            collected += 1
            if minutes is not None and collected >= minutes:
                print(f"done: collected {collected} minute(s)")
                return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect USDT/KRW ticker prices from Upbit and Bithumb every minute at second 00."
    )
    parser.add_argument(
        "--output",
        default="usdt_krw_minute_price.csv",
        help="Output CSV path (default: usdt_krw_minute_price.csv)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=None,
        help="Stop after N minutes (default: run forever)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    run_collector(output=output, timeout=args.timeout, minutes=args.minutes)


if __name__ == "__main__":
    main()
