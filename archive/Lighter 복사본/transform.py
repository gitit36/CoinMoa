"""Normalization and reconciliation utilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from api_client import utc_iso

OUTPUT_COLUMNS = ["Unnamed: 0", "일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "적용환율"]


@dataclass
class DepositVerification:
    """Deposit verification summary."""

    total_deposits: float
    total_withdrawals: float
    net_deposits: float
    earliest_timestamp: str
    has_approximately_600: bool
    approximate_600_band: tuple[float, float]


def _event_type_from_trade(side: str, liquidation: bool) -> str:
    if liquidation:
        return "청산"
    if side == "buy":
        return "매수"
    if side == "sell":
        return "매도"
    return "거래"


def _build_trade_rows(trades: pd.DataFrame, fx_rate: float, exchange_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if trades.empty:
        return rows

    for _, t in trades.iterrows():
        ts = t.get("timestamp")
        if pd.isna(ts):
            continue
        notional = float(t.get("notional_quote", 0.0) or 0.0)
        row = {
            "timestamp": pd.Timestamp(ts).to_pydatetime().astimezone(timezone.utc),
            "거래소": exchange_label,
            "유형": _event_type_from_trade(str(t.get("side") or ""), bool(t.get("liquidation", False))),
            "페어": str(t.get("market") or "") or pd.NA,
            "통화": pd.NA,
            "가격": float(t.get("price", 0.0) or 0.0),
            "원화가치": notional * fx_rate,
            "적용환율": fx_rate,
        }
        rows.append(row)
    return rows


def _build_transfer_rows(transfers: pd.DataFrame, fx_rate: float, exchange_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if transfers.empty:
        return rows

    type_map = {"deposit": "입금", "withdraw": "출금", "transfer": "이체"}
    for _, x in transfers.iterrows():
        ts = x.get("timestamp")
        if pd.isna(ts):
            continue
        amount = float(x.get("amount_quote", 0.0) or 0.0)
        event_type = str(x.get("event_type") or "transfer")

        row = {
            "timestamp": pd.Timestamp(ts).to_pydatetime().astimezone(timezone.utc),
            "거래소": exchange_label,
            "유형": type_map.get(event_type, "이체"),
            "페어": pd.NA,
            "통화": pd.NA,
            "가격": pd.NA,
            "원화가치": amount * fx_rate,
            "적용환율": fx_rate,
        }
        rows.append(row)
    return rows


def build_reconstructed_schema(
    trades: pd.DataFrame,
    transfers: pd.DataFrame,
    *,
    fx_rate: float,
    exchange_label: str,
) -> pd.DataFrame:
    """Build schema-matched dataframe in chronological order."""
    rows = _build_trade_rows(trades, fx_rate, exchange_label)
    rows.extend(_build_transfer_rows(transfers, fx_rate, exchange_label))

    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df.insert(0, "Unnamed: 0", range(len(df)))
    df["일시"] = df["timestamp"].apply(utc_iso)
    df = df[OUTPUT_COLUMNS + ["timestamp"]]
    return df


def infer_initial_deposit_if_missing(
    transfers: pd.DataFrame,
    trades: pd.DataFrame,
    balances: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Infer an initial deposit row if transfer history misses early capital."""
    transfers = transfers.copy()

    deposits = float(transfers.loc[transfers["event_type"] == "deposit", "amount_quote"].sum()) if not transfers.empty else 0.0
    withdrawals = float(transfers.loc[transfers["event_type"] == "withdraw", "amount_quote"].sum()) if not transfers.empty else 0.0

    earliest_ts: datetime | None = None
    for candidate_df in (transfers, trades, balances):
        if not candidate_df.empty and "timestamp" in candidate_df:
            ts = pd.to_datetime(candidate_df["timestamp"], errors="coerce", utc=True).dropna()
            if not ts.empty:
                ts_min = ts.min().to_pydatetime()
                earliest_ts = ts_min if earliest_ts is None else min(earliest_ts, ts_min)

    ending_equity = 0.0
    earliest_equity = 0.0
    realized = 0.0
    unrealized = 0.0

    if not balances.empty:
        b = balances.sort_values("timestamp").reset_index(drop=True)
        ending_equity = float(b.iloc[-1].get("total_asset_value_quote", 0.0) or 0.0)
        earliest_equity = float(b.iloc[0].get("total_asset_value_quote", 0.0) or 0.0)
        realized = float(b.iloc[-1].get("realized_pnl_quote", 0.0) or 0.0)
        unrealized = float(b.iloc[-1].get("unrealized_pnl_quote", 0.0) or 0.0)

    fee_total = float(trades["fee_quote"].sum()) if not trades.empty else 0.0
    funding_total = float(trades["funding_quote"].sum()) if not trades.empty else 0.0

    # Exposure proxy from signed trading cashflow.
    exposure_proxy = 0.0
    if not trades.empty:
        t = trades.sort_values("timestamp").copy()
        sign = t["side"].map({"buy": -1.0, "sell": 1.0}).fillna(0.0)
        signed = sign * t["notional_quote"].fillna(0.0) - t["fee_quote"].fillna(0.0) + t["funding_quote"].fillna(0.0)
        running = signed.cumsum()
        exposure_proxy = max(0.0, float(-running.min())) if not running.empty else 0.0

    # Reconciliation estimate.
    net_deposits = deposits - withdrawals
    net_pnl_components = realized + unrealized + funding_total - fee_total
    recon_estimate = ending_equity - net_deposits - net_pnl_components

    candidate_estimates = [x for x in (earliest_equity, recon_estimate, exposure_proxy) if x > 0]
    inferred_initial = max(candidate_estimates) if candidate_estimates else 0.0

    injected = False
    if deposits <= 0.0 and inferred_initial > 0.0 and earliest_ts is not None:
        inferred_time = earliest_ts - timedelta(seconds=1)
        inferred_row = {
            "timestamp": inferred_time,
            "event_type": "deposit",
            "asset": "USDC",
            "amount_quote": float(inferred_initial),
            "fee_quote": 0.0,
            "tx_hash": "inferred_initial_deposit",
            "source": "inference",
            "raw": {
                "reason": "deposit history missing; inferred from balance/trade reconciliation",
                "earliest_equity": earliest_equity,
                "reconciliation_estimate": recon_estimate,
                "exposure_proxy": exposure_proxy,
            },
        }
        transfers = pd.concat([pd.DataFrame([inferred_row]), transfers], ignore_index=True)
        transfers = transfers.sort_values("timestamp").reset_index(drop=True)
        deposits = float(transfers.loc[transfers["event_type"] == "deposit", "amount_quote"].sum())
        withdrawals = float(transfers.loc[transfers["event_type"] == "withdraw", "amount_quote"].sum())
        net_deposits = deposits - withdrawals
        injected = True

    info = {
        "inferred_initial_deposit": inferred_initial,
        "injected_inferred_deposit": injected,
        "earliest_equity": earliest_equity,
        "reconciliation_estimate": recon_estimate,
        "exposure_proxy": exposure_proxy,
        "ending_equity": ending_equity,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "fees_total": fee_total,
        "funding_total": funding_total,
        "total_deposits": deposits,
        "total_withdrawals": withdrawals,
        "net_deposits": net_deposits,
        "earliest_timestamp": utc_iso(earliest_ts),
    }
    return transfers, info


def deposit_verification_summary(
    transfers: pd.DataFrame,
    trades: pd.DataFrame,
    balances: pd.DataFrame,
    *,
    approx_target: float = 600.0,
    tolerance: float = 75.0,
) -> DepositVerification:
    """Compute deposit totals and whether ~600 was captured."""
    timestamps: list[datetime] = []
    for df in (transfers, trades, balances):
        if not df.empty and "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dropna()
            if not ts.empty:
                timestamps.append(ts.min().to_pydatetime())

    earliest = min(timestamps).astimezone(timezone.utc) if timestamps else None
    deposits = float(transfers.loc[transfers["event_type"] == "deposit", "amount_quote"].sum()) if not transfers.empty else 0.0
    withdrawals = float(transfers.loc[transfers["event_type"] == "withdraw", "amount_quote"].sum()) if not transfers.empty else 0.0
    net = deposits - withdrawals

    low = approx_target - tolerance
    high = approx_target + tolerance
    approx = low <= deposits <= high

    return DepositVerification(
        total_deposits=deposits,
        total_withdrawals=withdrawals,
        net_deposits=net,
        earliest_timestamp=utc_iso(earliest),
        has_approximately_600=approx,
        approximate_600_band=(low, high),
    )
