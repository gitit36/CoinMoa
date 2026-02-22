#!/usr/bin/env python3
"""
unified_txlog.py — 통합 거래 이력 (Upbit · Bithumb · Lighter)

단일 CSV 로 모든 거래소의 입금/출금/매수/매도/청산/이체 이벤트를 시간순으로 정렬·병합합니다.

Usage:
  python unified_txlog.py 2024-01-01 2024-12-31
  python unified_txlog.py 2024-01-01 2024-12-31 --out all_timeline.csv
  python unified_txlog.py 2024-01-01 2024-12-31 --exchanges upbit,lighter --fx 1350
  python unified_txlog.py 2025-01-01 2025-06-30 --exchanges bithumb --out bithumb_only.csv

Dependencies (pip install):
  python-dotenv  requests  pandas  PyJWT

Required .env per exchange:
  Upbit   : UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY
  Bithumb : BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY
  Lighter : LIGHTER_RO_TOKEN, LIGHTER_ACCOUNT_INDEX
            (optional: LIGHTER_L1_ADDRESS, LIGHTER_BASE_URL, LIGHTER_MARKET_ID, FX_KRW_PER_USD)
"""

from __future__ import annotations

import sys
import argparse
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Optional

from txlog import (
    KST,
    FxRates,
    CryptoPrice,
    fetch_deposits_in_range,
    fetch_withdrawals_in_range,
    fetch_orders_in_range_upbit,
    fetch_orders_in_range_bithumb,
)
from upbit_client import UpbitClient
from bithumb_client import BithumbClient
import lighter_txlog

logging.basicConfig(level=logging.WARNING)

# ── Canonical Schema ──────────────────────────────────────────────────────────
CANONICAL_COLS = [
    "ts_kst",        # timezone-aware datetime (정렬용)
    "일시",           # "YYYY-MM-DD-HH-MM-SS" (KST)
    "거래소",         # "Upbit" / "Bithumb" / "Lighter"
    "유형",           # "입금" / "출금" / "매수" / "매도" / "청산" / "이체"
    "페어",           # e.g. "KRW-BTC", "BTC-USD"
    "통화",           # base asset or currency
    "수량",           # float or None
    "가격",           # float or None
    "원화가치",       # float (KRW)
    "적용환율",       # float (KRW per USD)
    "수수료",         # float (KRW) or None
    "txid_or_uuid",  # str
]


def _empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_COLS)


