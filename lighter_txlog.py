"""
Lighter.xyz (zkLighter) Transaction Timeline Exporter

- Fetches trades (including liquidations) + deposit/withdraw/transfer history
- Normalizes into a single canonical table
- Sorts by time (KST) and exports to CSV

Env vars (.env supported via python-dotenv):
  LIGHTER_RO_TOKEN=ro:...              (required)
  LIGHTER_ACCOUNT_INDEX=12345          (required, int)
  LIGHTER_L1_ADDRESS=0xabc...          (optional; used for deposit history)
  LIGHTER_BASE_URL=https://...         (optional; default mainnet.zklighter.elliot.ai)
  LIGHTER_MARKET_ID=255                (optional; default 255)
  FX_KRW_PER_USD=1300.0                (optional; default 1300.0)

Usage:
  python lighter_txlog.py --pages 50 --limit 100 --out test_lighter.csv

Notes:
- This code uses query param auth=RO_TOKEN (not Authorization header), because
  some history endpoints commonly accept auth that way.
"""

from __future__ import annotations

import argparse
import random
import time

import requests
import pandas as pd
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
import os


# ========= ENV / SETTINGS =========
load_dotenv()

RO_TOKEN = os.getenv("LIGHTER_RO_TOKEN", "").strip()
BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
ACCOUNT_INDEX_RAW = os.getenv("LIGHTER_ACCOUNT_INDEX", "").strip()
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS", "").strip()  # optional
MARKET_ID_RAW = os.getenv("LIGHTER_MARKET_ID", "255").strip()
FX_KRW_PER_USD_RAW = os.getenv("FX_KRW_PER_USD", "1300.0").strip()

ACCOUNT_INDEX: int = 0
MARKET_ID: int = 255
FX_KRW_PER_USD: float = 1300.0


def _ensure_env():
    """Validate required env vars and parse globals. Call before any API usage."""
    global ACCOUNT_INDEX, MARKET_ID, FX_KRW_PER_USD
    if not RO_TOKEN:
        raise ValueError("Missing LIGHTER_RO_TOKEN in .env or environment.")
    if not ACCOUNT_INDEX_RAW:
        raise ValueError("Missing LIGHTER_ACCOUNT_INDEX in .env or environment.")
    try:
        ACCOUNT_INDEX = int(ACCOUNT_INDEX_RAW)
    except Exception as e:
        raise ValueError("LIGHTER_ACCOUNT_INDEX must be an integer.") from e
    try:
        MARKET_ID = int(MARKET_ID_RAW)
    except Exception as e:
        raise ValueError("LIGHTER_MARKET_ID must be an integer.") from e
    try:
        FX_KRW_PER_USD = float(FX_KRW_PER_USD_RAW)
    except Exception as e:
        raise ValueError("FX_KRW_PER_USD must be a float.") from e

# ========= HTTP SESSION =========
SESSION = requests.Session()
SESSION.headers.update({"accept": "application/json"})  # auth is passed via query param


# ========= UTIL =========
_MAX_RETRIES = 4
_BACKOFF_BASE = 0.8  # seconds
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def _get(url: str, params: Dict[str, Any] | None, timeout: int = 30) -> Dict[str, Any]:
    """
    GET JSON with query-param auth.
    Retries with exponential backoff on transient HTTP errors (429/5xx).
    """
    params = dict(params or {})
    params.setdefault("auth", RO_TOKEN)

    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            if r.status_code in _RETRYABLE_STATUS:
                last_exc = RuntimeError(f"HTTP {r.status_code}")
                delay = min(_BACKOFF_BASE * (2 ** attempt), 12.0) + random.uniform(0, 0.25)
                time.sleep(delay)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1:
                delay = min(_BACKOFF_BASE * (2 ** attempt), 12.0) + random.uniform(0, 0.25)
                time.sleep(delay)
    raise last_exc or RuntimeError(f"Request failed after {_MAX_RETRIES} retries: {url}")


def _extract_next_cursor(resp: Dict[str, Any]) -> Optional[str]:
    for k in ["next_cursor", "nextCursor"]:
        v = resp.get(k)
        if isinstance(v, str) and v:
            return v
    v = resp.get("cursor")
    if isinstance(v, str) and v:
        return v
    if isinstance(v, dict):
        for kk in ["next", "next_cursor", "nextCursor"]:
            vv = v.get(kk)
            if isinstance(vv, str) and vv:
                return vv
    return None


