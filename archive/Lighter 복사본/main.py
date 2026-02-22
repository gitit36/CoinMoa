"""Entrypoint: reconstruct full account lifecycle from API inception."""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict

import pandas as pd

from api_client import APIClient
from config import get_settings
from extractors.airdrops import fetch_airdrops_and_token_transfers, summarize_token_sales
from extractors.balances import fetch_balance_history
from extractors.trades import fetch_trades
from extractors.transfers import fetch_transfers
from transform import (
    OUTPUT_COLUMNS,
    build_reconstructed_schema,
    deposit_verification_summary,
    infer_initial_deposit_if_missing,
)


def _ensure_api_coverage(
    statuses: list,
    transfers: pd.DataFrame,
    trades: pd.DataFrame,
) -> None:
    """Fail loudly when core API extraction coverage is missing."""
    by_name = {s.name: s for s in statuses}
    core = [
        "trades",
        "deposit/history",
        "withdraw/history",
        "l1Metadata",
    ]
    missing = [name for name in core if name not in by_name]
    failed = [name for name in core if name in by_name and not by_name[name].success]

    # If we cannot hit any core cashflow/trade endpoints and have no records, abort.
    no_data = transfers.empty and trades.empty
    all_core_failed = len(failed) == len([c for c in core if c in by_name])
    if missing or (no_data and all_core_failed):
        details = {
            "missing_core_status": missing,
            "failed_core_endpoints": failed,
            "transfers_rows": int(len(transfers)),
            "trades_rows": int(len(trades)),
        }
        raise RuntimeError(
            "API-first extraction failed. Core endpoint coverage is insufficient. "
            f"details={json.dumps(details, ensure_ascii=False)}"
        )


def _print_endpoint_statuses(statuses: list) -> None:
    print("\n=== Endpoint Status ===")
    for s in statuses:
        state = "OK" if s.success else "FAIL"
        print(f"{state:4} | {s.name:30} | records={s.records:6} | {s.error[:180]}")


def _print_deposit_summary(summary, inference_info: dict[str, float | str | bool]) -> None:
    print("\n=== Deposit Verification Summary ===")
    print(f"Total deposits:      {summary.total_deposits:.6f}")
    print(f"Total withdrawals:   {summary.total_withdrawals:.6f}")
    print(f"Net deposits:        {summary.net_deposits:.6f}")
    print(f"Earliest timestamp:  {summary.earliest_timestamp}")
    lo, hi = summary.approximate_600_band
    print(f"Has ~600 deposit:    {summary.has_approximately_600} (band: {lo:.2f} ~ {hi:.2f})")

    print("\nInitial deposit recovery details:")
    print(f"- inferred_initial_deposit: {float(inference_info.get('inferred_initial_deposit', 0.0)):.6f}")
    print(f"- injected_inferred_deposit: {bool(inference_info.get('injected_inferred_deposit', False))}")
    print(f"- earliest_equity: {float(inference_info.get('earliest_equity', 0.0)):.6f}")
    print(f"- reconciliation_estimate: {float(inference_info.get('reconciliation_estimate', 0.0)):.6f}")
    print(f"- exposure_proxy: {float(inference_info.get('exposure_proxy', 0.0)):.6f}")


