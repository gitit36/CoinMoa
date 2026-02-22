"""Trades extractor: fills, liquidations, fees, and funding."""
from __future__ import annotations

from typing import Any

import pandas as pd

from api_client import APIClient, EndpointStatus, parse_timestamp, to_float


def _fetch_market_symbol_map(client: APIClient) -> dict[int, str]:
    """Get market_id -> symbol mapping from public orderBooks endpoint."""
    mapping: dict[int, str] = {}
    try:
        payload = client._request_json(  # pylint: disable=protected-access
            "GET",
            f"{client.settings.base_url}/api/v1/orderBooks",
            params={},
            auth_required=False,
        )
        books = payload.get("order_books") if isinstance(payload, dict) else None
        if isinstance(books, list):
            for b in books:
                if not isinstance(b, dict):
                    continue
                market_id = b.get("market_id")
                symbol = b.get("symbol")
                if market_id is not None and symbol:
                    try:
                        mapping[int(market_id)] = str(symbol)
                    except (TypeError, ValueError):
                        continue
    except Exception:
        return {}
    return mapping


def _resolve_side(raw: dict[str, Any], account_index: int) -> str:
    side = str(raw.get("side") or raw.get("direction") or raw.get("trade_side") or "").lower()
    if side in {"b", "bid"}:
        return "buy"
    if side in {"s", "ask"}:
        return "sell"
    if side in {"buy", "sell"}:
        return side

    is_taker_ask = raw.get("is_taker_ask")
    taker_idx = str(raw.get("taker_account_index") or "")
    maker_idx = str(raw.get("maker_account_index") or "")
    me = str(account_index)

    if str(is_taker_ask).lower() in {"1", "true"}:
        taker_side = "sell"
    elif str(is_taker_ask).lower() in {"0", "false"}:
        taker_side = "buy"
    else:
        return "unknown"

    if taker_idx and taker_idx == me:
        return taker_side
    if maker_idx and maker_idx == me:
        return "buy" if taker_side == "sell" else "sell"
    return taker_side


def _normalize_trade(
    raw: dict[str, Any],
    source: str,
    account_index: int,
    market_map: dict[int, str],
) -> dict[str, Any]:
    ts = parse_timestamp(
        raw.get("time")
        or raw.get("timestamp")
        or raw.get("created_at")
        or raw.get("executed_at")
        or raw.get("updated_at")
    )

    market = raw.get("symbol") or raw.get("market") or raw.get("pair")
    market_index = raw.get("market_index") or raw.get("market_id")
    if market_index is not None:
        try:
            mapped = market_map.get(int(market_index))
            if mapped:
                market = mapped
        except (TypeError, ValueError):
            pass
    if not market and market_index is not None:
        market = f"market_{market_index}"

    size = to_float(raw.get("size") or raw.get("quantity") or raw.get("filled_size"), default=0.0)
    price = to_float(raw.get("price"), default=0.0)

    notional = to_float(raw.get("notional") or raw.get("quote_qty"), default=0.0)
    if notional == 0.0 and size and price:
        notional = abs(size * price)

    side = _resolve_side(raw, account_index)

    maker_fee_bps = to_float(raw.get("maker_fee"), default=0.0)
    taker_fee_bps = to_float(raw.get("taker_fee"), default=0.0)
    explicit_fee = to_float(raw.get("fee") or raw.get("fee_usd"), default=0.0)

    fee_quote = explicit_fee
    if fee_quote == 0.0 and notional != 0.0:
        bps = taker_fee_bps if side in {"buy", "sell"} else maker_fee_bps
        if bps:
            fee_quote = notional * bps / 10000.0

    funding_quote = to_float(raw.get("funding") or raw.get("funding_fee") or raw.get("funding_payment"), default=0.0)
    realized_pnl = to_float(raw.get("realized_pnl") or raw.get("realizedPnl") or raw.get("pnl"), default=0.0)

    tx_type = str(raw.get("tx_type") or raw.get("trade_type") or "")
    liquidation = "liq" in tx_type.lower() or tx_type.lower() == "liquidation"

    return {
        "timestamp": ts,
        "side": side,
        "market": str(market or ""),
        "price": price,
        "size": abs(size),
        "notional_quote": abs(notional),
        "fee_quote": fee_quote,
        "funding_quote": funding_quote,
        "realized_pnl": realized_pnl,
        "liquidation": liquidation,
        "tx_hash": raw.get("hash") or raw.get("tx_hash") or raw.get("trade_id") or raw.get("id"),
        "source": source,
        "raw": raw,
    }


