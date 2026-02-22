"""Airdrop and token-event extraction utilities."""
from __future__ import annotations

from typing import Any

import pandas as pd

from api_client import APIClient, EndpointStatus, parse_timestamp, to_float


TOKEN_KEYWORDS = ("LIT", "LIGHTER")


def _looks_like_token(asset: str) -> bool:
    upper = asset.upper()
    return any(k in upper for k in TOKEN_KEYWORDS)


def fetch_airdrops_and_token_transfers(client: APIClient, transfers: pd.DataFrame) -> pd.DataFrame:
    """Collect token airdrops/transfers from explorer logs and transfer table."""
    rows: list[dict[str, Any]] = []

    # From transfer table first.
    if not transfers.empty:
        for _, row in transfers.iterrows():
            asset = str(row.get("asset") or "")
            if _looks_like_token(asset):
                rows.append(
                    {
                        "timestamp": row.get("timestamp"),
                        "asset": asset,
                        "quantity": to_float(row.get("amount_quote"), default=0.0),
                        "event_type": "airdrop" if str(row.get("event_type")) == "deposit" else "token_transfer",
                        "source": str(row.get("source") or "transfers"),
                        "raw": row.get("raw"),
                    }
                )

    # From explorer logs as airdrop hints.
    params = [str(client.settings.account_index)]
    if client.settings.l1_address:
        params.append(client.settings.l1_address)

    for param in params:
        endpoint_name = f"explorer.airdrop[{param}]"
        try:
            logs = client.paginate_explorer_logs(param)
            added = 0
            for log in logs:
                tx_type = str(log.get("tx_type") or "")
                pub = log.get("pubdata") if isinstance(log.get("pubdata"), dict) else {}
                asset = ""
                qty = 0.0
                for key in ("l1_deposit_pubdata_v2", "l2_transfer_pubdata_v2"):
                    block = pub.get(key)
                    if isinstance(block, dict):
                        asset = str(block.get("asset_index") or "")
                        qty = to_float(block.get("accepted_amount") or block.get("amount"), default=0.0)
                        break

                if ("airdrop" in tx_type.lower() or _looks_like_token(asset)) and qty:
                    rows.append(
                        {
                            "timestamp": parse_timestamp(log.get("time") or log.get("timestamp")),
                            "asset": asset or "TOKEN",
                            "quantity": qty,
                            "event_type": "airdrop" if "airdrop" in tx_type.lower() else "token_transfer",
                            "source": endpoint_name,
                            "raw": log,
                        }
                    )
                    added += 1
            client.endpoint_statuses.append(EndpointStatus(endpoint_name, True, added, ""))
        except Exception as exc:
            client.endpoint_statuses.append(EndpointStatus(endpoint_name, False, 0, str(exc)))

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "asset", "quantity", "event_type", "source", "raw"])

    df = df.drop_duplicates(subset=["timestamp", "asset", "quantity", "event_type", "source"], keep="last")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def summarize_token_sales(trades: pd.DataFrame) -> dict[str, float]:
    """Token sell summary for LIT/LIGHTER market rows."""
    if trades.empty:
        return {"qty_sold": 0.0, "vwap_sell_price": 0.0, "proceeds_quote": 0.0, "token_sale_pnl_quote": 0.0}

    market = trades["market"].astype(str).str.upper()
    mask = market.str.contains("LIT", na=False) & (trades["side"] == "sell")
    sales = trades[mask].copy()
    if sales.empty:
        return {"qty_sold": 0.0, "vwap_sell_price": 0.0, "proceeds_quote": 0.0, "token_sale_pnl_quote": 0.0}

    qty = float(sales["size"].sum())
    proceeds = float(sales["notional_quote"].sum())
    fees = float(sales["fee_quote"].sum())
    vwap = proceeds / qty if qty else 0.0

    # Airdrop assumed zero-cost basis unless external basis exists.
    pnl = proceeds - fees
    return {
        "qty_sold": qty,
        "vwap_sell_price": vwap,
        "proceeds_quote": proceeds,
        "token_sale_pnl_quote": pnl,
    }