def _parse_kst(iso_str: str) -> datetime:
    """ISO datetime string → KST-aware datetime."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _fmt_kst(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d-%H-%M-%S")


# ── Upbit / Bithumb (공통 로직) ──────────────────────────────────────────────

def _collect_cex_events(
    exchange_key: str,
    start_date: str,
    end_date: str,
    fx_override: Optional[float] = None,
) -> pd.DataFrame:
    """Upbit 또는 Bithumb 에서 입금·출금·매수·매도 이벤트를 수집하여 canonical DF 로 반환."""
    if exchange_key == "upbit":
        client = UpbitClient()
        name = "Upbit"
    else:
        client = BithumbClient()
        name = "Bithumb"

    dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=KST)
    dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=KST) + timedelta(days=1)

    fx = FxRates()
    if fx_override is None:
        fx.preload(start_date, end_date)
    cp = CryptoPrice(client)

    rows: list[dict] = []

    def _rate(tx_date: str) -> float:
        return fx_override if fx_override is not None else fx.get(tx_date)

    # ── Deposits ──────────────────────────────────────────────────────────────
    print(f"  [{name}] 입금 내역 조회 중...")
    for d in fetch_deposits_in_range(client, exchange_key, dt_start, dt_end):
        cur = d.get("currency", "")
        amt = float(d.get("amount", 0))
        fee = float(d.get("fee", 0))
        dt = _parse_kst(d["created_at"])
        tx_date = d["created_at"][:10]
        rate = _rate(tx_date)

        if cur == "KRW":
            krw = amt
            coin_price = None
            fee_krw = fee if fee else None
        else:
            coin_price = cp.get_krw(cur, tx_date)
            krw = amt * coin_price
            fee_krw = fee * coin_price if fee else None

        rows.append({
            "ts_kst": dt, "일시": _fmt_kst(dt), "거래소": name,
            "유형": "입금", "페어": "", "통화": cur,
            "수량": amt, "가격": coin_price,
            "원화가치": krw, "적용환율": rate,
            "수수료": fee_krw, "txid_or_uuid": d.get("txid", ""),
        })

    # ── Withdrawals ───────────────────────────────────────────────────────────
    print(f"  [{name}] 출금 내역 조회 중...")
    for w in fetch_withdrawals_in_range(client, exchange_key, dt_start, dt_end):
        cur = w.get("currency", "")
        amt = float(w.get("amount", 0))
        fee = float(w.get("fee", 0))
        dt = _parse_kst(w["created_at"])
        tx_date = w["created_at"][:10]
        rate = _rate(tx_date)

        if cur == "KRW":
            krw = amt + fee
            coin_price = None
            fee_krw = fee if fee else None
        else:
            coin_price = cp.get_krw(cur, tx_date)
            krw = (amt + fee) * coin_price
            fee_krw = fee * coin_price if fee else None

        rows.append({
            "ts_kst": dt, "일시": _fmt_kst(dt), "거래소": name,
            "유형": "출금", "페어": "", "통화": cur,
            "수량": amt, "가격": coin_price,
            "원화가치": krw, "적용환율": rate,
            "수수료": fee_krw, "txid_or_uuid": w.get("txid", ""),
        })

    # ── Orders (buy + sell) ───────────────────────────────────────────────────
    for side, label in [("bid", "매수"), ("ask", "매도")]:
        print(f"  [{name}] {label} 내역 조회 중...")
        if exchange_key == "upbit":
            orders = fetch_orders_in_range_upbit(client, start_date, end_date, side)
        else:
            orders = fetch_orders_in_range_bithumb(client, dt_start, dt_end, side)

        for o in orders:
            market = o.get("market", "")
            parts = market.split("-")
            if len(parts) != 2:
                continue
            quote, coin = parts
            vol = float(o.get("executed_volume") or 0)
            funds = float(o.get("executed_funds") or 0)
            fee = float(o.get("paid_fee") or 0)
            dt = _parse_kst(o["created_at"])
            tx_date = o["created_at"][:10]
            rate = _rate(tx_date)

            krw = (funds + fee) if side == "bid" else (funds - fee)
            avg_px = funds / vol if vol else 0

            rows.append({
                "ts_kst": dt, "일시": _fmt_kst(dt), "거래소": name,
                "유형": label, "페어": market, "통화": coin,
                "수량": vol, "가격": avg_px,
                "원화가치": krw, "적용환율": rate,
                "수수료": fee, "txid_or_uuid": o.get("uuid", ""),
            })

    if not rows:
        return _empty_canonical()
    return pd.DataFrame(rows)[CANONICAL_COLS]


def get_upbit_events(
    start_date: str, end_date: str, fx_override: Optional[float] = None,
) -> pd.DataFrame:
    """Upbit 이벤트 수집 → canonical DataFrame."""
    return _collect_cex_events("upbit", start_date, end_date, fx_override)


def get_bithumb_events(
    start_date: str, end_date: str, fx_override: Optional[float] = None,
) -> pd.DataFrame:
    """Bithumb 이벤트 수집 → canonical DataFrame."""
    return _collect_cex_events("bithumb", start_date, end_date, fx_override)


# ── Lighter ───────────────────────────────────────────────────────────────────

def get_lighter_events(
    start_date: str, end_date: str, fx_override: Optional[float] = None,
) -> pd.DataFrame:
    """Lighter 이벤트 수집 → canonical DataFrame."""
    if fx_override is not None:
        lighter_txlog.FX_KRW_PER_USD_RAW = str(fx_override)

    print("  [Lighter] 타임라인 수집 중...")
    timeline = lighter_txlog.build_lighter_timeline(
        max_pages=50, limit=100, include_deposit=True,
    )

    if timeline.empty:
        return _empty_canonical()

    # 날짜 필터
    dt_start = pd.Timestamp(start_date, tz="Asia/Seoul")
    dt_end = pd.Timestamp(end_date, tz="Asia/Seoul") + pd.Timedelta(days=1)

    if "_sort_ts" in timeline.columns:
        valid = timeline["_sort_ts"].notna()
        in_range = (timeline["_sort_ts"] >= dt_start) & (timeline["_sort_ts"] < dt_end)
        timeline = timeline.loc[valid & in_range].copy()

    if timeline.empty:
        return _empty_canonical()

    out = pd.DataFrame(index=timeline.index)
    out["ts_kst"] = timeline["_sort_ts"]
    out["일시"] = timeline["일시"]
    out["거래소"] = "Lighter"
    out["유형"] = timeline["유형"]
    out["페어"] = timeline["페어"]
    out["통화"] = timeline["통화"]
    out["수량"] = None
    out["가격"] = timeline["가격"]
    out["원화가치"] = timeline["원화가치"]
    out["적용환율"] = timeline["적용환율"]
    out["수수료"] = timeline["수수료"] if "수수료" in timeline.columns else None
    out["txid_or_uuid"] = ""

    return out[CANONICAL_COLS].reset_index(drop=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

_EXCHANGE_HANDLERS = {
    "upbit": get_upbit_events,
    "bithumb": get_bithumb_events,
    "lighter": get_lighter_events,
}

_ENV_HINTS = {
    "upbit": "UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY",
    "bithumb": "BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY",
    "lighter": "LIGHTER_RO_TOKEN, LIGHTER_ACCOUNT_INDEX",
}


def main():
    parser = argparse.ArgumentParser(
        description="통합 거래 이력: Upbit · Bithumb · Lighter → 단일 CSV",
    )
    parser.add_argument("start_date", help="시작일 (YYYY-MM-DD)")
    parser.add_argument("end_date", help="종료일 (YYYY-MM-DD)")
    parser.add_argument(
        "--out", default="unified_timeline.csv",
        help="출력 CSV 경로 (기본: unified_timeline.csv)",
    )
    parser.add_argument(
        "--exchanges", default="upbit,bithumb,lighter",
        help="거래소 목록 (comma-separated, 기본: upbit,bithumb,lighter)",
    )
    parser.add_argument(
        "--fx", type=float, default=None,
        help="FX_KRW_PER_USD override (예: 1300)",
    )
    args = parser.parse_args()

    for d in (args.start_date, args.end_date):
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            print(f"  ❌ 날짜 형식 오류: {d} → YYYY-MM-DD 형식이어야 합니다.")
            sys.exit(1)

    exchanges = [x.strip().lower() for x in args.exchanges.split(",") if x.strip()]
    unknown = set(exchanges) - set(_EXCHANGE_HANDLERS)
    if unknown:
        print(f"  ❌ 알 수 없는 거래소: {unknown}")
        print(f"     사용 가능: {', '.join(_EXCHANGE_HANDLERS)}")
        sys.exit(1)

    print(f"\n  📋 통합 거래 이력 ({args.start_date} ~ {args.end_date})")
    print(f"     거래소 : {', '.join(exchanges)}")
    if args.fx is not None:
        print(f"     환율   : {args.fx:,.1f} ₩/$")
    print(f"     출력   : {args.out}\n")

    frames: list[pd.DataFrame] = []
    for ex in exchanges:
        try:
            print(f"  ── {ex.upper()} {'─' * 50}")
            df = _EXCHANGE_HANDLERS[ex](args.start_date, args.end_date, fx_override=args.fx)
            print(f"     → {len(df)}건\n")
            frames.append(df)
        except Exception as e:
            print(f"  ⚠️  {ex} 수집 실패: {e}")
            print(f"     필요 환경변수: {_ENV_HINTS.get(ex, '(확인 필요)')}\n")

    if not frames:
        print("  ❌ 수집된 이벤트가 없습니다.")
        sys.exit(1)

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values("ts_kst", na_position="last").reset_index(drop=True)

    merged.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"  ✅ 저장 완료: {args.out}  (총 {len(merged)}건)")


if __name__ == "__main__":
    main()

# ── 실행 예시 ─────────────────────────────────────────────────────────────────
# 전체 거래소, 기본 출력:
#   python unified_txlog.py 2024-01-01 2024-12-31
#
# 특정 거래소만, 환율 override:
#   python unified_txlog.py 2024-01-01 2024-12-31 --exchanges upbit,lighter --fx 1350
#
# Bithumb만, 커스텀 파일명:
#   python unified_txlog.py 2025-01-01 2025-06-30 --exchanges bithumb --out bithumb_2025.csv
#
# Lighter만:
#   python unified_txlog.py 2024-06-01 2024-12-31 --exchanges lighter --fx 1400 --out lighter.csv
