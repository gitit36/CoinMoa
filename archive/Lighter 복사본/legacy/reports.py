"""Profit report computations, reconciliation, and breakdown exports."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd


@dataclass
class InitialCapitalInference:
    """Initial capital inference result."""

    estimated_beginning_equity: float
    method: str
    confidence: str
    caveats: List[str]


@dataclass
class ProfitSummary:
    """Top-level profit summary."""

    net_deposits: float
    realized_pnl: float
    unrealized_pnl: float
    fees_plus_funding: float
    airdrop_tokens_received: float
    token_sold_qty: float
    token_vwap_sell_price: float
    token_sale_proceeds: float
    token_sales_pnl: float
    ending_equity: float
    beginning_equity_estimate: float
    total_profit: float


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _series_contains(series: pd.Series, needle: str) -> pd.Series:
    return series.fillna("").astype(str).str.contains(needle, case=False, regex=False)


def infer_initial_capital(
    unified_df: pd.DataFrame,
    ending_equity: float,
    net_deposits: float,
    net_pnl_components: float,
) -> InitialCapitalInference:
    """Infer beginning equity using reconciliation and exposure fallback."""
    caveats: List[str] = []

    recon_estimate = ending_equity - net_deposits - net_pnl_components
    method = "reconciliation"
    confidence = "medium"

    # Fallback bound from running signed quote exposure if reconciliation is weak.
    signed = pd.to_numeric(unified_df.get("signed_quote_value"), errors="coerce").fillna(0.0)
    running = signed.cumsum()
    max_capital_proxy = float(abs(running.min())) if len(running) else 0.0

    if recon_estimate < 0:
        caveats.append("Reconciliation produced negative beginning equity; replaced with max-exposure proxy.")
        recon_estimate = max_capital_proxy
        method = "max_exposure_proxy"
        confidence = "low"

    if net_deposits == 0:
        caveats.append("No explicit deposits/withdrawals found; initial capital estimate has high uncertainty.")
        if max_capital_proxy > recon_estimate:
            recon_estimate = max_capital_proxy
            method = "max_exposure_proxy"
            confidence = "low"

    if max_capital_proxy > 0:
        caveats.append(f"Max signed-quote exposure proxy observed: {max_capital_proxy:.4f}.")

    return InitialCapitalInference(
        estimated_beginning_equity=float(recon_estimate),
        method=method,
        confidence=confidence,
        caveats=caveats,
    )


def _token_sell_summary(unified_df: pd.DataFrame, token_keyword: str = "LIT") -> Dict[str, float]:
    pair = unified_df.get("페어", pd.Series(dtype=str)).fillna("").astype(str)
    subtype = unified_df.get("event_subtype", pd.Series(dtype=str)).fillna("").astype(str)

    token_mask = pair.str.contains(token_keyword, case=False, regex=False)
    trade_mask = subtype.isin(["trade", "liquidation"])
    sell_mask = unified_df.get("유형", pd.Series(dtype=str)).fillna("") == "매도"

    token_sells = unified_df[token_mask & trade_mask & sell_mask].copy()
    qty = pd.to_numeric(token_sells.get("quantity"), errors="coerce").fillna(0.0)
    proceeds = pd.to_numeric(token_sells.get("quote_value"), errors="coerce").fillna(0.0)

    sold_qty = float(qty.sum())
    sale_proceeds = float(proceeds.sum())
    vwap = float(sale_proceeds / sold_qty) if sold_qty > 0 else 0.0

    # Cost basis assumption: airdrop cost = 0. If token deposits exist, treat them as zero-cost unless explicit basis present.
    token_sales_pnl = sale_proceeds
    return {
        "token_sold_qty": sold_qty,
        "token_vwap_sell_price": vwap,
        "token_sale_proceeds": sale_proceeds,
        "token_sales_pnl": token_sales_pnl,
    }


def build_profit_report(
    unified_df: pd.DataFrame,
    balance_snapshot: Dict[str, Any],
    token_keyword: str = "LIT",
) -> Tuple[Dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Compute total profit summary and daily/monthly breakdowns."""
    df = unified_df.copy()
    ts = pd.to_datetime(df.get("timestamp"), errors="coerce", utc=True)
    df["date"] = ts.dt.date.astype("string")
    df["month"] = ts.dt.to_period("M").astype("string")

    transfer_rows = df[df.get("event_group", "") == "transfer"]
    deposits = transfer_rows[transfer_rows.get("event_subtype", "") == "deposit"]
    withdrawals = transfer_rows[transfer_rows.get("event_subtype", "") == "withdraw"]

    net_deposits = float(pd.to_numeric(deposits.get("quote_value"), errors="coerce").fillna(0.0).sum() - pd.to_numeric(withdrawals.get("quote_value"), errors="coerce").fillna(0.0).sum())

    realized_pnl = _safe_float(balance_snapshot.get("realized_pnl"))
    unrealized_pnl = _safe_float(balance_snapshot.get("unrealized_pnl"))

    fee_total = float(pd.to_numeric(df.get("fee_usd"), errors="coerce").fillna(0.0).sum())
    funding_total = float(pd.to_numeric(df.get("funding_usd"), errors="coerce").fillna(0.0).sum())
    fees_plus_funding = -(fee_total + funding_total)

    airdrop_mask = df.get("is_airdrop", pd.Series(dtype=bool)).fillna(False)
    airdrop_tokens_received = float(pd.to_numeric(df.loc[airdrop_mask, "quantity"], errors="coerce").fillna(0.0).sum())
    airdrop_timestamps = [str(x) for x in df.loc[airdrop_mask, "일시"].dropna().tolist()]

    token_summary = _token_sell_summary(df, token_keyword=token_keyword)

    ending_equity = _safe_float(balance_snapshot.get("ending_equity"))

    pnl_components = realized_pnl + unrealized_pnl + fees_plus_funding + token_summary["token_sales_pnl"]
    init = infer_initial_capital(
        unified_df=df,
        ending_equity=ending_equity,
        net_deposits=net_deposits,
        net_pnl_components=pnl_components,
    )

    total_profit = ending_equity - init.estimated_beginning_equity

    summary = ProfitSummary(
        net_deposits=net_deposits,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        fees_plus_funding=fees_plus_funding,
        airdrop_tokens_received=airdrop_tokens_received,
        token_sold_qty=token_summary["token_sold_qty"],
        token_vwap_sell_price=token_summary["token_vwap_sell_price"],
        token_sale_proceeds=token_summary["token_sale_proceeds"],
        token_sales_pnl=token_summary["token_sales_pnl"],
        ending_equity=ending_equity,
        beginning_equity_estimate=init.estimated_beginning_equity,
        total_profit=total_profit,
    )

    recon_table = {
        "BeginningEquity(estimated)": init.estimated_beginning_equity,
        "+NetDeposits": net_deposits,
        "+RealizedPnL": realized_pnl,
        "+UnrealizedPnL": unrealized_pnl,
        "+TokenSalesPnL": token_summary["token_sales_pnl"],
        "+FeesFunding(net)": fees_plus_funding,
        "=EndingEquity": ending_equity,
    }

    daily = (
        df.groupby("date", dropna=True)
        .agg(
            net_signed_quote=("signed_quote_value", "sum"),
            trade_notional=("quote_value", "sum"),
            fees=("fee_usd", "sum"),
            funding=("funding_usd", "sum"),
            airdrop_qty=("quantity", lambda s: pd.to_numeric(s, errors="coerce").fillna(0.0).sum()),
            events=("event_group", "count"),
        )
        .reset_index()
        .sort_values("date")
    )

    monthly = (
        df.groupby("month", dropna=True)
        .agg(
            net_signed_quote=("signed_quote_value", "sum"),
            trade_notional=("quote_value", "sum"),
            fees=("fee_usd", "sum"),
            funding=("funding_usd", "sum"),
            airdrop_qty=("quantity", lambda s: pd.to_numeric(s, errors="coerce").fillna(0.0).sum()),
            events=("event_group", "count"),
        )
        .reset_index()
        .sort_values("month")
    )

    report: Dict[str, Any] = {
        "summary": asdict(summary),
        "initial_capital_inference": asdict(init),
        "airdrop_timestamps": airdrop_timestamps,
        "reconciliation": recon_table,
    }

    return report, daily, monthly


