"""Token airdrop/transfer and token sell helpers."""
from __future__ import annotations

import pandas as pd


def infer_airdrops(transfers: pd.DataFrame) -> pd.DataFrame:
    if transfers.empty:
        return pd.DataFrame(columns=["timestamp", "asset", "quantity", "source", "raw"])

    t = transfers.copy()
    asset_u = t["asset"].astype(str).str.upper()
    # Airdrop best-effort: incoming LIT-like assets or source mentioning airdrop
    mask = (
        (t["event_type"].isin(["deposit", "transfer"]))
        & (asset_u.str.contains("LIT", na=False) | t["source"].astype(str).str.contains("airdrop", case=False, na=False))
    )

    out = t[mask].copy()
    if out.empty:
        return pd.DataFrame(columns=["timestamp", "asset", "quantity", "source", "raw"])

    out.rename(columns={"amount_quote": "quantity"}, inplace=True)
    return out[["timestamp", "asset", "quantity", "source", "raw"]].reset_index(drop=True)


def infer_token_transfers(transfers: pd.DataFrame) -> pd.DataFrame:
    if transfers.empty:
        return pd.DataFrame(columns=["timestamp", "event_type", "asset", "amount_quote", "source", "raw"])

    t = transfers.copy()
    out = t[t["asset"].astype(str).str.upper().ne("USDC")].copy()
    return out[["timestamp", "event_type", "asset", "amount_quote", "source", "raw"]].reset_index(drop=True)


def token_sell_summary(trades: pd.DataFrame, token_keyword: str = "LIT") -> dict[str, float]:
    if trades.empty:
        return {"qty_sold": 0.0, "vwap": 0.0, "proceeds_quote": 0.0}

    m = trades["market"].astype(str).str.upper().str.contains(token_keyword.upper(), na=False)
    s = trades["side"].eq("sell")
    x = trades[m & s]
    if x.empty:
        return {"qty_sold": 0.0, "vwap": 0.0, "proceeds_quote": 0.0}

    qty = float(x["size"].sum())
    proceeds = float(x["notional_quote"].sum())
    return {
        "qty_sold": qty,
        "vwap": proceeds / qty if qty else 0.0,
        "proceeds_quote": proceeds,
    }