def _build_profit_snapshot(
    trades: pd.DataFrame,
    balances: pd.DataFrame,
    transfers: pd.DataFrame,
    airdrops: pd.DataFrame,
) -> dict[str, float]:
    deposits = float(transfers.loc[transfers["event_type"] == "deposit", "amount_quote"].sum()) if not transfers.empty else 0.0
    withdrawals = float(transfers.loc[transfers["event_type"] == "withdraw", "amount_quote"].sum()) if not transfers.empty else 0.0
    net_deposits = deposits - withdrawals

    fees = float(trades["fee_quote"].sum()) if not trades.empty else 0.0
    funding = float(trades["funding_quote"].sum()) if not trades.empty else 0.0
    realized = float(trades["realized_pnl"].sum()) if not trades.empty else 0.0

    unrealized = 0.0
    ending_equity = 0.0
    if not balances.empty:
        ending_equity = float(balances.iloc[-1].get("total_asset_value_quote", 0.0) or 0.0)
        unrealized = float(balances.iloc[-1].get("unrealized_pnl_quote", 0.0) or 0.0)

    token_sales = summarize_token_sales(trades)
    airdrop_qty = float(airdrops.loc[airdrops["event_type"] == "airdrop", "quantity"].sum()) if not airdrops.empty else 0.0

    return {
        "deposits_quote": deposits,
        "withdrawals_quote": withdrawals,
        "net_deposits_quote": net_deposits,
        "realized_pnl_quote": realized,
        "unrealized_pnl_quote": unrealized,
        "fees_quote": fees,
        "funding_quote": funding,
        "airdrop_tokens_received": airdrop_qty,
        "token_sold_qty": float(token_sales["qty_sold"]),
        "token_sell_vwap": float(token_sales["vwap_sell_price"]),
        "token_sell_proceeds_quote": float(token_sales["proceeds_quote"]),
        "token_sell_pnl_quote": float(token_sales["token_sale_pnl_quote"]),
        "ending_equity_quote": ending_equity,
    }


def main() -> None:
    settings = get_settings()
    reconstruction_dir = Path("outputs/reconstruction")
    reconstruction_dir.mkdir(parents=True, exist_ok=True)
    reconstructed_csv_path = reconstruction_dir / "reconstructed_full_history.csv"
    diagnostics_json_path = reconstruction_dir / "reconstruction_diagnostics.json"
    endpoint_statuses_json_path = reconstruction_dir / "endpoint_statuses.json"

    with APIClient(settings) as client:
        transfers = fetch_transfers(client)
        trades = fetch_trades(client)
        balances = fetch_balance_history(client)
        airdrops = fetch_airdrops_and_token_transfers(client, transfers)
        _ensure_api_coverage(client.endpoint_statuses, transfers=transfers, trades=trades)

        transfers, inference_info = infer_initial_deposit_if_missing(transfers, trades, balances)
        verification = deposit_verification_summary(transfers, trades, balances, approx_target=600.0, tolerance=75.0)

        reconstructed = build_reconstructed_schema(
            trades=trades,
            transfers=transfers,
            # USD-first output: keep value column in USD not KRW.
            fx_rate=1.0,
            exchange_label="DEX",
        )

        # Ensure schema order and UTC ISO timestamps.
        reconstructed = reconstructed.sort_values("timestamp").reset_index(drop=True)
        reconstructed["Unnamed: 0"] = range(len(reconstructed))
        output = reconstructed[OUTPUT_COLUMNS]
        output.to_csv(reconstructed_csv_path, index=False)

        _print_endpoint_statuses(client.endpoint_statuses)
        _print_deposit_summary(verification, inference_info)

        profit_snapshot = _build_profit_snapshot(trades, balances, transfers, airdrops)
        print("\n=== Profit Snapshot ===")
        for key, value in profit_snapshot.items():
            print(f"{key}: {value:.6f}")

        # Persist diagnostics for auditing endpoint availability and inference rationale.
        diagnostics = {
            "deposit_verification": asdict(verification),
            "inference_info": inference_info,
            "endpoint_statuses": [asdict(x) for x in client.endpoint_statuses],
            "profit_snapshot": profit_snapshot,
            "record_counts": {
                "transfers": int(len(transfers)),
                "trades": int(len(trades)),
                "balances": int(len(balances)),
                "airdrops": int(len(airdrops)),
                "reconstructed_rows": int(len(output)),
            },
        }
        with open(diagnostics_json_path, "w", encoding="utf-8") as f:
            json.dump(diagnostics, f, ensure_ascii=False, indent=2, default=str)
        with open(endpoint_statuses_json_path, "w", encoding="utf-8") as f:
            json.dump([asdict(x) for x in client.endpoint_statuses], f, ensure_ascii=False, indent=2)

        print(f"\nExported: {reconstructed_csv_path}")
        print(f"Exported: {diagnostics_json_path}")
        print(f"Exported: {endpoint_statuses_json_path}")


if __name__ == "__main__":
    main()
