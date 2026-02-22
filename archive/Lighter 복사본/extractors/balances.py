"""Balance extractor: current snapshot + optional history attempts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from api_client import APIClient, EndpointStatus, parse_timestamp, to_float


def _snapshot_row(raw: dict[str, Any], source: str) -> dict[str, Any]:
    positions = raw.get("positions") if isinstance(raw.get("positions"), list) else []
    realized = 0.0
    unrealized = 0.0
    for pos in positions:
        if isinstance(pos, dict):
            realized += to_float(pos.get("realized_pnl") or pos.get("realizedPnl"), default=0.0)
            unrealized += to_float(pos.get("unrealized_pnl") or pos.get("unrealizedPnl"), default=0.0)

    ts = parse_timestamp(raw.get("updated_at") or raw.get("timestamp"))
    if ts is None:
        ts = datetime.now(timezone.utc)

    return {
        "timestamp": ts,
        "collateral_quote": to_float(raw.get("collateral"), default=0.0),
        "available_balance_quote": to_float(raw.get("available_balance"), default=0.0),
        "total_asset_value_quote": to_float(raw.get("total_asset_value"), default=0.0),
        "realized_pnl_quote": realized,
        "unrealized_pnl_quote": unrealized,
        "source": source,
        "raw": raw,
    }


def fetch_balance_history(client: APIClient) -> pd.DataFrame:
    """Fetch balance history if endpoint exists, otherwise current snapshot."""
    rows: list[dict[str, Any]] = []

    # Always include current snapshot.
    try:
        account = client.get_account_snapshot()
        rows.append(_snapshot_row(account, "account"))
        client.endpoint_statuses.append(EndpointStatus("account", True, 1, ""))
    except Exception as exc:
        client.endpoint_statuses.append(EndpointStatus("account", False, 0, str(exc)))

    # Try possible historical balance endpoints (best-effort; may not exist).
    candidate_endpoints = (
        "account/balanceHistory",
        "account/history",
        "balance/history",
    )

    params = {"account_index": client.settings.account_index}
    for endpoint in candidate_endpoints:
        try:
            batch = client.paginate_v1(endpoint, auth_required=True, base_params=params)
            converted = 0
            for raw in batch:
                if isinstance(raw, dict):
                    rows.append(_snapshot_row(raw, endpoint))
                    converted += 1
            client.endpoint_statuses.append(EndpointStatus(endpoint, True, converted, ""))
        except Exception as exc:
            client.endpoint_statuses.append(EndpointStatus(endpoint, False, 0, str(exc)))

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "collateral_quote",
                "available_balance_quote",
                "total_asset_value_quote",
                "realized_pnl_quote",
                "unrealized_pnl_quote",
                "source",
                "raw",
            ]
        )

    df = df.drop_duplicates(subset=["timestamp", "total_asset_value_quote", "collateral_quote", "source"], keep="last")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
