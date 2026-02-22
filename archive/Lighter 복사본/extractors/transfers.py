"""Transfer extractor: deposits, withdrawals, and token transfers."""
from __future__ import annotations

from typing import Any

import pandas as pd

from api_client import APIClient, EndpointStatus, parse_timestamp, to_float


def _pick_amount(raw: dict[str, Any]) -> float:
    for key in ("amount", "accepted_amount", "usdc_amount", "value"):
        if raw.get(key) is not None:
            v = to_float(raw.get(key), default=0.0)
            if v != 0.0:
                return v

    pub = raw.get("pubdata") if isinstance(raw.get("pubdata"), dict) else {}
    if pub:
        for block_key in ("l1_deposit_pubdata_v2", "l1_withdraw_pubdata_v2", "l2_transfer_pubdata_v2"):
            block = pub.get(block_key)
            if isinstance(block, dict):
                for key in ("accepted_amount", "amount"):
                    v = to_float(block.get(key), default=0.0)
                    if v != 0.0:
                        return v
    return 0.0


def _pick_asset(raw: dict[str, Any]) -> str:
    for key in ("asset", "asset_index", "token"):
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value)

    pub = raw.get("pubdata") if isinstance(raw.get("pubdata"), dict) else {}
    for block_key in ("l1_deposit_pubdata_v2", "l1_withdraw_pubdata_v2", "l2_transfer_pubdata_v2"):
        block = pub.get(block_key)
        if isinstance(block, dict) and block.get("asset_index") is not None:
            return str(block.get("asset_index"))

    return "USDC"


def _normalize(raw: dict[str, Any], source: str, fallback_type: str) -> dict[str, Any]:
    tx_type = str(raw.get("tx_type") or raw.get("type") or fallback_type).lower()
    if "deposit" in tx_type:
        event_type = "deposit"
    elif "withdraw" in tx_type:
        event_type = "withdraw"
    elif "transfer" in tx_type:
        event_type = "transfer"
    else:
        event_type = fallback_type

    ts = parse_timestamp(
        raw.get("time")
        or raw.get("timestamp")
        or raw.get("created_at")
        or raw.get("updated_at")
        or raw.get("executed_at")
    )

    return {
        "timestamp": ts,
        "event_type": event_type,
        "asset": _pick_asset(raw),
        "amount_quote": _pick_amount(raw),
        "fee_quote": to_float(raw.get("fee") or raw.get("usdc_fee"), default=0.0),
        "tx_hash": raw.get("hash") or raw.get("tx_hash") or raw.get("id"),
        "source": source,
        "raw": raw,
    }


def fetch_transfers(client: APIClient) -> pd.DataFrame:
    """Fetch complete transfer history from inception."""
    rows: list[dict[str, Any]] = []

    base_params = {"account_index": client.settings.account_index}
    if client.settings.l1_address:
        base_params["l1_address"] = client.settings.l1_address

    endpoints = (
        ("deposit/history", "deposit", True),
        ("withdraw/history", "withdraw", True),
        ("l1Metadata", "transfer", True),
    )

    for endpoint, fallback_type, auth_required in endpoints:
        try:
            batch = client.paginate_v1(endpoint, auth_required=auth_required, base_params=base_params)
            rows.extend(_normalize(x, endpoint, fallback_type) for x in batch)
            client.endpoint_statuses.append(EndpointStatus(endpoint, True, len(batch), ""))
        except Exception as exc:
            client.endpoint_statuses.append(EndpointStatus(endpoint, False, 0, str(exc)))

    explorer_params = [str(client.settings.account_index)]
    if client.settings.l1_address:
        explorer_params.append(client.settings.l1_address)

    for param in explorer_params:
        endpoint_name = f"explorer.logs[{param}]"
        try:
            logs = client.paginate_explorer_logs(param)
            for log in logs:
                tx_type = str(log.get("tx_type") or "").lower()
                if tx_type in {"l1deposit", "l1withdraw", "deposit", "withdraw", "l2transfer", "transfer"}:
                    rows.append(_normalize(log, endpoint_name, "transfer"))
            client.endpoint_statuses.append(EndpointStatus(endpoint_name, True, len(logs), ""))
        except Exception as exc:
            client.endpoint_statuses.append(EndpointStatus(endpoint_name, False, 0, str(exc)))

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=["timestamp", "event_type", "asset", "amount_quote", "fee_quote", "tx_hash", "source", "raw"]
        )

    df = df.drop_duplicates(subset=["timestamp", "event_type", "asset", "amount_quote", "tx_hash"], keep="last")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
