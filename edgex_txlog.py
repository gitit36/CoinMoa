"""
EdgeX transaction timeline exporter.

- Fetches position transaction history and collateral transaction history
- Normalizes into the same timeline shape used by lighter_txlog.py
- Sorts by time (KST) and exports to CSV

Env vars (.env supported via python-dotenv):
  EDGEX_BASE_URL=https://pro.edgex.exchange     (optional)
  EDGEX_ACCOUNT_ID=12345                        (required)
  EDGEX_STARK_PRIVATE_KEY=0xabc...              (required)
  FX_KRW_PER_USD=1300.0                         (optional)

Dependency:
  pip install edgex-python-sdk
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Callable, Optional

import pandas as pd
from dotenv import load_dotenv


load_dotenv()

BASE_URL = os.getenv("EDGEX_BASE_URL", "https://pro.edgex.exchange").rstrip("/")
ACCOUNT_ID_RAW = os.getenv("EDGEX_ACCOUNT_ID", "").strip()
STARK_PRIVATE_KEY = os.getenv("EDGEX_STARK_PRIVATE_KEY", "").strip()
FX_KRW_PER_USD_RAW = os.getenv("FX_KRW_PER_USD", "1300.0").strip()

ACCOUNT_ID: int = 0
FX_KRW_PER_USD: float = 1300.0


def _ensure_env() -> None:
    global ACCOUNT_ID, FX_KRW_PER_USD
    if not ACCOUNT_ID_RAW:
        raise ValueError("Missing EDGEX_ACCOUNT_ID in .env or environment.")
    if not STARK_PRIVATE_KEY:
        raise ValueError("Missing EDGEX_STARK_PRIVATE_KEY in .env or environment.")
    try:
        ACCOUNT_ID = int(ACCOUNT_ID_RAW)
    except Exception as exc:
        raise ValueError("EDGEX_ACCOUNT_ID must be an integer.") from exc
    try:
        FX_KRW_PER_USD = float(FX_KRW_PER_USD_RAW)
    except Exception as exc:
        raise ValueError("FX_KRW_PER_USD must be a float.") from exc


def _get_sdk_classes() -> tuple[Any, Any, Any]:
    try:
        from edgex_sdk import Client
        from edgex_sdk.account.client import (
            GetCollateralTransactionPageParams,
            GetPositionTransactionPageParams,
        )
    except ImportError as exc:
        raise ImportError(
            "EdgeX requires edgex-python-sdk. Install it with `pip install edgex-python-sdk`."
        ) from exc
    return Client, GetCollateralTransactionPageParams, GetPositionTransactionPageParams


def _build_client() -> Any:
    Client, _, _ = _get_sdk_classes()
    return Client(
        base_url=BASE_URL,
        account_id=ACCOUNT_ID,
        stark_private_key=STARK_PRIVATE_KEY,
    )


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _normalize_edgex_error(exc: Exception) -> str:
    text = str(exc)
    if "ACCOUNT_ID_WHITELIST_ERROR" in text:
        return (
            "EdgeX API rejected this account with ACCOUNT_ID_WHITELIST_ERROR. "
            "The account is not whitelisted for private API access."
        )
    return text


def _to_kst(ts: Any) -> Optional[pd.Timestamp]:
    if ts is None or ts == "":
        return None

    for unit in ("ms", "s"):
        try:
            return pd.to_datetime(ts, unit=unit, utc=True).tz_convert("Asia/Seoul")
        except Exception:
            pass

    try:
        dt = pd.to_datetime(ts, utc=True)
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.tz_localize("UTC")
        return dt.tz_convert("Asia/Seoul")
    except Exception:
        return None


def _base_currency_from_pair(pair: str) -> str:
    if not isinstance(pair, str) or not pair:
        return ""
    normalized = pair.replace("/", "-").replace("_", "-")
    if "-" in normalized:
        return normalized.split("-")[0]
    return normalized


def _pick_first(row: pd.Series, keys: list[str]) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _pair_from_row(row: pd.Series) -> str:
    value = _pick_first(
        row,
        [
            "symbol",
            "market",
            "pair",
            "futureName",
            "contractName",
            "instrumentName",
            "positionName",
        ],
    )
    if not isinstance(value, str):
        return ""
    return value.replace("/", "-").replace("_", "-")


def _timestamp_series(df: pd.DataFrame) -> pd.Series:
    for key in ("createdTime", "created_at", "timestamp", "time"):
        if key in df.columns:
            return df[key]
    return pd.Series([None] * len(df), index=df.index)


def _sort_ts_series(df: pd.DataFrame) -> pd.Series:
    return pd.Series(pd.DatetimeIndex(_timestamp_series(df).apply(_to_kst)), index=df.index)


def _asset_series(df: pd.DataFrame) -> pd.Series:
    for key in ("coinSymbol", "asset", "currency", "coinName", "coinId"):
        if key in df.columns:
            return df[key]
    return pd.Series(["USDC"] * len(df), index=df.index)


def _price_series(df: pd.DataFrame) -> pd.Series:
    for key in ("fillPrice", "price", "avgPrice", "averageOpenPrice"):
        if key in df.columns:
            return df[key].apply(_safe_float)
    return pd.Series([None] * len(df), index=df.index)


def _classify_position_type(row: pd.Series) -> Optional[str]:
    tx_type = str(row.get("type") or "").upper()
    if "LIQUID" in tx_type or "ADL" in tx_type:
        return "청산"
    if "BUY" in tx_type or "LONG_OPEN" in tx_type or "LONG_INCREASE" in tx_type:
        return "매수"
    if "SELL" in tx_type or "SHORT_OPEN" in tx_type or "SHORT_INCREASE" in tx_type:
        return "매도"
    if "CLOSE" in tx_type and "BUY" in tx_type:
        return "매수"
    if "CLOSE" in tx_type and "SELL" in tx_type:
        return "매도"
    return None


def _classify_collateral_type(row: pd.Series) -> str:
    tx_type = str(row.get("type") or "").upper()
    if "TRANSFER" in tx_type:
        return "이체"
    if "WITHDRAW" in tx_type or "OUT" in tx_type:
        return "출금"
    if "DEPOSIT" in tx_type or "IN" in tx_type:
        return "입금"
    return "이체"


def _amount_from_collateral(row: pd.Series) -> float:
    for key in (
        "deltaAmount",
        "amount",
        "usdcAmount",
        "transferAmount",
        "changeAmount",
    ):
        value = _safe_float(row.get(key))
        if value is not None:
            return abs(value)
    return 0.0


def _fee_from_row(row: pd.Series) -> float:
    for key in (
        "fillCloseFee",
        "deltaOpenFee",
        "fee",
        "tradeFee",
        "closeFee",
        "openFee",
        "withdrawFee",
    ):
        value = _safe_float(row.get(key))
        if value is not None:
            return abs(value)
    return 0.0


def _notional_from_position(row: pd.Series) -> float:
    size = None
    for key in ("fillCloseSize", "deltaOpenSize", "size", "quantity", "qty"):
        size = _safe_float(row.get(key))
        if size is not None:
            break

    price = None
    for key in ("fillPrice", "price", "avgPrice", "averageOpenPrice"):
        price = _safe_float(row.get(key))
        if price is not None:
            break

    if size is not None and price is not None:
        return abs(size * price)

    for key in ("fillAmount", "turnover", "notional", "tradeValue", "quoteAmount"):
        value = _safe_float(row.get(key))
        if value is not None:
            return abs(value)
    return 0.0


async def _paginate(
    fetcher: Callable[[Any], Any],
    params_cls: Any,
    limit: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset_data = ""

    for _ in range(max_pages):
        params = params_cls(size=str(min(limit, 100)), offset_data=offset_data)
        try:
            resp = await fetcher(params)
        except Exception as exc:
            raise RuntimeError(_normalize_edgex_error(exc)) from exc
        if not resp or resp.get("code") != "SUCCESS":
            message = (resp or {}).get("msg") if isinstance(resp, dict) else ""
            raise RuntimeError(message or "EdgeX API request failed.")

        data = resp.get("data") or {}
        page_rows = data.get("dataList") or []
        if not isinstance(page_rows, list) or not page_rows:
            break

        rows.extend(page_rows)
        next_offset = data.get("offsetData") or data.get("offset_data") or ""
        if not next_offset or next_offset == offset_data:
            break
        offset_data = next_offset

    return rows


async def fetch_position_transactions(max_pages: int = 50, limit: int = 100) -> pd.DataFrame:
    _ensure_env()
    _, _, params_cls = _get_sdk_classes()
    async with _build_client() as client:
        rows = await _paginate(client.account.get_position_transaction_page, params_cls, limit, max_pages)
        return pd.DataFrame(rows)


async def fetch_collateral_transactions(max_pages: int = 50, limit: int = 100) -> pd.DataFrame:
    _ensure_env()
    _, params_cls, _ = _get_sdk_classes()
    async with _build_client() as client:
        rows = await _paginate(client.account.get_collateral_transaction_page, params_cls, limit, max_pages)
        return pd.DataFrame(rows)


def position_events_to_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "적용환율", "수수료", "_sort_ts"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    out = df.copy()
    out["유형"] = out.apply(_classify_position_type, axis=1)
    out = out[out["유형"].notna()].copy()
    if out.empty:
        return pd.DataFrame(columns=cols)

    out["_sort_ts"] = _sort_ts_series(out)
    out["일시"] = out["_sort_ts"].dt.strftime("%Y-%m-%d-%H-%M-%S")
    out["거래소"] = "EdgeX"
    out["페어"] = out.apply(_pair_from_row, axis=1)
    out["통화"] = out["페어"].apply(_base_currency_from_pair)
    out["가격"] = _price_series(out)
    out["적용환율"] = float(FX_KRW_PER_USD)
    out["원화가치"] = out.apply(_notional_from_position, axis=1) * out["적용환율"]
    out["수수료"] = out.apply(_fee_from_row, axis=1) * out["적용환율"]
    return out[cols].copy()


def collateral_events_to_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "적용환율", "수수료", "_sort_ts"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    out = df.copy()
    out["_sort_ts"] = _sort_ts_series(out)
    out["일시"] = out["_sort_ts"].dt.strftime("%Y-%m-%d-%H-%M-%S")
    out["거래소"] = "EdgeX"
    out["유형"] = out.apply(_classify_collateral_type, axis=1)
    out["페어"] = ""
    out["통화"] = _asset_series(out)
    out["가격"] = None
    out["적용환율"] = float(FX_KRW_PER_USD)
    out["원화가치"] = out.apply(_amount_from_collateral, axis=1) * out["적용환율"]
    out["수수료"] = out.apply(_fee_from_row, axis=1) * out["적용환율"]
    return out[cols].copy()


async def build_edgex_timeline(max_pages: int = 50, limit: int = 100) -> pd.DataFrame:
    _ensure_env()
    positions = await fetch_position_transactions(max_pages=max_pages, limit=limit)
    collateral = await fetch_collateral_transactions(max_pages=max_pages, limit=limit)

    timeline = pd.concat(
        [
            position_events_to_df(positions),
            collateral_events_to_df(collateral),
        ],
        ignore_index=True,
    )
    if timeline.empty:
        return timeline
    return timeline.sort_values(by=["_sort_ts"], na_position="last").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=50, help="Max pages to fetch per endpoint.")
    parser.add_argument("--limit", type=int, default=100, help="Page size per endpoint.")
    parser.add_argument("--out", type=str, default="edgex_timeline.csv", help="Output CSV path.")
    args = parser.parse_args()

    try:
        timeline_df = asyncio.run(build_edgex_timeline(max_pages=args.pages, limit=args.limit))
    except Exception as exc:
        print(f"error: {_normalize_edgex_error(exc)}", file=sys.stderr)
        raise SystemExit(1) from exc
    timeline_view = timeline_df.drop(columns=["_sort_ts"], errors="ignore")
    timeline_view.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"saved: {args.out}  (rows={len(timeline_view)})")


if __name__ == "__main__":
    main()
