"""
Lighter API client: 잔고, 입출금 내역, 거래 내역, 손익.
Based on https://apidocs.lighter.xyz/docs/get-started-for-programmers-1
"""
import asyncio
import csv
from datetime import datetime
from io import StringIO
from typing import Any, Optional, Union

import lighter
from config import (
    ACCOUNT_INDEX,
    API_KEY_INDEX,
    API_KEY_PRIVATE_KEY,
    BASE_URL,
    ETHERSCAN_API_KEY,
    KOREAEXIM_API_KEY,
    L1_ADDRESS,
    READ_ONLY_AUTH_TOKEN,
    get_auth_required,
)

# Collateral is typically in 6 decimals (USDC)
COLLATERAL_DECIMALS = 6

# Lighter L1 contract (Ethereum mainnet). Deposit/Withdraw function selectors from docs.
LIGHTER_CONTRACT = "0x3B4D794a66304F130a4Db8F2551B0070dfCf5ca7".lower()
DEPOSIT_SELECTOR = "0x8a857083"
WITHDRAW_SELECTOR = "0xd20191bd"
ETHERSCAN_API = "https://api.etherscan.io/api"


def _div(value: Optional[Union[int, str]], decimals: int = 6) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        return float(value)
    return value / (10**decimals)


async def get_balance(use_l1_address: bool = False) -> dict[str, Any]:
    """
    계정 잔고 (담보 금액).
    AccountApi.account -> collateral.
    """
    client = lighter.ApiClient(lighter.Configuration(host=BASE_URL))
    try:
        api = lighter.AccountApi(client)
        if (use_l1_address or not ACCOUNT_INDEX) and L1_ADDRESS:
            acc = await api.account(by="l1_address", value=L1_ADDRESS)
        else:
            acc = await api.account(by="index", value=str(ACCOUNT_INDEX))
        # API returns { "accounts": [ { "collateral": "28.94...", "index": ..., ... } ] }
        accounts_list = getattr(acc, "accounts", None) or []
        inner = accounts_list[0] if accounts_list else getattr(acc, "account", acc)
        if not inner and accounts_list:
            inner = accounts_list[0]
        collateral_raw = getattr(inner, "collateral", None)
        idx = getattr(inner, "index", None) or getattr(acc, "index", ACCOUNT_INDEX)
        if collateral_raw is None:
            collateral = 0.0
        elif isinstance(collateral_raw, str):
            collateral = float(collateral_raw)
        else:
            collateral = _div(collateral_raw)
        available = getattr(inner, "available_balance", None)
        total_asset = getattr(inner, "total_asset_value", None)
        if isinstance(available, str):
            available = float(available)
        elif available is not None and not isinstance(available, (int, float)):
            available = float(available) if available else 0.0
        if isinstance(total_asset, str):
            total_asset = float(total_asset)
        elif total_asset is not None and not isinstance(total_asset, (int, float)):
            total_asset = float(total_asset) if total_asset else 0.0
        return {
            "account_index": idx,
            "collateral_usd": round(collateral, 2),
            "available_balance_usd": round(available, 2) if available is not None else round(collateral, 2),
            "total_asset_value_usd": round(total_asset, 2) if total_asset is not None else round(collateral, 2),
            "raw_collateral": collateral_raw,
        }
    finally:
        await client.close()


async def get_pnl(use_l1_address: bool = False) -> dict[str, Any]:
    """
    손익: 미실현/실현 PnL from account positions.
    AccountApi.account position details: unrealized_pnl, realized_pnl.
    """
    client = lighter.ApiClient(lighter.Configuration(host=BASE_URL))
    try:
        api = lighter.AccountApi(client)
        if (use_l1_address or not ACCOUNT_INDEX) and L1_ADDRESS:
            acc = await api.account(by="l1_address", value=L1_ADDRESS)
        else:
            acc = await api.account(by="index", value=str(ACCOUNT_INDEX))
        total_unrealized = 0.0
        total_realized = 0.0
        positions = []
        accounts_list = getattr(acc, "accounts", None) or []
        inner = accounts_list[0] if accounts_list else getattr(acc, "account", acc)
        pos_details = getattr(inner, "positions", None) or getattr(acc, "position_details", None) or getattr(acc, "positions", None) or []
        for p in pos_details or []:
            u = _div(getattr(p, "unrealized_pnl", None) or getattr(p, "unrealizedPnl", None))
            r = _div(getattr(p, "realized_pnl", None) or getattr(p, "realizedPnl", None))
            total_unrealized += u
            total_realized += r
            market_id = getattr(p, "market_id", None)
            symbol = getattr(p, "symbol", None)
            market = market_id if market_id is not None else symbol
            pos_val = _div(getattr(p, "position_value", None) or getattr(p, "positionValue", None))
            position_size = getattr(p, "position", None)
            sign = getattr(p, "sign", None)
            avg_entry = getattr(p, "avg_entry_price", None)
            positions.append({
                "market_id": market_id,
                "symbol": symbol,
                "market": market,
                "position": position_size,
                "sign": sign,
                "avg_entry_price": avg_entry,
                "unrealized_pnl": round(u, 2),
                "realized_pnl": round(r, 2),
                "position_value_usd": round(pos_val, 2),
            })
        return {
            "account_index": getattr(acc, "index", ACCOUNT_INDEX),
            "total_unrealized_pnl_usd": round(total_unrealized, 2),
            "total_realized_pnl_usd": round(total_realized, 2),
            "total_pnl_usd": round(total_unrealized + total_realized, 2),
            "positions": positions,
        }
    finally:
        await client.close()


EXPLORER_BASE = "https://explorer.elliot.ai"

async def _get_auth_for_request() -> tuple[Optional[str], Optional[str]]:
    """
    Return (auth_string, error_message) for auth-gated requests.
    Prefer READ_ONLY_AUTH_TOKEN; otherwise create token via SignerClient.
    """
    if READ_ONLY_AUTH_TOKEN:
        return (READ_ONLY_AUTH_TOKEN, None)
    return await _create_auth_token()


def _auth_headers(auth_token: str, use_bearer: bool = True) -> dict[str, str]:
    """
    Build Authorization header for Lighter API.
    - Query param 'auth' is always the raw token.
    - Header: for read-only (ro:...) try Bearer by default; use_bearer=False uses raw token (retry on 401).
    """
    if auth_token.startswith("ro:") and use_bearer:
        return {"Authorization": f"Bearer {auth_token}"}
    return {"Authorization": auth_token}


EXPLORER_LOG_PAGE_SIZE = 100  # API가 한 번에 주는 최대 개수

async def get_account_logs_raw(param: str, limit: int = 5000, use_pagination: bool = True) -> dict[str, Any]:
    """
    Explorer 계정 로그 조회 (필터 없음). 인증 불필요.
    GET https://explorer.elliot.ai/api/accounts/{param}/logs
    use_pagination=True면 offset으로 100건씩 이전 로그까지 계속 가져옴 (100건 초과 시).
    참고: Explorer는 과거 로그 보관 기간이 제한될 수 있음 (예: 2025년 8월 이전 미제공).
    """
    import aiohttp
    all_logs: list = []
    offset = 0
    max_total = min(limit, 10000)  # 상한
    async with aiohttp.ClientSession() as session:
        while offset < max_total:
            url = f"{EXPLORER_BASE}/api/accounts/{param}/logs"
            if use_pagination and offset > 0:
                url += f"?offset={offset}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    if offset == 0:
                        return {"logs": [], "error": f"Explorer HTTP {resp.status}", "source": "explorer"}
                    break
                data = await resp.json()
            if not isinstance(data, list):
                break
            if not data:
                break
            all_logs.extend(data)
            if len(data) < EXPLORER_LOG_PAGE_SIZE:
                break
            offset += len(data)
            if offset >= max_total:
                break
    all_logs.sort(key=lambda x: x.get("time") or "", reverse=True)
    return {"logs": all_logs[:limit], "count": len(all_logs), "source": "explorer (no auth)"}


async def get_log_by_hash(tx_hash: str) -> dict[str, Any]:
    """
    Explorer에서 tx hash로 단일 로그 상세 조회. 인증 불필요.
    GET https://explorer.elliot.ai/api/logs/{hash}
    """
    import aiohttp
    h = tx_hash.strip()
    if not h or not h.startswith("0x"):
        return {"error": "0x로 시작하는 tx hash 필요"}
    url = f"{EXPLORER_BASE}/api/logs/{h}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return {"error": f"HTTP {resp.status}", "log": None}
            data = await resp.json()
    return {"log": data, "source": "explorer"}


def _parse_log_pubdata_flat(log: dict) -> dict:
    """
    로그 한 건의 pubdata를 파싱해 보기 쉬운 flat 필드로 반환.
    반환 dict 키: amount, asset, from_account_index, to_account_index, from_route_type, to_route_type,
    usdc_fee, account_index, l1_address, route_type, accepted_amount,
    trade_type, market_index, is_taker_ask, price, size, maker_fee, taker_fee,
    taker_account_index, maker_account_index, funding_rate_prefix_sum
    """
    pub = log.get("pubdata") or {}
    row = {}
    if "l2_transfer_pubdata_v2" in pub:
        d = pub["l2_transfer_pubdata_v2"]
        row["amount"] = d.get("amount", "")
        row["asset"] = d.get("asset_index", "")
        row["from_account_index"] = d.get("from_account_index", "")
        row["to_account_index"] = d.get("to_account_index", "")
        row["from_route_type"] = d.get("from_route_type", "")
        row["to_route_type"] = d.get("to_route_type", "")
        row["usdc_fee"] = d.get("usdc_fee", "")
    if "l1_deposit_pubdata_v2" in pub:
        d = pub["l1_deposit_pubdata_v2"]
        row["account_index"] = d.get("account_index", "")
        row["l1_address"] = d.get("l1_address", "")
        row["asset"] = d.get("asset_index", "")
        row["route_type"] = d.get("route_type", "")
        row["accepted_amount"] = d.get("accepted_amount", "") or d.get("amount", "")
    if "l1_withdraw_pubdata_v2" in pub:
        d = pub["l1_withdraw_pubdata_v2"]
        row["account_index"] = d.get("account_index", "")
        row["l1_address"] = d.get("l1_address", "")
        row["asset"] = d.get("asset_index", "")
        row["route_type"] = d.get("route_type", "")
        row["accepted_amount"] = d.get("amount", "")
    trade_data = pub.get("trade_pubdata_with_funding") or pub.get("trade_pubdata")
    if trade_data:
        row["trade_type"] = trade_data.get("trade_type", "")
        row["market_index"] = trade_data.get("market_index", "")
        row["is_taker_ask"] = trade_data.get("is_taker_ask", "")
        row["price"] = trade_data.get("price", "")
        row["size"] = trade_data.get("size", "")
        row["maker_fee"] = trade_data.get("maker_fee", "")
        row["taker_fee"] = trade_data.get("taker_fee", "")
        row["taker_account_index"] = trade_data.get("taker_account_index", "")
        row["maker_account_index"] = trade_data.get("maker_account_index", "")
        row["funding_rate_prefix_sum"] = trade_data.get("funding_rate_prefix_sum", "")
    return row