def _to_dt_kst_from_ms(ts_ms: Any) -> Optional[pd.Timestamp]:
    try:
        return pd.to_datetime(ts_ms, unit="ms", utc=True).tz_convert("Asia/Seoul")
    except Exception:
        return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


# ========= 0) Market map (market_id -> pair string) =========
def fetch_order_books() -> Any:
    return _get(
        f"{BASE_URL}/api/v1/orderBooks",
        params={"market_id": MARKET_ID, "filter": "all"},
    )


def build_market_pair_map() -> Dict[int, str]:
    ob = fetch_order_books()
    candidates: List[Any] = []

    if isinstance(ob, dict):
        if isinstance(ob.get("order_books"), list):
            candidates = ob["order_books"]
        elif isinstance(ob.get("data"), list):
            candidates = ob["data"]
        else:
            candidates = [ob]
    elif isinstance(ob, list):
        candidates = ob

    pair_map: Dict[int, str] = {}
    for it in candidates:
        if not isinstance(it, dict):
            continue
        mid = it.get("market_id") or it.get("marketId") or it.get("m") or it.get("id")
        try:
            mid_int = int(mid)
        except Exception:
            continue

        # Try direct pair fields
        for k in ["symbol", "pair", "name", "market", "ticker"]:
            v = it.get(k)
            if isinstance(v, str) and v:
                pair_map[mid_int] = v
                break

        # Try base/quote composition
        if mid_int not in pair_map:
            base = it.get("base_symbol") or it.get("base") or it.get("baseAsset") or it.get("base_asset")
            quote = it.get("quote_symbol") or it.get("quote") or it.get("quoteAsset") or it.get("quote_asset")
            if isinstance(base, str) and isinstance(quote, str) and base and quote:
                pair_map[mid_int] = f"{base}-{quote}"

    return pair_map


def base_currency_from_pair(pair: str) -> str:
    if isinstance(pair, str) and "-" in pair:
        return pair.split("-")[0]
    return ""


# ========= 1) Trades (trade + liquidation) =========
def fetch_trades_page(limit: int = 100, cursor: Optional[str] = None, type_: str = "all") -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "sort_by": "timestamp",
        "sort_dir": "desc",
        "limit": limit,
        "account_index": ACCOUNT_INDEX,
        "market_id": MARKET_ID,
        "type": type_,  # "all" often includes trade + liquidation
        "role": "all",
    }
    if cursor:
        params["cursor"] = cursor
    return _get(f"{BASE_URL}/api/v1/trades", params)


def fetch_trades(max_pages: int = 50, limit: int = 100, type_: str = "all") -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(max_pages):
        resp = fetch_trades_page(limit=limit, cursor=cursor, type_=type_)
        trades = resp.get("trades", [])
        if not isinstance(trades, list) or not trades:
            break
        rows.extend(trades)
        cursor = _extract_next_cursor(resp)
        if not cursor:
            break
    return pd.DataFrame(rows)


def classify_trade_row(row: pd.Series) -> str:
    if row.get("type") == "liquidation":
        return "청산"
    if row.get("bid_account_id") == ACCOUNT_INDEX:
        return "매수"
    if row.get("ask_account_id") == ACCOUNT_INDEX:
        return "매도"
    return "기타"


def _compute_trade_fee_usd(row: pd.Series) -> float:
    """Compute per-trade fee in USD from taker/maker fee bps (cherry-picked from Lighter 복사본)."""
    for key in ("fee", "fee_usd"):
        v = _safe_float(row.get(key))
        if v is not None and v != 0.0:
            return abs(v)

    me = str(ACCOUNT_INDEX)
    taker_idx = str(row.get("taker_account_index") or "")
    maker_idx = str(row.get("maker_account_index") or "")

    if me and me == taker_idx:
        fee_bps = _safe_float(row.get("taker_fee")) or 0.0
    elif me and me == maker_idx:
        fee_bps = _safe_float(row.get("maker_fee")) or 0.0
    else:
        fee_bps = _safe_float(row.get("taker_fee")) or 0.0

    if not fee_bps:
        return 0.0

    size = _safe_float(row.get("size") or row.get("quantity"))
    price = _safe_float(row.get("price"))
    if size and price:
        notional = abs(size * price)
    else:
        notional = abs(_safe_float(row.get("usd_amount")) or 0.0)

    return notional * fee_bps / 10_000.0 if notional else 0.0


