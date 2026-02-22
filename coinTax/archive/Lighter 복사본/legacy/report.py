"""Profit report generation with initial capital inference and reconciliation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from extractors.airdrops import summarize_token_sales


@dataclass
class ProfitReport:
    totals: dict[str, Any]
    reconciliation: pd.DataFrame
    by_day: pd.DataFrame
    by_month: pd.DataFrame


def _safe_sum(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df:
        return 0.0
    return float(df[col].fillna(0.0).sum())


def build_profit_report(
    *,
    trades: pd.DataFrame,
    transfers: pd.DataFrame,
    snapshots: pd.DataFrame,
    airdrops: pd.DataFrame,
) -> ProfitReport:
    """Compute final earnings summary and reconciliation table."""
    deposits = _safe_sum(transfers[transfers["event_type"] == "deposit"], "amount_quote") if not transfers.empty else 0.0
    withdrawals = _safe_sum(transfers[transfers["event_type"] == "withdraw"], "amount_quote") if not transfers.empty else 0.0
    net_deposits = deposits - withdrawals

    realized = _safe_sum(trades, "realized_pnl")
    unrealized = _safe_sum(snapshots, "unrealized_pnl_quote")
    fees = _safe_sum(trades, "fee_quote")
    funding = _safe_sum(trades, "funding_quote")

    airdrop_qty = _safe_sum(airdrops, "quantity")
    token_sales = summarize_token_sales(trades, token_keyword="LIT")

    ending_equity = 0.0
    if not snapshots.empty:
        ending_equity = float(snapshots.iloc[-1].get("total_asset_value_quote") or snapshots.iloc[-1].get("collateral_quote") or 0.0)

    net_pnl_components = realized + unrealized + funding - fees + float(token_sales["token_sale_pnl_quote"])

    # Reconcile without reliable beginning snapshot
    beginning_equity_est = ending_equity - net_deposits - net_pnl_components
    total_profit = ending_equity - beginning_equity_est

    if not snapshots.empty and len(snapshots) > 1:
        confidence = "high"
        method = "balance-history"
    elif deposits or withdrawals:
        confidence = "medium"
        method = "cashflow-pnl-reconciliation"
    else:
        confidence = "low"
        method = "exposure-based-heuristic"
        if not trades.empty:
            beginning_equity_est = max(float(trades["notional_quote"].max() * 0.03), 0.0)
            total_profit = ending_equity - beginning_equity_est

    recon = pd.DataFrame(
        [
            {"item": "BeginningEquity(estimated)", "value_quote": beginning_equity_est},
            {"item": "+ Deposits", "value_quote": deposits},
            {"item": "- Withdrawals", "value_quote": withdrawals},
            {"item": "+ RealizedPnL", "value_quote": realized},
            {"item": "+ UnrealizedPnL", "value_quote": unrealized},
            {"item": "+ Funding", "value_quote": funding},
            {"item": "- Fees", "value_quote": fees},
            {"item": "+ TokenSalePnL", "value_quote": float(token_sales["token_sale_pnl_quote"])},
            {"item": "= EndingEquity", "value_quote": ending_equity},
        ]
    )

    by_day = pd.DataFrame(columns=["date", "notional_quote", "realized_pnl", "fees", "funding"])
    by_month = pd.DataFrame(columns=["month", "notional_quote", "realized_pnl", "fees", "funding"])
    if not trades.empty:
        t = trades.copy()
        t["date"] = pd.to_datetime(t["timestamp"]).dt.date
        t["month"] = pd.to_datetime(t["timestamp"]).dt.to_period("M").astype(str)
        by_day = (
            t.groupby("date", as_index=False)
            .agg(notional_quote=("notional_quote", "sum"), realized_pnl=("realized_pnl", "sum"), fees=("fee_quote", "sum"), funding=("funding_quote", "sum"))
            .sort_values("date")
        )
        by_month = (
            t.groupby("month", as_index=False)
            .agg(notional_quote=("notional_quote", "sum"), realized_pnl=("realized_pnl", "sum"), fees=("fee_quote", "sum"), funding=("funding_quote", "sum"))
            .sort_values("month")
        )

    totals = {
        "net_deposits_quote": net_deposits,
        "deposits_quote": deposits,
        "withdrawals_quote": withdrawals,
        "realized_pnl_quote": realized,
        "unrealized_pnl_quote": unrealized,
        "fees_quote": fees,
        "funding_quote": funding,
        "airdrop_tokens_received": airdrop_qty,
        "token_sell_qty": float(token_sales["qty_sold"]),
        "token_sell_vwap": float(token_sales["vwap_sell_price"]),
        "token_sell_proceeds_quote": float(token_sales["proceeds_quote"]),
        "token_sale_pnl_quote": float(token_sales["token_sale_pnl_quote"]),
        "beginning_equity_estimate_quote": beginning_equity_est,
        "ending_equity_quote": ending_equity,
        "total_profit_quote": total_profit,
        "initial_capital_method": method,
        "initial_capital_confidence": confidence,
        "caveats": (
            "Historical balance snapshots may be unavailable via API. "
            "Beginning equity is estimated from reconciliation; token cost basis assumed zero for airdrop-derived sales."
        ),
    }

    return ProfitReport(totals=totals, reconciliation=recon, by_day=by_day, by_month=by_month)