async def export_logs_to_csv(param: str, output_path: Optional[str] = None) -> str:
    """
    계정 로그 전체를 페이지네이션으로 가져와 CSV 문자열로 반환.
    param: L1 주소 또는 account_index.
    output_path: 지정 시 해당 경로에 파일 저장 후 CSV 문자열 반환.
    """
    import json
    raw = await get_account_logs_raw(param, limit=10000, use_pagination=True)
    if raw.get("error"):
        raise ValueError(raw["error"])
    logs = raw.get("logs", [])
    out = StringIO()
    w = csv.writer(out)
    w.writerow(["일시", "tx_type", "pubdata"])
    for log in logs:
        time_str = (log.get("time") or "").replace("Z", "").replace("T", "-")[:19]
        tx_type = log.get("tx_type") or ""
        pub = log.get("pubdata")
        pub_str = json.dumps(pub, ensure_ascii=False) if pub else ""
        w.writerow([time_str, tx_type, pub_str])
    csv_str = out.getvalue()
    if output_path:
        from pathlib import Path
        Path(output_path).write_text(csv_str, encoding="utf-8")
    return csv_str


# 로그 CSV용 flat 컬럼 헤더 (pubdata 파싱해서 펼친 버전)
_LOGS_FLAT_HEADER = [
    "일시", "tx_type",
    "amount", "asset", "from_account_index", "to_account_index", "from_route_type", "to_route_type", "usdc_fee",
    "account_index", "l1_address", "route_type", "accepted_amount",
    "trade_type", "market_index", "is_taker_ask", "price", "size", "maker_fee", "taker_fee",
    "taker_account_index", "maker_account_index", "funding_rate_prefix_sum",
]


async def export_logs_to_csv_flat(param: str, output_path: Optional[str] = None) -> str:
    """
    계정 로그 전체를 가져와 pubdata를 파싱해 컬럼을 펼친 '보기 쉬운' CSV로 반환.
    tx_type별로 해당하는 컬럼만 채워지고 나머지는 빈칸.
    """
    raw = await get_account_logs_raw(param, limit=10000, use_pagination=True)
    if raw.get("error"):
        raise ValueError(raw["error"])
    logs = raw.get("logs", [])
    out = StringIO()
    w = csv.writer(out)
    w.writerow(_LOGS_FLAT_HEADER)
    for log in logs:
        time_str = (log.get("time") or "").replace("Z", "").replace("T", "-")[:19]
        tx_type = log.get("tx_type") or ""
        flat = _parse_log_pubdata_flat(log)
        row = [
            time_str, tx_type,
            flat.get("amount", ""), flat.get("asset", ""), flat.get("from_account_index", ""),
            flat.get("to_account_index", ""), flat.get("from_route_type", ""), flat.get("to_route_type", ""),
            flat.get("usdc_fee", ""),
            flat.get("account_index", ""), flat.get("l1_address", ""), flat.get("route_type", ""),
            flat.get("accepted_amount", ""),
            flat.get("trade_type", ""), flat.get("market_index", ""), flat.get("is_taker_ask", ""),
            flat.get("price", ""), flat.get("size", ""), flat.get("maker_fee", ""), flat.get("taker_fee", ""),
            flat.get("taker_account_index", ""), flat.get("maker_account_index", ""),
            flat.get("funding_rate_prefix_sum", ""),
        ]
        w.writerow(row)
    csv_str = out.getvalue()
    if output_path:
        from pathlib import Path
        Path(output_path).write_text(csv_str, encoding="utf-8")
    return csv_str


def get_logs_date_range(logs: list) -> tuple[Optional[str], Optional[str]]:
    """로그 목록에서 가장 이른/늦은 일시 반환. (oldest, newest)"""
    if not logs:
        return (None, None)
    times = [log.get("time") or "" for log in logs]
    times = [t.replace("Z", "").replace("T", "-")[:10] for t in times if t]
    if not times:
        return (None, None)
    return (min(times), max(times))


async def get_deposits_withdrawals_explorer(param: str, limit: int = 50) -> dict[str, Any]:
    """
    입출금 내역을 Lighter Explorer API에서 조회. 인증 불필요.
    offset 페이지네이션으로 100건 넘는 로그도 수집 후 필터.
    """
    raw = await get_account_logs_raw(param, limit=5000, use_pagination=True)
    if raw.get("error"):
        return {"items": [], "error": raw["error"], "source": "explorer"}
    data = raw.get("logs", [])
    items = []
    for log in data:
        tx_type = log.get("tx_type", "")
        if tx_type in ("L1Deposit", "L1Withdraw", "Deposit", "Withdraw"):
            item = {
                "type": "deposit" if "Deposit" in tx_type else "withdraw",
                "tx_type": tx_type,
                "hash": log.get("hash"),
                "time": log.get("time"),
                "pubdata": log.get("pubdata"),
            }
            if log.get("pubdata"):
                pd = log["pubdata"]
                if "l1_deposit_pubdata_v2" in pd:
                    d = pd["l1_deposit_pubdata_v2"]
                    item["account_index"] = d.get("account_index")
                    item["l1_address"] = d.get("l1_address")
                    item["asset_index"] = d.get("asset_index")
                    # 입금 실제 반영액은 accepted_amount에 있음 (amount 없을 수 있음)
                    item["amount"] = d.get("accepted_amount") or d.get("amount")
                elif "l1_withdraw_pubdata_v2" in pd:
                    w = pd["l1_withdraw_pubdata_v2"]
                    item["account_index"] = w.get("account_index")
                    item["l1_address"] = w.get("l1_address")
                    item["asset_index"] = w.get("asset_index")
                    item["amount"] = w.get("amount")
            items.append(item)
    items.sort(key=lambda x: x.get("time") or "", reverse=True)
    return {"items": items[:limit], "count": len(items), "source": "explorer (no auth)"}


async def get_deposits_withdrawals_onchain(l1_address: str, limit: int = 50) -> dict[str, Any]:
    """
    입출금 내역을 온체인(Etherscan)에서 조회. API 키/private key 불필요.
    Lighter 컨트랙트로 보낸 deposit(0x8a857083), withdraw(0xd20191bd) 트랜잭션만 필터.
    """
    import aiohttp
    params = {
        "module": "account",
        "action": "txlist",
        "address": l1_address,
        "startblock": 0,
        "endblock": 99999999,
        "page": 1,
        "offset": min(limit * 2, 100),
        "sort": "desc",
    }
    if ETHERSCAN_API_KEY:
        params["apikey"] = ETHERSCAN_API_KEY
    async with aiohttp.ClientSession() as session:
        async with session.get(ETHERSCAN_API, params=params) as resp:
            if resp.status != 200:
                return {"items": [], "error": f"Etherscan HTTP {resp.status}", "source": "on-chain"}
            data = await resp.json()
    if data.get("status") != "1":
        msg = data.get("message", data.get("result", "No result"))
        if isinstance(msg, str) and "rate limit" in msg.lower():
            msg = "Etherscan rate limit. 잠시 후 재시도."
        return {"items": [], "count": 0, "error": msg, "source": "on-chain (Etherscan)"}
    if not isinstance(data.get("result"), list):
        return {"items": [], "count": 0, "source": "on-chain (Etherscan)"}
    items = []
    for tx in data["result"]:
        to_addr = (tx.get("to") or "").lower()
        if to_addr != LIGHTER_CONTRACT:
            continue
        raw_input = (tx.get("input") or "").lower()
        if not raw_input.startswith("0x") or len(raw_input) < 10:
            continue
        sel = raw_input[:10]
        if sel == DEPOSIT_SELECTOR.lower():
            items.append({"type": "deposit", "tx_hash": tx.get("hash"), "block": tx.get("blockNumber"), "time": tx.get("timeStamp"), "from": tx.get("from"), "value": tx.get("value"), "etherscan": f"https://etherscan.io/tx/{tx.get('hash')}"})
        elif sel == WITHDRAW_SELECTOR.lower():
            items.append({"type": "withdraw", "tx_hash": tx.get("hash"), "block": tx.get("blockNumber"), "time": tx.get("timeStamp"), "from": tx.get("from"), "value": tx.get("value"), "etherscan": f"https://etherscan.io/tx/{tx.get('hash')}"})
    items.sort(key=lambda x: int(x.get("time") or 0), reverse=True)
    return {"items": items[:limit], "count": len(items), "source": "on-chain (Etherscan)"}


async def _fetch_history_no_auth(
    session: "aiohttp.ClientSession",
    path: str,
    params: dict,
) -> tuple[Optional[list], Optional[str]]:
    """Try GET with no auth. Returns (data_list, error_message)."""
    url = f"{BASE_URL.rstrip('/')}/api/v1/{path}"
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return (None, f"HTTP {resp.status}: {await resp.text()}")
        data = await resp.json()
    items = data if isinstance(data, list) else (getattr(data, "data", None) or data.get("data", data.get("items", [])))
    return (items if isinstance(items, list) else [], None)


async def _fetch_history_with_auth(
    session: "aiohttp.ClientSession",
    path: str,
    params: dict,
    auth_token: str,
) -> tuple[Optional[list], Optional[str]]:
    """GET with read-token (or full auth). Returns (data_list, error_message). 401 with ro: retries with raw header."""
    url = f"{BASE_URL.rstrip('/')}/api/v1/{path}"
    params = {**params, "auth": auth_token}
    for use_bearer in (True, False):  # try Bearer first for read-only, then raw
        headers = _auth_headers(auth_token, use_bearer=use_bearer)
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data if isinstance(data, list) else (getattr(data, "data", None) or data.get("data", data.get("items", [])))
                return (items if isinstance(items, list) else [], None)
            if resp.status != 401 or not auth_token.startswith("ro:") or not use_bearer:
                return (None, f"HTTP {resp.status}: {(await resp.text())[:300]}")
    return (None, "HTTP 401 (auth)")