def print_console_report(report: Dict[str, Any]) -> None:
    """Render concise console report."""
    s = report["summary"]
    inf = report["initial_capital_inference"]

    print("\n================ Profit Report ================")
    print(f"Net deposits: {s['net_deposits']:.6f}")
    print(f"Realized PnL: {s['realized_pnl']:.6f}")
    print(f"Unrealized PnL: {s['unrealized_pnl']:.6f}")
    print(f"Fees + funding (net): {s['fees_plus_funding']:.6f}")
    print(f"Airdrop tokens received: {s['airdrop_tokens_received']:.6f}")
    print(f"Token sold qty: {s['token_sold_qty']:.6f}")
    print(f"Token sell VWAP: {s['token_vwap_sell_price']:.6f}")
    print(f"Token sale proceeds: {s['token_sale_proceeds']:.6f}")
    print(f"Token sales PnL: {s['token_sales_pnl']:.6f}")
    print(f"Beginning equity (est.): {s['beginning_equity_estimate']:.6f}")
    print(f"Ending equity: {s['ending_equity']:.6f}")
    print(f"Total profit: {s['total_profit']:.6f}")

    print("\nInitial capital inference")
    print(f"Method: {inf['method']}")
    print(f"Confidence: {inf['confidence']}")
    if inf["caveats"]:
        for caveat in inf["caveats"]:
            print(f"- {caveat}")

    print("\nReconciliation")
    for k, v in report["reconciliation"].items():
        print(f"{k}: {float(v):.6f}")