def trades_to_final_df(df: pd.DataFrame, pair_map: Dict[int, str]) -> pd.DataFrame:
    cols = ["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "적용환율", "수수료", "_sort_ts"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    out = df.copy()

    out["_dt"] = out.get("timestamp").apply(_to_dt_kst_from_ms) if "timestamp" in out.columns else None
    out["_sort_ts"] = out["_dt"].astype("datetime64[ns, Asia/Seoul]")
    out["일시"] = out["_dt"].dt.strftime("%Y-%m-%d-%H-%M-%S")
    out["거래소"] = "Lighter"
    out["유형"] = out.apply(classify_trade_row, axis=1)

    out["페어"] = (
        out.get("market_id")
        .map(pair_map)
        .fillna(out.get("market_id").apply(lambda x: f"market_{x}"))
    )
    out["통화"] = out["페어"].apply(base_currency_from_pair)

    out["가격"] = out.get("price").apply(_safe_float) if "price" in out.columns else None
    out["usd_amount"] = out.get("usd_amount").apply(_safe_float) if "usd_amount" in out.columns else None

    out["적용환율"] = float(FX_KRW_PER_USD)
    out["원화가치"] = out["usd_amount"].fillna(0.0) * out["적용환율"]

    fee_usd = out.apply(_compute_trade_fee_usd, axis=1)
    out["수수료"] = fee_usd * float(FX_KRW_PER_USD)

    return out[cols].copy()


# ========= 2) Deposit/Withdraw/Transfer History =========
def try_get_l1_address_from_account() -> Optional[str]:
    """
    Some deposit endpoints require l1_address.
    Attempt to fetch it from /api/v1/account?by=index&value=ACCOUNT_INDEX
    """
    try:
        resp = _get(
            f"{BASE_URL}/api/v1/account",
            params={"by": "index", "value": str(ACCOUNT_INDEX)},
        )
    except Exception:
        return None

    candidates: List[Any] = []
    if isinstance(resp, dict):
        candidates.append(resp)
        if isinstance(resp.get("data"), dict):
            candidates.append(resp["data"])
        if isinstance(resp.get("account"), dict):
            candidates.append(resp["account"])

    for obj in candidates:
        if not isinstance(obj, dict):
            continue
        for k in ["l1_address", "l1Address", "owner", "owner_address", "eth_address", "ethAddress", "address"]:
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("0x") and len(v) >= 10:
                return v
    return None


def fetch_transfer_history(max_pages: int = 50, cursor: Optional[str] = None) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    cur = cursor
    for _ in range(max_pages):
        resp = _get(
            f"{BASE_URL}/api/v1/transfer/history",
            params={"account_index": ACCOUNT_INDEX, "cursor": cur} if cur else {"account_index": ACCOUNT_INDEX},
        )
        items = resp.get("transfers") or resp.get("data") or resp.get("items") or resp.get("results") or []
        if not isinstance(items, list) or not items:
            break
        rows.extend(items)
        nxt = _extract_next_cursor(resp)
        if not nxt or nxt == cur:
            break
        cur = nxt
    return pd.DataFrame(rows)


def fetch_withdraw_history(max_pages: int = 50, cursor: Optional[str] = None, filter_: str = "all") -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    cur = cursor
    for _ in range(max_pages):
        params: Dict[str, Any] = {"account_index": ACCOUNT_INDEX, "filter": filter_}
        if cur:
            params["cursor"] = cur
        resp = _get(f"{BASE_URL}/api/v1/withdraw/history", params=params)
        items = resp.get("withdraws") or resp.get("withdrawals") or resp.get("data") or resp.get("items") or resp.get("results") or []
        if not isinstance(items, list) or not items:
            break
        rows.extend(items)
        nxt = _extract_next_cursor(resp)
        if not nxt or nxt == cur:
            break
        cur = nxt
    return pd.DataFrame(rows)


def fetch_deposit_history(l1_address: str, max_pages: int = 50, cursor: Optional[str] = None, filter_: str = "all") -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    cur = cursor
    for _ in range(max_pages):
        params: Dict[str, Any] = {"account_index": ACCOUNT_INDEX, "l1_address": l1_address, "filter": filter_}
        if cur:
            params["cursor"] = cur
        resp = _get(f"{BASE_URL}/api/v1/deposit/history", params=params)
        items = resp.get("deposits") or resp.get("data") or resp.get("items") or resp.get("results") or []
        if not isinstance(items, list) or not items:
            break
        rows.extend(items)
        nxt = _extract_next_cursor(resp)
        if not nxt or nxt == cur:
            break
        cur = nxt
    return pd.DataFrame(rows)


def history_to_events_df(df: pd.DataFrame, event_type_kr: str) -> pd.DataFrame:
    cols = ["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "적용환율", "수수료", "_sort_ts"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    x = df.copy()

    # Timestamp column candidates
    ts_col = None
    for k in ["timestamp", "time", "created_at", "createdAt", "block_timestamp", "tx_time", "transaction_time"]:
        if k in x.columns:
            ts_col = k
            break

    if ts_col is not None:
        def to_dt(v):
            dt = _to_dt_kst_from_ms(v)
            if dt is not None:
                return dt
            try:
                return pd.to_datetime(v, unit="s", utc=True).tz_convert("Asia/Seoul")
            except Exception:
                return None
        x["_dt"] = x[ts_col].apply(to_dt)
    else:
        x["_dt"] = None

    x["_sort_ts"] = x["_dt"].astype("datetime64[ns, Asia/Seoul]")
    x["일시"] = x["_dt"].dt.strftime("%Y-%m-%d-%H-%M-%S")

    # Asset / amount candidates
    asset_col = None
    for k in ["asset", "asset_symbol", "token", "symbol", "currency", "coin"]:
        if k in x.columns:
            asset_col = k
            break

    amt_col = None
    for k in ["usd_amount", "amount_usd", "amountUsd", "amount", "amt", "value", "size", "quantity", "qty"]:
        if k in x.columns:
            amt_col = k
            break

    x["거래소"] = "Lighter"
    x["유형"] = event_type_kr
    x["페어"] = ""
    x["통화"] = x[asset_col] if asset_col else ""
    x["가격"] = None

    usd = x[amt_col].apply(_safe_float) if amt_col else None
    x["적용환율"] = float(FX_KRW_PER_USD)
    x["원화가치"] = (usd.fillna(0.0) if usd is not None else 0.0) * x["적용환율"]

    # Extract fee if present (cherry-picked from Lighter 복사본/extractors/transfers.py)
    fee_col = None
    for k in ("fee", "usdc_fee", "fee_usd"):
        if k in x.columns:
            fee_col = k
            break
    if fee_col is not None:
        fee_usd = x[fee_col].apply(_safe_float).fillna(0.0)
        x["수수료"] = fee_usd * float(FX_KRW_PER_USD)
    else:
        x["수수료"] = None

    return x[cols].copy()


# ========= Main workflow =========
def build_lighter_timeline(max_pages: int = 50, limit: int = 100, include_deposit: bool = True) -> pd.DataFrame:
    _ensure_env()
    pair_map = build_market_pair_map()

    # Trades (trade + liquidation)
    df_trades_all = fetch_trades(max_pages=max_pages, limit=limit, type_="all")
    final_trades_df = trades_to_final_df(df_trades_all, pair_map)

    # Withdraw / Transfer (no l1 needed)
    df_withdraw = fetch_withdraw_history(max_pages=max_pages)
    df_transfer = fetch_transfer_history(max_pages=max_pages)

    events_withdraw = history_to_events_df(df_withdraw, "출금")
    events_transfer = history_to_events_df(df_transfer, "이체")

    # Deposit (needs l1)
    if include_deposit:
        l1_addr = L1_ADDRESS or try_get_l1_address_from_account()
        if l1_addr:
            df_deposit = fetch_deposit_history(l1_address=l1_addr, max_pages=max_pages)
            events_deposit = history_to_events_df(df_deposit, "입금")
        else:
            events_deposit = pd.DataFrame(columns=events_withdraw.columns)
    else:
        events_deposit = pd.DataFrame(columns=events_withdraw.columns)

    timeline_df = pd.concat(
        [final_trades_df, events_deposit, events_withdraw, events_transfer],
        ignore_index=True,
    )

    timeline_df = timeline_df.sort_values(by=["_sort_ts"], na_position="last").reset_index(drop=True)
    return timeline_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=50, help="Max pages to fetch per endpoint.")
    ap.add_argument("--limit", type=int, default=100, help="Trades page size.")
    ap.add_argument("--out", type=str, default="test_lighter_sj_v0.3.csv", help="Output CSV path.")
    ap.add_argument("--no-deposit", action="store_true", help="Skip deposit history (if l1 address is problematic).")
    args = ap.parse_args()

    timeline_df = build_lighter_timeline(
        max_pages=args.pages,
        limit=args.limit,
        include_deposit=not args.no_deposit,
    )

    # Drop sort helper column for viewing/export
    timeline_view = timeline_df.drop(columns=["_sort_ts"], errors="ignore")
    timeline_view.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"✅ saved: {args.out}  (rows={len(timeline_view)})")


if __name__ == "__main__":
    main()