async def get_deposits_withdrawals_via_read_token(limit: int = 5000) -> dict[str, Any]:
    """
    Read-token(또는 API 키 auth)으로 입출금 내역 API만 호출.
    deposit/history, withdraw/history, l1Metadata 순으로 시도해 하나라도 성공하면 반환.
    """
    if not get_auth_required():
        return {"items": [], "error": "READ_ONLY_AUTH_TOKEN 또는 API_KEY_PRIVATE_KEY 필요", "source": "read-token"}
    auth_token, err = await _get_auth_for_request()
    if err or not auth_token:
        return {"error": f"Auth failed: {err}", "items": [], "source": "read-token"}
    if not ACCOUNT_INDEX:
        return {"items": [], "error": "ACCOUNT_INDEX 필요", "source": "read-token"}
    import aiohttp
    base = {"account_index": ACCOUNT_INDEX, "limit": limit}
    if L1_ADDRESS:
        base["l1_address"] = L1_ADDRESS
    l1_err = None
    async with aiohttp.ClientSession() as session:
        # 1) deposit/history with auth
        dep_list, dep_err = await _fetch_history_with_auth(session, "deposit/history", dict(base), auth_token)
        wd_list, wd_err = await _fetch_history_with_auth(session, "withdraw/history", dict(base), auth_token)
        if (dep_list is not None or wd_list is not None) and (dep_list or wd_list):
            combined = (
                [{"type": "deposit", "tx_type": "Deposit", **(x if isinstance(x, dict) else {"raw": x})} for x in (dep_list or [])]
                + [{"type": "withdraw", "tx_type": "Withdraw", **(x if isinstance(x, dict) else {"raw": x})} for x in (wd_list or [])]
            )
            combined.sort(key=lambda t: str(t.get("timestamp") or t.get("created_at") or t.get("executed_at") or t.get("raw") or ""), reverse=True)
            return {"items": combined[:limit], "count": len(combined), "source": "deposit/withdraw history (read-token)"}
        # 2) l1Metadata with auth (401 시 raw 토큰으로 재시도)
        url = f"{BASE_URL.rstrip('/')}/api/v1/l1Metadata"
        params_l1 = {"account_index": ACCOUNT_INDEX, "auth": auth_token, "limit": limit}
        if L1_ADDRESS:
            params_l1["l1_address"] = L1_ADDRESS
        for use_bearer in (True, False):
            headers = _auth_headers(auth_token, use_bearer=use_bearer)
            async with session.get(url, params=params_l1, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data if isinstance(data, list) else data.get("items", [])
                    if isinstance(items, list) and items:
                        return {"items": items[:limit], "count": len(items), "source": "l1Metadata (read-token)"}
                else:
                    l1_err = f"l1Metadata HTTP {resp.status}: {(await resp.text())[:200]}"
                if resp.status != 401 or not auth_token.startswith("ro:") or not use_bearer:
                    break
    err_msg = " | ".join(filter(None, ["deposit/history: " + (dep_err or "ok"), "withdraw/history: " + (wd_err or "ok"), "l1Metadata: " + (l1_err or "ok")]))
    return {"items": [], "error": err_msg or "입출금 API 모두 실패", "source": "read-token"}


async def get_account_l1_address(account_index: int) -> Optional[str]:
    """
    account_index로 L1 주소 조회. 메인 API GET /api/v1/account (인증 불필요).
    """
    import aiohttp
    url = f"{BASE_URL.rstrip('/')}/api/v1/account"
    params = {"by": "index", "value": str(account_index)}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        accounts = (data or {}).get("accounts") or []
        if accounts and isinstance(accounts[0], dict):
            return (accounts[0].get("l1_address") or "").strip() or None
        return None
    except Exception:
        return None


async def get_l2_transfer_out_breakdown(
    param: str, our_account_index: Optional[int] = None
) -> list[dict[str, Any]]:
    """
    우리 계정에서 다른 계정으로 보낸 L2 이체를 목적지(to_account_index)별로 합산.
    반환: [ {"to_account_index": str, "l1_address": str|None, "amount": float}, ... ]
    """
    if our_account_index is None:
        b = await get_balance()
        our_account_index = b.get("account_index")
        if our_account_index is None:
            return []
    our = str(our_account_index)
    raw = await get_account_logs_raw(param, limit=10000, use_pagination=True)
    if raw.get("error"):
        return []
    by_to: dict[str, float] = {}
    for log in raw.get("logs", []):
        if log.get("tx_type") != "L2Transfer":
            continue
        pd = log.get("pubdata") or {}
        d = pd.get("l2_transfer_pubdata_v2") or {}
        from_idx = str(d.get("from_account_index", ""))
        to_idx = str(d.get("to_account_index", ""))
        if from_idx != our or to_idx == our or not to_idx:
            continue
        amt = d.get("amount")
        if amt:
            try:
                by_to[to_idx] = by_to.get(to_idx, 0.0) + float(amt)
            except (TypeError, ValueError):
                pass
    result = []
    for to_idx, amount in sorted(by_to.items(), key=lambda x: -x[1]):
        l1 = await get_account_l1_address(int(to_idx))
        result.append({
            "to_account_index": to_idx,
            "l1_address": l1,
            "amount": round(amount, 2),
        })
    return result


async def get_l2_transfer_out_total(param: str, our_account_index: Optional[int] = None) -> float:
    """
    우리 계정에서 다른 계정으로 보낸 L2 이체 금액 합계 (USDC 등).
    param: L1 주소 또는 account_index. our_account_index 없으면 get_balance()로 조회.
    """
    if our_account_index is None:
        b = await get_balance()
        our_account_index = b.get("account_index")
        if our_account_index is None:
            return 0.0
    our = str(our_account_index)
    raw = await get_account_logs_raw(param, limit=10000, use_pagination=True)
    if raw.get("error"):
        return 0.0
    total = 0.0
    for log in raw.get("logs", []):
        if log.get("tx_type") != "L2Transfer":
            continue
        pd = log.get("pubdata") or {}
        d = pd.get("l2_transfer_pubdata_v2") or {}
        from_idx = str(d.get("from_account_index", ""))
        to_idx = str(d.get("to_account_index", ""))
        if from_idx != our or to_idx == our:
            continue
        amt = d.get("amount")
        if amt:
            try:
                total += float(amt)
            except (TypeError, ValueError):
                pass
    return round(total, 6)


async def get_deposits_withdrawals(limit: int = 50) -> dict[str, Any]:
    """
    입출금 내역. private key 없이 시도:
    1) Explorer API (인증 불필요) - account_index 또는 l1_address로
    2) L1_ADDRESS 있으면 온체인(Etherscan) 조회
    3) GET deposit/history, withdraw/history (인증 없이)
    4) 실패 시 l1Metadata (auth 필요)
    """
    if ACCOUNT_INDEX:
        explorer = await get_deposits_withdrawals_explorer(str(ACCOUNT_INDEX), limit)
        if explorer.get("items"):
            return explorer
    if L1_ADDRESS:
        explorer = await get_deposits_withdrawals_explorer(L1_ADDRESS, limit)
        if explorer.get("items"):
            return explorer
        onchain = await get_deposits_withdrawals_onchain(L1_ADDRESS, limit)
        if "error" not in onchain or onchain.get("items") is not None:
            return onchain
    import aiohttp
    base_params = {"account_index": ACCOUNT_INDEX}
    if limit:
        base_params["limit"] = limit
    if L1_ADDRESS:
        base_params["l1_address"] = L1_ADDRESS

    async with aiohttp.ClientSession() as session:
        deposits, dep_err = await _fetch_history_no_auth(session, "deposit/history", dict(base_params))
        withdraws, wd_err = await _fetch_history_no_auth(session, "withdraw/history", dict(base_params))

    if deposits is not None or withdraws is not None:
        dep_list = deposits or []
        wd_list = withdraws or []
        combined = (
            [{"type": "deposit", **(x if isinstance(x, dict) else {"raw": x})} for x in dep_list]
            + [{"type": "withdraw", **(x if isinstance(x, dict) else {"raw": x})} for x in wd_list]
        )
        combined.sort(key=lambda t: t.get("timestamp") or t.get("created_at") or t.get("raw") or 0, reverse=True)
        return {"items": combined[:limit], "count": len(combined), "source": "deposit/withdraw history (no auth)"}

    if not get_auth_required():
        return {
            "error": "입출금 내역: deposit/history, withdraw/history, l1Metadata 모두 인증 필요. private key 없이 보려면 L1 주소로 온체인 이벤트 조회(컨트랙트 0x3B4D794a66304F130a4Db8F2551B0070dfCf5ca7) 또는 API_KEY_PRIVATE_KEY 설정.",
            "items": [],
        }
    auth_token, err = await _get_auth_for_request()
    if err or not auth_token:
        return {"error": f"Auth token failed: {err}", "items": []}
    url = f"{BASE_URL.rstrip('/')}/api/v1/l1Metadata"
    params = {"account_index": ACCOUNT_INDEX, "auth": auth_token}
    if L1_ADDRESS:
        params["l1_address"] = L1_ADDRESS
    if limit:
        params["limit"] = limit
    headers = _auth_headers(auth_token)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {"error": f"HTTP {resp.status}: {text}", "items": []}
            data = await resp.json()
    items = data if isinstance(data, list) else getattr(data, "items", data.get("items", []))
    return {"items": items, "count": len(items) if isinstance(items, list) else 0, "source": "l1Metadata"}


async def get_trades_explorer(param: str, limit: int = 50) -> dict[str, Any]:
    """
    거래/주문 내역을 Lighter Explorer API에서 조회. 인증 불필요.
    offset 페이지네이션으로 100건 넘는 로그도 수집 후 필터.
    """
    raw = await get_account_logs_raw(param, limit=5000, use_pagination=True)
    if raw.get("error"):
        return {"trades": [], "error": raw["error"], "source": "explorer"}
    data = raw.get("logs", [])
    items = []
    for log in data:
        tx_type = log.get("tx_type", "")
        # 거래/주문 관련 타입 필터
        if tx_type in ("L2CreateOrder", "L2CancelOrder", "Trade", "OrderMatch", "Match", "Fill"):
            item = {
                "tx_type": tx_type,
                "hash": log.get("hash"),
                "time": log.get("time"),
                "pubdata": log.get("pubdata"),
            }
            # pubdata에서 거래 정보 추출
            if log.get("pubdata"):
                pd = log["pubdata"]
                # trade_pubdata_with_funding 또는 trade_pubdata 처리
                trade_data = None
                if "trade_pubdata_with_funding" in pd:
                    trade_data = pd["trade_pubdata_with_funding"]
                elif "trade_pubdata" in pd:
                    trade_data = pd["trade_pubdata"]
                
                if trade_data:
                    item["market_index"] = trade_data.get("market_index")
                    # is_taker_ask: taker 기준 0=매수, 1=매도. 우리 계정 기준으로 side 보정
                    is_taker_ask = trade_data.get("is_taker_ask", 0)
                    taker_idx = str(trade_data.get("taker_account_index", ""))
                    maker_idx = str(trade_data.get("maker_account_index", ""))
                    our_account = str(param) if (isinstance(param, str) and param.isdigit()) else (str(ACCOUNT_INDEX) if ACCOUNT_INDEX else None)
                    if our_account and (our_account == taker_idx or our_account == maker_idx):
                        if our_account == taker_idx:
                            item["side"] = "Sell" if is_taker_ask else "Buy"
                        else:
                            item["side"] = "Buy" if is_taker_ask else "Sell"  # maker는 taker 반대
                    else:
                        item["side"] = "Sell" if is_taker_ask else "Buy"
                    item["size"] = trade_data.get("size")
                    item["price"] = trade_data.get("price")
                    item["trade_type"] = trade_data.get("trade_type")
                    item["maker_account_index"] = trade_data.get("maker_account_index")
                    item["taker_account_index"] = trade_data.get("taker_account_index")
                    item["maker_fee"] = trade_data.get("maker_fee")
                    item["taker_fee"] = trade_data.get("taker_fee")
                    item["fee_account_index"] = trade_data.get("fee_account_index")
                    
                    # 사용자가 taker인지 maker인지 확인하여 수수료 계산
                    if our_account == taker_idx:
                        fee_bps = trade_data.get("taker_fee", 0)  # basis points (1 bps = 0.01%)
                    elif our_account == maker_idx:
                        fee_bps = trade_data.get("maker_fee", 0)
                    else:
                        fee_bps = 0
                    
                    # 수수료 계산: 거래 금액 * (fee_bps / 10000)
                    if item["size"] and item["price"]:
                        trade_value = float(item["size"]) * float(item["price"])
                        fee_usd = trade_value * (fee_bps / 10000.0) if fee_bps else 0.0
                        item["fee_usd"] = round(fee_usd, 6)
                    else:
                        item["fee_usd"] = 0.0
                elif "order_pubdata" in pd:
                    o = pd["order_pubdata"]
                    item["market_index"] = o.get("market_index")
                    item["side"] = o.get("side")
                    item["size"] = o.get("size")
                    item["price"] = o.get("price")
            items.append(item)
    items.sort(key=lambda x: x.get("time") or "", reverse=True)
    return {"trades": items[:limit], "count": len(items), "source": "explorer (no auth)"}


async def get_trades(limit: int = 50, market_id: Optional[int] = None) -> dict[str, Any]:
    """
    거래 내역 (체결 내역).
    1) Explorer API 시도 (인증 불필요)
    2) accountTrades endpoint 시도 (auth 필요)
    """
    # 먼저 Explorer API 시도
    if ACCOUNT_INDEX:
        explorer = await get_trades_explorer(str(ACCOUNT_INDEX), limit)
        if explorer.get("trades"):
            return explorer
    if L1_ADDRESS:
        explorer = await get_trades_explorer(L1_ADDRESS, limit)
        if explorer.get("trades"):
            return explorer
    
    # Explorer에서 못 찾으면 API 엔드포인트 시도
    if not get_auth_required():
        return {
            "error": "거래 내역: Explorer API에서 찾지 못함. READ_ONLY_AUTH_TOKEN 또는 API_KEY_PRIVATE_KEY 설정 필요.",
            "trades": [],
        }
    import aiohttp
    auth_token, err = await _get_auth_for_request()
    if err or not auth_token:
        return {"error": f"Auth token failed: {err}", "trades": []}
    url = f"{BASE_URL.rstrip('/')}/api/v1/accountTrades"
    params = {"account_index": ACCOUNT_INDEX, "auth": auth_token, "limit": limit}
    if market_id is not None:
        params["market_id"] = market_id
    headers = _auth_headers(auth_token)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {"error": f"HTTP {resp.status}: {text}", "trades": []}
            data = await resp.json()
    trades = data if isinstance(data, list) else getattr(data, "trades", data.get("trades", data.get("data", [])))
    return {"trades": trades, "count": len(trades) if isinstance(trades, list) else 0, "source": "accountTrades API"}


def _normalize_api_trade(raw: dict) -> dict:
    """accountTrades API 응답 한 건을 Explorer 형식과 비슷하게 정규화 (time, side, size, price, market_index)."""
    t = raw if isinstance(raw, dict) else {}
    # 가능한 필드명: time, created_at, timestamp, executed_at / side / size, amount / price / market_id, market_index
    time_val = t.get("time") or t.get("created_at") or t.get("timestamp") or t.get("executed_at") or ""
    if isinstance(time_val, (int, float)):
        from datetime import datetime
        try:
            time_val = datetime.utcfromtimestamp(time_val / 1000 if time_val > 1e12 else time_val).isoformat() + "Z"
        except Exception:
            time_val = str(time_val)
    side = t.get("side") or t.get("order_side") or ""
    if isinstance(side, int):
        side = "Sell" if side == 1 else "Buy"
    size = t.get("size") or t.get("amount") or t.get("filled_size")
    price = t.get("price") or t.get("avg_price") or t.get("executed_price")
    market_index = t.get("market_index") or t.get("market_id")
    return {
        "time": time_val,
        "side": side,
        "size": size,
        "price": price,
        "market_index": market_index,
        "tx_type": "accountTrades",
        "fee_usd": t.get("fee_usd", 0.0),
        **{k: v for k, v in t.items() if k not in ("time", "created_at", "timestamp", "side", "size", "price", "market_index", "market_id")},
    }


async def get_trades_account_trades_api(limit: int = 1000, offset: Optional[int] = None) -> dict[str, Any]:
    """
    Read token(auth)으로 accountTrades API만 호출. Explorer보다 과거 데이터가 많을 수 있음.
    offset 지원 시 페이지네이션 가능.
    """
    if not get_auth_required():
        return {"trades": [], "error": "READ_ONLY_AUTH_TOKEN 또는 API_KEY_PRIVATE_KEY 필요", "source": "accountTrades API"}
    if not ACCOUNT_INDEX:
        return {"trades": [], "error": "ACCOUNT_INDEX 필요", "source": "accountTrades API"}
    import aiohttp
    auth_token, err = await _get_auth_for_request()
    if err or not auth_token:
        return {"error": f"Auth token failed: {err}", "trades": [], "source": "accountTrades API"}
    url = f"{BASE_URL.rstrip('/')}/api/v1/accountTrades"
    params = {"account_index": ACCOUNT_INDEX, "auth": auth_token, "limit": limit}
    if offset is not None:
        params["offset"] = offset
    headers = _auth_headers(auth_token)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return {"error": f"HTTP {resp.status}: {text}", "trades": [], "source": "accountTrades API"}
                data = await resp.json()
    except Exception as e:
        return {"error": str(e), "trades": [], "source": "accountTrades API"}
    raw_list = data if isinstance(data, list) else data.get("trades", data.get("data", []))
    if not isinstance(raw_list, list):
        raw_list = []
    trades = [_normalize_api_trade(x) for x in raw_list]
    return {"trades": trades, "count": len(trades), "source": "accountTrades API"}


async def fetch_all_trades_via_api_until_april(max_count: int = 20000) -> dict[str, Any]:
    """
    Read token으로 accountTrades API를 offset 페이지네이션해 2025년 4월까지 거래 수집.
    API가 offset을 지원하지 않으면 limit만으로 한 번에 최대한 가져옴.
    """
    if not get_auth_required() or not ACCOUNT_INDEX:
        return {"trades": [], "error": "READ_ONLY_AUTH_TOKEN 및 ACCOUNT_INDEX 필요", "source": "accountTrades API"}
    all_trades: list = []
    limit = 1000
    offset = 0
    target_until = "2025-04"  # 4월 데이터까지 포함
    while len(all_trades) < max_count:
        result = await get_trades_account_trades_api(limit=limit, offset=offset)
        if result.get("error"):
            if offset == 0:
                return result
            break
        batch = result.get("trades") or []
        if not batch:
            break
        all_trades.extend(batch)
        # 가장 오래된 거래가 4월 이전이면 수집 완료
        times = [t.get("time") or "" for t in batch]
        oldest = min(times) if times else ""
        if target_until in oldest or (oldest and oldest < target_until):
            break
        if len(batch) < limit:
            break
        offset += len(batch)
        # offset 미지원 시 API가 같은 데이터 반복할 수 있음 → 중복 제거
        if offset > 0 and len(batch) == limit:
            await asyncio.sleep(0.2)
    # 시간 역순 유지 (최신 먼저), 중복 제거 (time+size+price 기준)
    seen = set()
    unique = []
    for t in all_trades:
        key = (t.get("time"), t.get("size"), t.get("price"))
        if key not in seen:
            seen.add(key)
            unique.append(t)
    unique.sort(key=lambda x: x.get("time") or "", reverse=True)
    return {"trades": unique, "count": len(unique), "source": "accountTrades API (paginated)"}


async def get_market_symbols() -> dict[int, str]:
    """마켓 인덱스 -> 심볼 매핑 가져오기"""
    client = lighter.ApiClient(lighter.Configuration(host=BASE_URL))
    try:
        api = lighter.OrderApi(client)
        order_books = await api.order_books()
        market_map = {}
        if hasattr(order_books, "order_books"):
            for idx, ob in enumerate(order_books.order_books):
                symbol = getattr(ob, "symbol", None)
                # market_index 속성 확인
                market_idx = getattr(ob, "market_index", idx)
                if symbol:
                    # 인덱스와 market_index 둘 다 매핑
                    market_map[idx] = symbol
                    if market_idx is not None and market_idx != idx:
                        market_map[market_idx] = symbol
        return market_map
    except Exception:
        # 기본 매핑 (ETH는 보통 마켓 0)
        return {0: "ETH"}
    finally:
        await client.close()


def parse_iso_time(time_str: str) -> str:
    """ISO 8601 시간을 YYYY-MM-DD-HH-MM-SS 형식으로 변환"""
    if not time_str:
        return ""
    try:
        # 2026-02-08T11:05:19.37Z 형식 파싱
        # Z를 +00:00로 변환하거나 그냥 제거
        clean_time = time_str.replace("Z", "")
        if "." in clean_time:
            # 밀리초 제거
            clean_time = clean_time.split(".")[0]
        # T를 공백으로, 공백을 -로
        clean_time = clean_time.replace("T", "-").replace(":", "-")
        # YYYY-MM-DD-HH-MM-SS 형식으로 변환
        parts = clean_time.split("-")
        if len(parts) >= 6:
            return f"{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}-{parts[4]}-{parts[5]}"
        return time_str
    except Exception as e:
        return time_str


def parse_date_from_iso(time_str: str) -> str:
    """ISO 시간에서 날짜만 추출 (YYYYMMDD 형식)"""
    if not time_str:
        return ""
    try:
        # 2026-02-08T11:05:19.37Z -> 20260208
        date_part = time_str.split("T")[0]
        return date_part.replace("-", "")
    except Exception:
        return ""


async def get_exchange_rate_for_date(date_str: str, fallback_rate: float = 1300.0) -> float:
    """
    특정 날짜의 USD/KRW 환율 조회.
    한국수출입은행 API 사용 (KOREAEXIM_API_KEY 필요).
    API 키가 없거나 조회 실패 시 fallback_rate 반환.
    
    Args:
        date_str: YYYYMMDD 형식 날짜 (예: "20260208")
        fallback_rate: API 조회 실패 시 사용할 기본 환율
    """
    if not KOREAEXIM_API_KEY:
        return fallback_rate
    
    import aiohttp
    url = "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON"
    params = {
        "authkey": KOREAEXIM_API_KEY,
        "searchdate": date_str,
        "data": "AP01"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return fallback_rate
                data = await resp.json()
                
                # 응답이 리스트인 경우 USD 찾기
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            cur_unit = item.get("cur_unit", "")
                            # USD 또는 840 (USD 코드)
                            if "USD" in cur_unit.upper() or item.get("cur_code") == "840":
                                # 매매기준율 또는 전일대비율 사용
                                rate_str = item.get("deal_bas_r", "") or item.get("ttb", "") or item.get("tts", "")
                                if rate_str:
                                    # 쉼표 제거 후 변환 (예: "1,300.00" -> 1300.0)
                                    rate_str = rate_str.replace(",", "")
                                    try:
                                        return float(rate_str)
                                    except ValueError:
                                        pass
                
                # USD를 찾지 못한 경우
                return fallback_rate
    except Exception:
        return fallback_rate


async def get_exchange_rates_for_dates(dates: set[str], fallback_rate: float = 1300.0) -> dict[str, float]:
    """
    여러 날짜의 환율을 한 번에 조회.
    캐싱하여 같은 날짜는 한 번만 조회.
    """
    rates = {}
    for date_str in dates:
        if date_str:
            rate = await get_exchange_rate_for_date(date_str, fallback_rate)
            rates[date_str] = rate
    return rates


async def export_to_csv(usd_to_krw_rate: float = 1300.0, use_daily_rates: bool = False) -> str:
    """
    거래 내역과 입출금 내역을 CSV 형식으로 변환.
    컬럼: 일시 | 거래소 | 유형 | 페어 | 통화 | 가격 | 원화가치 | 적용환율
    
    Args:
        usd_to_krw_rate: 기본 환율 (use_daily_rates=False일 때 사용)
        use_daily_rates: True면 거래일별 환율 조회 (KOREAEXIM_API_KEY 필요)
    """
    output = StringIO()
    writer = csv.writer(output)
    
    # 헤더
    writer.writerow(["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "수수료(USD)", "적용환율"])
    
    # 마켓 심볼 매핑 가져오기
    market_map = await get_market_symbols()
    
    # 포지션 정보에서 마켓 심볼 가져오기 (더 정확함)
    pnl_data = await get_pnl()
    for pos in pnl_data.get("positions", []):
        market_id = pos.get("market_id")
        symbol = pos.get("symbol")
        if market_id is not None and symbol:
            market_map[market_id] = symbol
    
    rows = []
    date_set = set()  # 거래일 수집용
    
    # 입출금 내역 추가
    deposits = await get_deposits_withdrawals(limit=1000)
    for item in deposits.get("items", []):
        if isinstance(item, dict):
            time_str = item.get("time", "")
            date_str = parse_iso_time(time_str) if time_str else ""
            date_yyyymmdd = parse_date_from_iso(time_str)
            if date_yyyymmdd:
                date_set.add(date_yyyymmdd)
            
            tx_type = item.get("tx_type", "")
            typ = "입금" if "Deposit" in tx_type else "출금"
            
            # amount 찾기: 직접 amount 또는 pubdata에서
            amount = item.get("amount")
            asset = item.get("asset_index", "USDC")
            
            # pubdata에서 accepted_amount 확인
            if not amount and item.get("pubdata"):
                pd = item.get("pubdata", {})
                if "l1_deposit_pubdata_v2" in pd:
                    amount = pd["l1_deposit_pubdata_v2"].get("accepted_amount")
                    if not asset:
                        asset = pd["l1_deposit_pubdata_v2"].get("asset_index", "USDC")
                elif "l1_withdraw_pubdata_v2" in pd:
                    amount = pd["l1_withdraw_pubdata_v2"].get("amount")
                    if not asset:
                        asset = pd["l1_withdraw_pubdata_v2"].get("asset_index", "USDC")
            
            if amount:
                amount_float = float(amount) if isinstance(amount, str) else amount
                # 환율은 나중에 적용
                rows.append({
                    "date_str": date_str,
                    "date_yyyymmdd": date_yyyymmdd,
                    "type": typ,
                    "pair": "",
                    "asset": asset or "USDC",
                    "amount": amount_float,
                    "usd_value": amount_float,
                    "price": amount_float,
                    "fee_usd": 0.0,  # 입출금은 수수료 없음
                })
    
    # 거래 내역 추가 (전체: limit 5000)
    trades = await get_trades(limit=5000)
    for trade in trades.get("trades", []):
        if isinstance(trade, dict):
            time_str = trade.get("time", "")
            date_str = parse_iso_time(time_str) if time_str else ""
            date_yyyymmdd = parse_date_from_iso(time_str)
            if date_yyyymmdd:
                date_set.add(date_yyyymmdd)
            
            tx_type = trade.get("tx_type", "")
            side = trade.get("side", "")
            market_idx = trade.get("market_index")
            symbol = market_map.get(market_idx) if market_idx is not None else None
            pair = f"{symbol}-USDC" if symbol else ""
            size = trade.get("size")
            price = trade.get("price")
            
            if size and price:
                size_float = float(size) if isinstance(size, str) else size
                price_float = float(price) if isinstance(price, str) else price
                usd_value = size_float * price_float
                
                # 유형: 매수/매도
                typ = "매수" if side == "Buy" else "매도"
                
                # 수수료 정보 가져오기
                fee_usd = trade.get("fee_usd", 0.0)
                
                rows.append({
                    "date_str": date_str,
                    "date_yyyymmdd": date_yyyymmdd,
                    "type": typ,
                    "pair": pair,
                    "asset": symbol or "",
                    "amount": size_float,
                    "usd_value": usd_value,
                    "price": price_float,
                    "fee_usd": fee_usd,
                })
    
    # 거래일별 환율 조회
    exchange_rates = {}
    if use_daily_rates and date_set:
        print(f"거래일별 환율 조회 중... ({len(date_set)}개 날짜)")
        exchange_rates = await get_exchange_rates_for_dates(date_set, fallback_rate=usd_to_krw_rate)
        if exchange_rates:
            print(f"환율 조회 완료: {len(exchange_rates)}개 날짜")
        else:
            print(f"환율 조회 실패. 기본 환율({usd_to_krw_rate}) 사용.")
    
    # 시간순 정렬 (오래된 것부터)
    rows.sort(key=lambda x: x["date_str"])
    
    # CSV 작성 (환율 적용)
    for row in rows:
        date_yyyymmdd = row["date_yyyymmdd"]
        if use_daily_rates and date_yyyymmdd and date_yyyymmdd in exchange_rates:
            rate = exchange_rates[date_yyyymmdd]
        else:
            rate = usd_to_krw_rate
        
        krw_value = row["usd_value"] * rate
        fee_usd = row.get("fee_usd", 0.0)
        
        writer.writerow([
            row["date_str"],
            "Lighter",
            row["type"],
            row["pair"],
            row["asset"],
            row["price"],
            round(krw_value, 2),
            round(fee_usd, 6),
            rate
        ])
    
    return output.getvalue()


async def print_csv_export(usd_to_krw_rate: float = 1300.0, output_file: Optional[str] = None, use_daily_rates: bool = False):
    """잔고를 먼저 표시하고 CSV 출력 또는 파일 저장"""
    # 잔고 표시
    b = await get_balance()
    if "error" not in b:
        print(f"잔고: {b.get('collateral_usd')} USDC")
        print(f"총 자산 가치: {b.get('total_asset_value_usd')} USDC")
        print()
    
    # CSV 생성
    csv_data = await export_to_csv(usd_to_krw_rate, use_daily_rates=use_daily_rates)
    
    # 파일로 저장 또는 출력
    if output_file:
        from pathlib import Path
        output_path = Path(output_file)
        output_path.write_text(csv_data, encoding='utf-8')
        print(f"CSV 파일이 저장되었습니다: {output_path.absolute()}")
        print(f"총 {len(csv_data.splitlines()) - 1}건의 거래 내역이 포함되었습니다.")
        if use_daily_rates:
            print("거래일별 환율이 적용되었습니다.")
    else:
        print(csv_data)


async def _create_auth_token(expiry_seconds: int = 3600) -> tuple[Optional[str], Optional[str]]:
    """Create auth token via SignerClient (create_auth_token_with_expiry)."""
    def _sync_create():
        c = lighter.SignerClient(
            url=BASE_URL,
            api_private_keys={API_KEY_INDEX: API_KEY_PRIVATE_KEY},
            account_index=ACCOUNT_INDEX,
        )
        out = c.create_auth_token_with_expiry(
            deadline=expiry_seconds,
            api_key_index=API_KEY_INDEX,
        )
        return (out[0], out[1]) if isinstance(out, (tuple, list)) else (out, None)
    try:
        token, err = await asyncio.to_thread(_sync_create)
        return (token, err)
    except Exception as e:
        return (None, str(e))


async def get_lighter_token_balance() -> dict[str, Any]:
    """
    입금받은 Lighter 토큰(LIT) 개수 계산.
    입출금 내역에서 LIT 토큰만 필터링하여 합계 계산.
    """
    deposits = await get_deposits_withdrawals(limit=10000)
    
    total_deposited = 0.0
    total_withdrawn = 0.0
    deposit_count = 0
    withdrawal_count = 0
    
    for item in deposits.get("items", []):
        if isinstance(item, dict):
            tx_type = item.get("tx_type", "")
            asset = item.get("asset_index", "")
            amount = item.get("amount")
            
            # pubdata에서 확인
            if item.get("pubdata"):
                pd = item.get("pubdata", {})
                if "l1_deposit_pubdata_v2" in pd:
                    asset = pd["l1_deposit_pubdata_v2"].get("asset_index", "")
                    amount = pd["l1_deposit_pubdata_v2"].get("accepted_amount") or pd["l1_deposit_pubdata_v2"].get("amount")
                elif "l1_withdraw_pubdata_v2" in pd:
                    asset = pd["l1_withdraw_pubdata_v2"].get("asset_index", "")
                    amount = pd["l1_withdraw_pubdata_v2"].get("amount")
            
            # LIT 토큰 확인 (대소문자 구분 없이)
            if asset and asset.upper() in ("LIT", "LIGHTER"):
                if amount:
                    amount_float = float(amount) if isinstance(amount, str) else amount
                    if "Deposit" in tx_type:
                        total_deposited += amount_float
                        deposit_count += 1
                    elif "Withdraw" in tx_type:
                        total_withdrawn += amount_float
                        withdrawal_count += 1
    
    net_balance = total_deposited - total_withdrawn
    
    return {
        "total_deposited": round(total_deposited, 6),
        "total_withdrawn": round(total_withdrawn, 6),
        "net_balance": round(net_balance, 6),
        "deposit_count": deposit_count,
        "withdrawal_count": withdrawal_count,
    }


QWANTIFY_AIRDROP_URL = "https://www.qwantify.io/app/lighter/airdrop"


async def get_airdrop_qwantify(wallet_address: Optional[str] = None) -> dict[str, Any]:
    """
    Qwantify에서 LIT 에어드랍 수량 조회.
    https://www.qwantify.io/app/lighter/airdrop?walletAddress=0x...&page=1
    """
    import re
    address = (wallet_address or L1_ADDRESS or "").strip()
    if not address or not address.startswith("0x"):
        return {"error": "wallet_address 필요", "airdrop_lit": None, "source": "qwantify"}
    url = f"{QWANTIFY_AIRDROP_URL}?walletAddress={address.lower()}&page=1"
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                text = await resp.text()
        if resp.status != 200:
            return {"error": f"HTTP {resp.status}", "airdrop_lit": None, "source": "qwantify"}
        # JSON 응답 시
        if text.strip().startswith("{"):
            try:
                import json
                data = json.loads(text)
                # 예상 키: allocation, airdrop, lit, amount 등
                for key in ("allocation", "airdrop", "lit", "amount", "totalAllocation", "eligible"):
                    if isinstance(data.get(key), (int, float)):
                        return {"airdrop_lit": float(data[key]), "raw": data, "source": "qwantify"}
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, (int, float)):
                            return {"airdrop_lit": float(v), "source": "qwantify"}
            except Exception:
                pass
        # HTML에서 __NEXT_DATA__ 또는 유사 JSON 추출
        next_data = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text, re.DOTALL)
        if next_data:
            try:
                import json
                data = json.loads(next_data.group(1))
                props = (data.get("props") or {}).get("pageProps") or data
                for key in ("allocation", "airdrop", "lit", "amount", "totalAllocation", "eligible", "airdropAmount"):
                    if isinstance(props.get(key), (int, float)):
                        return {"airdrop_lit": float(props[key]), "source": "qwantify"}
            except Exception:
                pass
        # 숫자 패턴 (LIT 수량으로 보이는 것)
        num_match = re.search(r'["\']?(?:allocation|airdrop|lit|amount)["\']?\s*:\s*([0-9]+\.?[0-9]*)', text, re.I)
        if num_match:
            try:
                return {"airdrop_lit": float(num_match.group(1)), "source": "qwantify"}
            except Exception:
                pass
        return {"error": "에어드랍 수량 파싱 실패", "airdrop_lit": None, "source": "qwantify"}
    except asyncio.TimeoutError:
        return {"error": "Qwantify 요청 시간 초과", "airdrop_lit": None, "source": "qwantify"}
    except Exception as e:
        return {"error": str(e), "airdrop_lit": None, "source": "qwantify"}


async def get_points() -> dict[str, Any]:
    """
    Lighter 포인트 정보 조회.
    referral/points 엔드포인트 사용.
    """
    if not get_auth_required():
        return {
            "error": "READ_ONLY_AUTH_TOKEN 또는 API_KEY_PRIVATE_KEY 필요",
            "user_total_points": 0,
        }
    
    import aiohttp
    auth_token, err = await _get_auth_for_request()
    if err or not auth_token:
        return {"error": f"Auth token failed: {err}", "user_total_points": 0}
    
    url = f"{BASE_URL.rstrip('/')}/api/v1/referral/points"
    params = {"account_index": ACCOUNT_INDEX, "auth": auth_token}
    headers = _auth_headers(auth_token)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return {"error": f"HTTP {resp.status}: {text}", "user_total_points": 0}
                data = await resp.json()
        
        return {
            "user_total_points": data.get("user_total_points", 0),
            "user_last_week_points": data.get("user_last_week_points", 0),
            "user_total_referral_reward_points": data.get("user_total_referral_reward_points", 0),
            "user_last_week_referral_reward_points": data.get("user_last_week_referral_reward_points", 0),
            "reward_point_multiplier": data.get("reward_point_multiplier", "0"),
            "referrals": data.get("referrals", []),
        }
    except Exception as e:
        return {"error": str(e), "user_total_points": 0}


async def calculate_all_time_pnl() -> dict[str, Any]:
    """
    All-time PNL 계산: 현재 총 자산 - 총 순 입금액.
    총 출금 = L1 인출 + L2 이체(다른 계정으로 보낸 금액).
    """
    # 현재 잔고 및 자산 가치
    balance = await get_balance()
    current_value = balance.get("total_asset_value_usd", balance.get("collateral_usd", 0.0))
    our_account_index = balance.get("account_index")

    # 입출금 내역으로 총 입금 / L1 출금 계산
    deposits = await get_deposits_withdrawals(limit=10000)
    total_deposits = 0.0
    total_l1_withdrawals = 0.0

    for item in deposits.get("items", []):
        if isinstance(item, dict):
            tx_type = item.get("tx_type", "")
            amount = item.get("amount")
            if not amount and item.get("pubdata"):
                pd = item.get("pubdata", {})
                if "l1_deposit_pubdata_v2" in pd:
                    amount = pd["l1_deposit_pubdata_v2"].get("accepted_amount")
                elif "l1_withdraw_pubdata_v2" in pd:
                    amount = pd["l1_withdraw_pubdata_v2"].get("amount")
            if amount:
                amount_float = float(amount) if isinstance(amount, str) else amount
                if "Deposit" in tx_type:
                    total_deposits += amount_float
                elif "Withdraw" in tx_type:
                    total_l1_withdrawals += amount_float

    # L2 이체(다른 계정으로 보낸 금액) 합산
    param = L1_ADDRESS if L1_ADDRESS else (str(ACCOUNT_INDEX) if ACCOUNT_INDEX else None)
    l2_transfer_out = 0.0
    if param:
        l2_transfer_out = await get_l2_transfer_out_total(param, our_account_index)
    total_withdrawals = total_l1_withdrawals + l2_transfer_out

    net_deposits = total_deposits - total_withdrawals
    all_time_pnl = current_value - net_deposits

    return {
        "current_value": round(current_value, 2),
        "total_deposits": round(total_deposits, 2),
        "total_withdrawals": round(total_withdrawals, 2),
        "total_l1_withdrawals": round(total_l1_withdrawals, 2),
        "l2_transfer_out": round(l2_transfer_out, 2),
        "net_deposits": round(net_deposits, 2),
        "all_time_pnl": round(all_time_pnl, 2),
        "pnl_percentage": round((all_time_pnl / net_deposits * 100) if net_deposits > 0 else 0.0, 2),
    }


async def print_summary():
    """잔고 및 All-time PNL 요약 출력. 순서: 입출금 내역 → 총 입출금/All-time PNL → 잔고 → 포인트 → LIT·에어드랍"""
    print("=" * 50)
    print("📊 계정 요약")
    print("=" * 50)

    # 1) 입출금 내역 먼저
    await print_deposits_withdrawals(limit=50)
    print()

    pnl_data = None
    # 2) 총 입금 / 총 출금 (L1 인출 + L2 이체 보낸 금액)
    try:
        pnl_data = await calculate_all_time_pnl()
        print(f"\n💵 총 입금: {pnl_data.get('total_deposits', 0)} USD")
        tw = pnl_data.get('total_withdrawals', 0)
        print(f"💵 총 출금: {tw} USD", end="")
        l1w = pnl_data.get('total_l1_withdrawals', 0)
        l2out = pnl_data.get('l2_transfer_out', 0)
        if l2out and l2out > 0:
            print(f" (L1 인출: {l1w}, L2 이체: {l2out})")
        else:
            print()
        # L2 이체 어디로 나갔는지: 목적지(계정+L1주소)별 금액
        if l2out and l2out > 0:
            param = L1_ADDRESS if L1_ADDRESS else (str(ACCOUNT_INDEX) if ACCOUNT_INDEX else None)
            if param:
                try:
                    breakdown = await get_l2_transfer_out_breakdown(param)
                    for row in breakdown:
                        to_idx = row.get("to_account_index", "")
                        addr = row.get("l1_address") or "(주소 조회 실패)"
                        if addr and addr != "(주소 조회 실패)" and len(addr) > 10:
                            addr_short = f"{addr[:6]}...{addr[-4:]}"
                        else:
                            addr_short = addr
                        print(f"   → 계정 {to_idx} ({addr_short}): {row.get('amount', 0)} USD")
                except Exception:
                    pass
    except Exception as e:
        print(f"\n💵 총 입금/출금 조회 오류: {e}")

    # 잔고 (API 503 등 예외 시에도 입출금/거래는 Explorer로 계속 출력)
    try:
        b = await get_balance()
    except Exception as e:
        b = {"error": str(e)}
    if "error" not in b:
        print(f"\n💰 잔고: {b.get('collateral_usd')} USDC")
        if b.get("total_asset_value_usd") is not None:
            print(f"   총 자산 가치: {b.get('total_asset_value_usd')} USDC")
        if b.get("available_balance_usd") is not None:
            print(f"   사용 가능: {b.get('available_balance_usd')} USDC")
    else:
        print(f"\n⚠️  잔고 조회 실패: {b.get('error', '')}")

    # All-time PNL (위에서 pnl_data 있으면 재사용, 없으면 재계산)
    try:
        if pnl_data is None:
            pnl_data = await calculate_all_time_pnl()
        print(f"\n📈 All-time PNL: {pnl_data.get('all_time_pnl')} USD")
        if pnl_data.get('net_deposits', 0) > 0:
            pnl_pct = pnl_data.get('pnl_percentage', 0)
            sign = "+" if pnl_pct >= 0 else ""
            print(f"   수익률: {sign}{pnl_pct}%")
        print(f"   순 입금: {pnl_data.get('net_deposits')} USD")
    except Exception as e:
        print(f"\n⚠️  All-time PNL 계산 오류: {e}")
    
    # 현재 포지션 PNL
    try:
        p = await get_pnl()
    except Exception as e:
        p = {"error": str(e)}
    if "error" not in p:
        print(f"\n📊 현재 포지션 PNL:")
        print(f"   미실현: {p.get('total_unrealized_pnl_usd')} USD")
        print(f"   실현: {p.get('total_realized_pnl_usd')} USD")
        print(f"   합계: {p.get('total_pnl_usd')} USD")

    # Lighter 포인트 (요청 순서: 포인트 → 에어드랍 LIT)
    try:
        points_data = await get_points()
        if "error" not in points_data:
            print(f"\n🎁 Lighter 포인트:")
            print(f"   총 포인트: {points_data.get('user_total_points', 0):,}")
            print(f"   지난 주 포인트: {points_data.get('user_last_week_points', 0):,}")
            if points_data.get('user_total_referral_reward_points', 0) > 0:
                print(f"   총 추천 보상 포인트: {points_data.get('user_total_referral_reward_points', 0):,}")
            if points_data.get('reward_point_multiplier'):
                multiplier = float(points_data.get('reward_point_multiplier', 0))
                if multiplier > 0:
                    print(f"   보상 포인트 배수: {multiplier}x")
    except Exception as e:
        print(f"\n⚠️  포인트 조회 오류: {e}")

    # Lighter 토큰(LIT) + 에어드랍 받은 LIT
    try:
        lit_data = await get_lighter_token_balance()
        print(f"\n🪙 Lighter 토큰 (LIT) — 입금·에어드랍 기준:")
        print(f"   입금받은 총량: {lit_data.get('total_deposited', 0):,.6f} LIT")
        print(f"   출금한 총량: {lit_data.get('total_withdrawn', 0):,.6f} LIT")
        print(f"   현재 잔고 (입금−출금): {lit_data.get('net_balance', 0):,.6f} LIT")
        print(f"   입금 횟수: {lit_data.get('deposit_count', 0)}회")
    except Exception as e:
        print(f"\n⚠️  Lighter 토큰 조회 오류: {e}")
    if L1_ADDRESS:
        try:
            airdrop = await get_airdrop_qwantify(L1_ADDRESS)
            if airdrop.get("airdrop_lit") is not None:
                print(f"   에어드랍 (Qwantify): {airdrop['airdrop_lit']:,.2f} LIT")
            elif airdrop.get("error"):
                print(f"   에어드랍 (Qwantify): 자동 조회 실패 — 브라우저에서 확인:")
                print(f"      {QWANTIFY_AIRDROP_URL}?walletAddress={L1_ADDRESS.lower()}&page=1")
        except Exception as e:
            print(f"   에어드랍 (Qwantify): {e}")
            print(f"      수동 확인: {QWANTIFY_AIRDROP_URL}?walletAddress={L1_ADDRESS.lower()}&page=1")

    print("\n" + "=" * 50)


async def print_balance():
    b = await get_balance()
    if "error" in b:
        print("잔고 오류:", b["error"])
        return
    print("=== 잔고 (Balance) ===")
    print(f"  계정 인덱스: {b.get('account_index')}")
    print(f"  담보 (USDC): {b.get('collateral_usd')}")
    if b.get("available_balance_usd") is not None:
        print(f"  사용 가능: {b.get('available_balance_usd')} USDC")
    if b.get("total_asset_value_usd") is not None:
        print(f"  총 자산 가치: {b.get('total_asset_value_usd')} USDC")


async def print_pnl():
    p = await get_pnl()
    if "error" in p:
        print("손익 오류:", p["error"])
        return
    print("=== 손익 (PnL) ===")
    print(f"  미실현 PnL (USD): {p.get('total_unrealized_pnl_usd')}")
    print(f"  실현 PnL (USD):   {p.get('total_realized_pnl_usd')}")
    print(f"  합계 PnL (USD):   {p.get('total_pnl_usd')}")
    for pos in p.get("positions") or []:
        market_info = pos.get("symbol") or f"마켓 {pos.get('market_id')}" or "마켓 정보 없음"
        position_info = f"포지션: {pos.get('position')}" if pos.get('position') is not None else ""
        sign_info = f" ({pos.get('sign')})" if pos.get('sign') else ""
        entry_info = f" 진입가: {pos.get('avg_entry_price')}" if pos.get('avg_entry_price') is not None else ""
        print(f"    {market_info}{sign_info}: 미실현 {pos.get('unrealized_pnl')} USD, 실현 {pos.get('realized_pnl')} USD, 가치 {pos.get('position_value_usd')} USD{entry_info}")


async def print_deposits_withdrawals(limit: int = 50):
    d = await get_deposits_withdrawals(limit=limit)
    if d.get("error") and not d.get("items"):
        err = d["error"]
        print("입출금 내역 오류:", err)
        if "on-chain" in (d.get("source") or ""):
            print("  (Etherscan 무료 API 키 ETHERSCAN_API_KEY 설정 시 해결될 수 있음)")
        return
    source = d.get("source", "API")
    print(f"=== 입출금 내역 ({source}) {d.get('count', 0)}건 ===")
    for i, item in enumerate(d.get("items") or []):
        if isinstance(item, dict):
            if item.get("etherscan"):
                ts = item.get("time")
                ts_str = f" @ {ts}" if ts else ""
                print(f"  [{i+1}] {item.get('type', '?')}  tx: {item.get('tx_hash', '')}{ts_str}  {item.get('etherscan')}")
            elif item.get("tx_type"):
                tx_type = item.get("tx_type", "")
                typ = "입금" if "Deposit" in tx_type else "출금"
                time = item.get("time", "")
                amount = item.get("amount") or item.get("pubdata", {}).get("l1_deposit_pubdata_v2", {}).get("accepted_amount") or item.get("pubdata", {}).get("l1_withdraw_pubdata_v2", {}).get("amount")
                asset = item.get("asset_index", "")
                if amount:
                    print(f"  [{i+1}] {typ}  {amount} {asset}  {time}")
                else:
                    print(f"  [{i+1}] {typ}  {tx_type}  {time}")
            else:
                print(f"  [{i+1}] {item}")
        else:
            print(f"  [{i+1}] {item}")


async def print_trades(limit: int = 50, max_display: Optional[int] = 20, trades_result: Optional[dict] = None):
    if trades_result is not None:
        t = trades_result
    else:
        t = await get_trades(limit=limit)
    if t.get("error") and not t.get("trades"):
        print("거래 내역 오류:", t["error"])
        return
    source = t.get("source", "API")
    print(f"=== 거래 내역 ({source}) {t.get('count', 0)}건 ===")
    trades_list = t.get("trades") or []
    if max_display is not None:
        trades_list = trades_list[:max_display]
    for i, tr in enumerate(trades_list):
        if isinstance(tr, dict):
            tx_type = tr.get("tx_type", "")
            time = tr.get("time", "")
            if tr.get("market_index") is not None:
                market = tr.get("market_index")
                side = tr.get("side", "")
                size = tr.get("size", "")
                price = tr.get("price", "")
                taker = tr.get("taker_account_index", "")
                maker = tr.get("maker_account_index", "")
                info = f"마켓 {market}  {side}  크기: {size}  가격: {price}"
                if taker or maker:
                    info += f"  (Taker: {taker}, Maker: {maker})"
                print(f"  [{i+1}] {tx_type}  {info}  {time}")
            else:
                print(f"  [{i+1}] {tx_type}  {time}  해시: {tr.get('hash', '')[:20]}...")
        else:
            print(f"  [{i+1}] {tr}")


async def watch_mode(output_file: str, interval: int = 60, usd_to_krw_rate: float = 1300.0, use_daily_rates: bool = False):
    """
    실시간 모니터링 모드: 주기적으로 CSV 파일 업데이트
    """
    from datetime import datetime
    
    print(f"실시간 모니터링 시작... (간격: {interval}초)")
    print(f"CSV 파일: {output_file}")
    print("종료하려면 Ctrl+C를 누르세요.\n")
    
    last_count = 0
    
    try:
        while True:
            try:
                # CSV 생성
                csv_data = await export_to_csv(usd_to_krw_rate, use_daily_rates=use_daily_rates)
                current_count = len(csv_data.splitlines()) - 1  # 헤더 제외
                
                # 파일 저장
                from pathlib import Path
                output_path = Path(output_file)
                output_path.write_text(csv_data, encoding='utf-8')
                
                # 변경사항 표시
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if current_count != last_count:
                    print(f"[{timestamp}] 업데이트: {current_count}건 (이전: {last_count}건)")
                    last_count = current_count
                else:
                    print(f"[{timestamp}] 확인: {current_count}건 (변경 없음)")
                
                # 대기
                await asyncio.sleep(interval)
            except KeyboardInterrupt:
                print("\n모니터링 종료.")
                break
            except Exception as e:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 오류: {e}")
                await asyncio.sleep(interval)
    except KeyboardInterrupt:
        print("\n모니터링 종료.")


async def main():
    import sys
    from datetime import datetime
    
    # 실시간 모니터링 모드 확인 (--watch 또는 -w)
    if "--watch" in sys.argv or "-w" in sys.argv:
        # 출력 파일 확인
        output_file = "lighter_transactions_live.csv"
        if "--output" in sys.argv:
            idx = sys.argv.index("--output")
            if idx + 1 < len(sys.argv):
                output_file = sys.argv[idx + 1]
        elif "-o" in sys.argv:
            idx = sys.argv.index("-o")
            if idx + 1 < len(sys.argv):
                output_file = sys.argv[idx + 1]
        
        # 간격 확인 (--interval 또는 -i)
        interval = 60  # 기본 60초
        if "--interval" in sys.argv:
            idx = sys.argv.index("--interval")
            if idx + 1 < len(sys.argv):
                try:
                    interval = int(sys.argv[idx + 1])
                except ValueError:
                    pass
        elif "-i" in sys.argv:
            idx = sys.argv.index("-i")
            if idx + 1 < len(sys.argv):
                try:
                    interval = int(sys.argv[idx + 1])
                except ValueError:
                    pass
        
        # 환율 확인
        rate = 1300.0
        if "--rate" in sys.argv:
            idx = sys.argv.index("--rate")
            if idx + 1 < len(sys.argv):
                try:
                    rate = float(sys.argv[idx + 1])
                except ValueError:
                    pass
        elif "-r" in sys.argv:
            idx = sys.argv.index("-r")
            if idx + 1 < len(sys.argv):
                try:
                    rate = float(sys.argv[idx + 1])
                except ValueError:
                    pass
        
        use_daily_rates = "--daily-rates" in sys.argv or "-d" in sys.argv
        
        await watch_mode(output_file, interval=interval, usd_to_krw_rate=rate, use_daily_rates=use_daily_rates)
        return
    
    # CSV 출력 모드 확인
    if "--csv" in sys.argv or "-c" in sys.argv:
        # 환율 인자 확인 (--rate 또는 -r)
        rate = 1300.0
        if "--rate" in sys.argv:
            idx = sys.argv.index("--rate")
            if idx + 1 < len(sys.argv):
                try:
                    rate = float(sys.argv[idx + 1])
                except ValueError:
                    pass
        elif "-r" in sys.argv:
            idx = sys.argv.index("-r")
            if idx + 1 < len(sys.argv):
                try:
                    rate = float(sys.argv[idx + 1])
                except ValueError:
                    pass
        
        # 출력 파일 확인 (--output 또는 -o)
        output_file = None
        if "--output" in sys.argv:
            idx = sys.argv.index("--output")
            if idx + 1 < len(sys.argv):
                output_file = sys.argv[idx + 1]
        elif "-o" in sys.argv:
            idx = sys.argv.index("-o")
            if idx + 1 < len(sys.argv):
                output_file = sys.argv[idx + 1]
        
        # 파일명이 지정되지 않으면 기본 파일명 생성
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"lighter_transactions_{timestamp}.csv"
        
        # 거래일별 환율 사용 여부 확인 (--daily-rates 또는 -d)
        use_daily_rates = "--daily-rates" in sys.argv or "-d" in sys.argv
        
        await print_csv_export(usd_to_krw_rate=rate, output_file=output_file, use_daily_rates=use_daily_rates)
        return

    # Explorer 로그 전체 조회 (--logs). 계정 로그 API로 모든 tx_type 확인
    if "--logs" in sys.argv or "-l" in sys.argv:
        param = L1_ADDRESS if L1_ADDRESS else str(ACCOUNT_INDEX)
        if not param:
            print("L1_ADDRESS 또는 ACCOUNT_INDEX 설정 필요")
            return
        raw = await get_account_logs_raw(param, limit=5000)
        if raw.get("error"):
            print("로그 조회 실패:", raw["error"])
            return
        logs = raw.get("logs", [])
        from collections import Counter
        types = Counter(log.get("tx_type", "(unknown)") for log in logs)
        print("=== Explorer 계정 로그 (전체) ===")
        print(f"  API: {EXPLORER_BASE}/api/accounts/{param}/logs")
        print(f"  총 {len(logs)}건, tx_type별:")
        for tx_type, count in sorted(types.items(), key=lambda x: -x[1]):
            print(f"    {tx_type}: {count}건")
        show = min(20, len(logs))
        if show:
            print(f"\n  최근 {show}건 요약 (time, tx_type, hash):")
            for i, log in enumerate(logs[:show]):
                print(f"    [{i+1}] {log.get('time', '')}  {log.get('tx_type', '')}  {log.get('hash', '')}")
        return

    # 로그 전체 CSV 내보내기 (--logs-csv). 계정 기준 로그 전부 뽑아서 CSV 저장
    if "--logs-csv" in sys.argv:
        param = L1_ADDRESS if L1_ADDRESS else str(ACCOUNT_INDEX)
        if not param:
            print("L1_ADDRESS 또는 ACCOUNT_INDEX 설정 필요")
            return
        output_file = None
        if "-o" in sys.argv and sys.argv.index("-o") + 1 < len(sys.argv):
            output_file = sys.argv[sys.argv.index("-o") + 1]
        if not output_file:
            output_file = f"lighter_logs_{param[:10].replace('0x', '')}.csv"
        try:
            csv_content = await export_logs_to_csv_flat(param, output_path=output_file)
            lines = csv_content.strip().splitlines()
            n = len(lines) - 1
            print(f"로그 CSV 저장(보기 쉬운 컬럼): {output_file} ({n}건)")
            if n >= 1:
                # 첫 행(헤더) 제외, 1행=최신·마지막 행=최구
                newest = lines[1].split(",")[0][:10]
                oldest = lines[-1].split(",")[0][:10]
                print(f"데이터 기간: {oldest} ~ {newest} (Explorer 제공 범위)")
                if "2025-04" not in oldest and "2025-05" not in oldest and "2025-06" not in oldest and "2025-07" not in oldest:
                    print("  ※ 4~7월 등 그 이전 데이터는 Explorer에 없을 수 있습니다. (보관 한계)")
        except Exception as e:
            print(f"오류: {e}")
        return

    # Read-token만 사용 (Explorer 제외): 입출금 deposit/withdraw history + l1Metadata, 거래 accountTrades 시도 (--via-read-token)
    if "--via-read-token" in sys.argv or "--read-token" in sys.argv:
        if not get_auth_required():
            print("READ_ONLY_AUTH_TOKEN 또는 API_KEY_PRIVATE_KEY 필요")
            return
        if not ACCOUNT_INDEX:
            print("ACCOUNT_INDEX 필요 (.env에 설정)")
            return
        print("Read-token으로 입출금/거래 API만 호출 (Explorer 미사용)...")
        # 1) 입출금: deposit/history, withdraw/history, l1Metadata
        dw = await get_deposits_withdrawals_via_read_token(limit=5000)
        if dw.get("error") and not dw.get("items"):
            print("입출금:", dw.get("error"))
        else:
            print(f"\n=== 입출금 내역 ({dw.get('source', '')}) {dw.get('count', 0)}건 ===")
            for i, item in enumerate(dw.get("items") or [])[:100]:
                typ = item.get("type", item.get("tx_type", "?"))
                ts = item.get("time") or item.get("created_at") or item.get("timestamp") or item.get("executed_at") or ""
                amt = item.get("amount") or item.get("accepted_amount") or item.get("usdc_amount") or ""
                print(f"  [{i+1}] {typ}  {amt}  {ts}")
            if (dw.get("count") or 0) > 100:
                print(f"  ... 외 {dw.get('count', 0) - 100}건")
        # 2) 거래: accountTrades (read-token이 403이면 실패할 수 있음)
        tr = await get_trades_account_trades_api(limit=5000)
        if tr.get("error"):
            print(f"\n거래 (accountTrades): {tr.get('error')} — read-token 미지원일 수 있음")
        else:
            trades = tr.get("trades") or []
            print(f"\n=== 거래 내역 ({tr.get('source', '')}) {len(trades)}건 ===")
            for i, t in enumerate(trades[:50]):
                tm = t.get("time") or ""
                side = t.get("side", "")
                sz = t.get("size", "")
                pr = t.get("price", "")
                print(f"  [{i+1}] {tm[:19]}  {side}  size={sz}  price={pr}")
            if len(trades) > 50:
                print(f"  ... 외 {len(trades) - 50}건")
        # CSV 저장
        if "-o" in sys.argv and sys.argv.index("-o") + 1 < len(sys.argv):
            out_path = sys.argv[sys.argv.index("-o") + 1]
            import csv
            from io import StringIO
            buf = StringIO()
            w = csv.writer(buf)
            w.writerow(["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "수수료(USD)", "적용환율"])
            rate = 1300.0
            for item in dw.get("items") or []:
                typ = item.get("type", item.get("tx_type", ""))
                ts = (item.get("time") or item.get("created_at") or item.get("timestamp") or "").replace("Z", "").replace("T", " ")[:19]
                amt = item.get("amount") or item.get("accepted_amount") or item.get("usdc_amount") or 0
                try:
                    amt_f = float(amt)
                except (TypeError, ValueError):
                    amt_f = 0
                krw = round(amt_f * rate, 2)
                w.writerow([ts, "Lighter", "입금" if "deposit" in str(typ).lower() else "출금", "", "USDC", amt_f, krw, 0, rate])
            for t in tr.get("trades") or []:
                tm = (t.get("time") or "").replace("Z", "").replace("T", " ")[:19]
                side = "매수" if (t.get("side") or "").upper() in ("BUY", "B") else "매도"
                sz = t.get("size") or 0
                pr = t.get("price") or 0
                try:
                    usd = float(sz) * float(pr)
                except (TypeError, ValueError):
                    usd = 0
                w.writerow([tm, "Lighter", side, "", "", pr, round(usd * rate, 2), t.get("fee_usd", 0) or 0, rate])
            from pathlib import Path
            Path(out_path).write_text(buf.getvalue(), encoding="utf-8")
            print(f"\nCSV 저장: {out_path}")
        return

    # Read token으로 accountTrades API만 사용해 4월까지 과거 거래 수집 (--trades-api)
    if "--trades-api" in sys.argv:
        if not get_auth_required():
            print("READ_ONLY_AUTH_TOKEN 또는 API_KEY_PRIVATE_KEY 필요")
            return
        if not ACCOUNT_INDEX:
            print("ACCOUNT_INDEX 필요 (.env에 설정)")
            return
        print("Read token으로 accountTrades API 호출 중... (4월까지 수집 시도)")
        result = await fetch_all_trades_via_api_until_april(max_count=20000)
        if result.get("error"):
            print("오류:", result["error"])
            return
        trades = result.get("trades") or []
        print(f"\n=== 거래 내역 ({result.get('source', 'accountTrades API')}) {len(trades)}건 ===")
        if trades:
            oldest = min(t.get("time") or "" for t in trades)
            newest = max(t.get("time") or "" for t in trades)
            print(f"기간: {oldest[:10] if oldest else '?'} ~ {newest[:10] if newest else '?'}")
        await print_trades(max_display=None, trades_result=result)
        # CSV 저장 옵션 (-o 파일명)
        if "-o" in sys.argv and sys.argv.index("-o") + 1 < len(sys.argv):
            out_path = sys.argv[sys.argv.index("-o") + 1]
            import csv
            from io import StringIO
            buf = StringIO()
            w = csv.writer(buf)
            w.writerow(["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "수수료(USD)", "적용환율"])
            rate = 1300.0
            for tr in trades:
                tm = (tr.get("time") or "").replace("Z", "").replace("T", " ")
                side = "매수" if (tr.get("side") or "").upper() in ("BUY", "B") else "매도"
                sz = tr.get("size") or 0
                pr = tr.get("price") or 0
                try:
                    usd = float(sz) * float(pr)
                except (TypeError, ValueError):
                    usd = 0
                fee = tr.get("fee_usd", 0) or 0
                w.writerow([tm[:19], "Lighter", side, "", "", pr, round(usd * rate, 2), fee, rate])
            from pathlib import Path
            Path(out_path).write_text(buf.getvalue(), encoding="utf-8")
            print(f"\nCSV 저장: {out_path} ({len(trades)}건)")
        return

    # 전체 데이터 모드 (--all / -a): 페이지네이션으로 전부 뽑아서 동일 형식으로 출력
    if "--all" in sys.argv or "-a" in sys.argv:
        await print_summary()
        print()
        await print_deposits_withdrawals(limit=5000)
        print()
        await print_trades(limit=5000, max_display=None)
        return

    # 기본 모드: 입출금 내역 → All-time PNL → 포인트 → LIT·에어드랍 (요약 안에 포함), 거래 최근 15건
    await print_summary()
    print()
    await print_trades(limit=50, max_display=15)
    print("  (거래 전체는 --all 또는 -a 사용)")


if __name__ == "__main__":
    asyncio.run(main())