def fetch_trades(client: APIClient) -> pd.DataFrame:
    """Fetch complete trades/fills from inception."""
    rows: list[dict[str, Any]] = []
    account_index = client.settings.account_index
    market_map = _fetch_market_symbol_map(client)

    # Preferred endpoint from current API spec: /api/v1/trades
    try:
        collected: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(client.settings.max_pages):
            params: dict[str, Any] = {
                "account_index": account_index,
                "sort_by": "timestamp",
                "sort_dir": "desc",
                "limit": min(client.settings.page_limit, 100),
            }
            token = client.auth_token()
            if token:
                params["auth"] = token
            if cursor:
                params["cursor"] = cursor

            payload = client._request_json(  # pylint: disable=protected-access
                "GET",
                f"{client.settings.base_url}/api/v1/trades",
                params=params,
                auth_required=bool(token),
            )
            if isinstance(payload, dict):
                batch = payload.get("trades", [])
                cursor = payload.get("next_cursor")
            elif isinstance(payload, list):
                batch = payload
                cursor = None
            else:
                batch = []
                cursor = None

            if not isinstance(batch, list) or not batch:
                break
            collected.extend([x for x in batch if isinstance(x, dict)])
            if not cursor:
                break

        if collected:
            rows.extend(_normalize_trade(x, "trades", account_index, market_map) for x in collected)
            client.endpoint_statuses.append(EndpointStatus("trades", True, len(collected), ""))
        else:
            client.endpoint_statuses.append(EndpointStatus("trades", False, 0, "empty trades response"))
    except Exception as exc:
        client.endpoint_statuses.append(EndpointStatus("trades", False, 0, str(exc)))

    # Backward-compat fallback
    try:
        trades = client.paginate_v1(
            "accountTrades",
            auth_required=True,
            base_params={"account_index": account_index},
            data_keys=("trades", "items", "data"),
        )
        rows.extend(_normalize_trade(x, "accountTrades", account_index, market_map) for x in trades)
        client.endpoint_statuses.append(EndpointStatus("accountTrades", True, len(trades), ""))
    except Exception as exc:
        client.endpoint_statuses.append(EndpointStatus("accountTrades", False, 0, str(exc)))

    # Explorer backfill (trade_pubdata/trade_pubdata_with_funding).
    explorer_params = [str(account_index)]
    if client.settings.l1_address:
        explorer_params.append(client.settings.l1_address)

    for param in explorer_params:
        endpoint_name = f"explorer.trade_logs[{param}]"
        try:
            logs = client.paginate_explorer_logs(param)
            added = 0
            for log in logs:
                pub = log.get("pubdata") if isinstance(log.get("pubdata"), dict) else {}
                trade_block = pub.get("trade_pubdata_with_funding") or pub.get("trade_pubdata")
                if isinstance(trade_block, dict):
                    merged = {**log, **trade_block}
                    rows.append(_normalize_trade(merged, endpoint_name, account_index, market_map))
                    added += 1
            client.endpoint_statuses.append(EndpointStatus(endpoint_name, True, added, ""))
        except Exception as exc:
            client.endpoint_statuses.append(EndpointStatus(endpoint_name, False, 0, str(exc)))

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "side",
                "market",
                "price",
                "size",
                "notional_quote",
                "fee_quote",
                "funding_quote",
                "realized_pnl",
                "liquidation",
                "tx_hash",
                "source",
                "raw",
            ]
        )

    df = df.drop_duplicates(subset=["timestamp", "side", "market", "size", "price", "tx_hash"], keep="last")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
