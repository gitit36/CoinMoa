"""
EdgeX API client: 잔고, 입출금(담보) 내역, 거래 내역, 손익.
Same pattern as Lighter. Docs: https://edgex-1.gitbook.io/edgeX-documentation/api
Requires: EDGEX_ACCOUNT_ID, EDGEX_STARK_PRIVATE_KEY in .env
"""
import asyncio
import csv
from datetime import datetime
from io import StringIO
from typing import Any, Optional

from config import EDGEX_ACCOUNT_ID, EDGEX_BASE_URL, EDGEX_STARK_PRIVATE_KEY


def _edgex_configured() -> bool:
    return bool(EDGEX_ACCOUNT_ID and EDGEX_STARK_PRIVATE_KEY)


def _get_client():
    """Lazy import edgex_sdk (sync constructor)."""
    try:
        from edgex_sdk import Client
    except ImportError:
        raise ImportError(
            "EdgeX 사용 시 pip install edgex-python-sdk 필요. "
            "설치 후 EDGEX_ACCOUNT_ID, EDGEX_STARK_PRIVATE_KEY 를 .env 에 설정하세요."
        )
    return Client(
        base_url=EDGEX_BASE_URL,
        account_id=int(EDGEX_ACCOUNT_ID),
        stark_private_key=EDGEX_STARK_PRIVATE_KEY,
    )


async def get_balance() -> dict[str, Any]:
    """계정 자산(잔고). getAccountAsset -> collateralList, totalEquity."""
    if not _edgex_configured():
        return {"error": "EDGEX_ACCOUNT_ID, EDGEX_STARK_PRIVATE_KEY 설정 필요"}
    try:
        client = _get_client()
        resp = await client.get_account_asset()
    except Exception as e:
        return {"error": str(e)}
    if not resp or resp.get("code") != "SUCCESS":
        return {"error": resp.get("msg") or "get_account_asset failed"}
    data = resp.get("data", {})
    collateral_list = data.get("collateralList") or data.get("collateralAssetModelList") or []
    total_equity = 0.0
    available = 0.0
    for c in collateral_list:
        total_equity += float(c.get("totalEquity") or 0)
        available += float(c.get("availableAmount") or 0)
    return {
        "account_id": EDGEX_ACCOUNT_ID,
        "collateral_usd": round(total_equity, 2),
        "available_balance_usd": round(available, 2) if available else round(total_equity, 2),
        "total_asset_value_usd": round(total_equity, 2),
    }


async def get_pnl() -> dict[str, Any]:
    """손익: positionList 의 unrealizePnl, termRealizePnl 등."""
    if not _edgex_configured():
        return {"error": "EDGEX_ACCOUNT_ID, EDGEX_STARK_PRIVATE_KEY 설정 필요"}
    try:
        client = _get_client()
        resp = await client.get_account_asset()
    except Exception as e:
        return {"error": str(e)}
    if not resp or resp.get("code") != "SUCCESS":
        return {"error": resp.get("msg") or "get_account_asset failed"}
    data = resp.get("data", {})
    positions = data.get("positionList") or data.get("positionAssetList") or []
    total_u = 0.0
    total_r = 0.0
    for p in positions:
        total_u += float(p.get("unrealizePnl", 0) or 0)
        total_r += float(p.get("termRealizePnl", 0) or p.get("totalRealizePnl", 0) or 0)
    return {
        "account_index": EDGEX_ACCOUNT_ID,
        "total_unrealized_pnl_usd": round(total_u, 2),
        "total_realized_pnl_usd": round(total_r, 2),
        "total_pnl_usd": round(total_u + total_r, 2),
        "positions": positions,
    }


async def get_deposits_withdrawals(limit: int = 50) -> dict[str, Any]:
    """담보 입출금 내역. getCollateralTransactionPage."""
    if not _edgex_configured():
        return {"items": [], "error": "EDGEX_ACCOUNT_ID, EDGEX_STARK_PRIVATE_KEY 설정 필요"}
    try:
        from edgex_sdk.account.client import GetCollateralTransactionPageParams
        client = _get_client()
        params = GetCollateralTransactionPageParams(size=str(min(limit, 100)), offset_data="")
        resp = await client.account.get_collateral_transaction_page(params)
    except ImportError:
        return {"items": [], "error": "pip install edgex-python-sdk 필요"}
    except Exception as e:
        return {"items": [], "error": str(e)}
    if not resp or resp.get("code") != "SUCCESS":
        return {"items": [], "error": resp.get("msg") or "get_collateral_transaction_page failed"}
    data_list = (resp.get("data") or {}).get("dataList") or []
    items = []
    for row in data_list[:limit]:
        typ = row.get("type", "")
        is_deposit = "DEPOSIT" in typ.upper() or "TRANSFER_IN" in typ.upper()
        items.append({
            "type": "deposit" if is_deposit else "withdraw",
            "tx_type": typ,
            "time": row.get("createdTime"),
            "amount": row.get("deltaAmount") or row.get("amount"),
            "asset_index": row.get("coinId"),
        })
    return {"items": items, "count": len(items), "source": "EdgeX API"}


async def get_trades(limit: int = 50) -> dict[str, Any]:
    """포지션/체결 내역. getPositionTransactionPage."""
    if not _edgex_configured():
        return {"trades": [], "error": "EDGEX_ACCOUNT_ID, EDGEX_STARK_PRIVATE_KEY 설정 필요"}
    try:
        from edgex_sdk.account.client import GetPositionTransactionPageParams
        client = _get_client()
        params = GetPositionTransactionPageParams(size=str(min(limit, 100)), offset_data="")
        resp = await client.account.get_position_transaction_page(params)
    except ImportError:
        return {"trades": [], "error": "pip install edgex-python-sdk 필요"}
    except Exception as e:
        return {"trades": [], "error": str(e)}
    if not resp or resp.get("code") != "SUCCESS":
        return {"trades": [], "error": resp.get("msg") or "get_position_transaction_page failed"}
    data_list = (resp.get("data") or {}).get("dataList") or []
    trades = []
    for row in data_list[:limit]:
        trades.append({
            "tx_type": row.get("type"),
            "time": row.get("createdTime"),
            "side": "Sell" if "SELL" in (row.get("type") or "") else "Buy",
            "size": row.get("fillCloseSize") or row.get("deltaOpenSize"),
            "price": row.get("fillPrice"),
            "realize_pnl": row.get("realizePnl"),
            "fee": row.get("fillCloseFee") or row.get("deltaOpenFee"),
        })
    return {"trades": trades, "count": len(trades), "source": "EdgeX API"}


def _parse_iso_time(ts: Optional[str]) -> str:
    """ms timestamp or ISO -> YYYY-MM-DD-HH-MM-SS."""
    if not ts:
        return ""
    try:
        if isinstance(ts, str) and ts.isdigit():
            ts = int(ts)
        if isinstance(ts, (int, float)):
            dt = datetime.utcfromtimestamp(ts / 1000.0 if ts > 1e12 else ts)
            return dt.strftime("%Y-%m-%d-%H-%M-%S")
        return str(ts)
    except Exception:
        return str(ts)


async def export_to_csv(usd_to_krw_rate: float = 1300.0) -> str:
    """Lighter와 동일 CSV 형식: 일시|거래소|유형|페어|통화|가격|원화가치|수수료(USD)|적용환율."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["일시", "거래소", "유형", "페어", "통화", "가격", "원화가치", "수수료(USD)", "적용환율"])
    rows = []
    dw = await get_deposits_withdrawals(limit=1000)
    for item in dw.get("items", []):
        if isinstance(item, dict):
            ts = item.get("time")
            date_str = _parse_iso_time(ts)
            typ = "입금" if item.get("type") == "deposit" else "출금"
            amount = item.get("amount")
            if amount:
                amt = float(amount)
                rows.append((date_str, "EdgeX", typ, "", item.get("asset_index", "USDC"), amt, amt * usd_to_krw_rate, 0.0, usd_to_krw_rate))
    tr = await get_trades(limit=1000)
    for t in tr.get("trades", []):
        if isinstance(t, dict) and t.get("price") and (t.get("size") or t.get("price")):
            size = float(t.get("size") or 0)
            price = float(t.get("price"))
            usd_val = size * price
            fee = float(t.get("fee") or 0)
            rows.append((
                _parse_iso_time(t.get("time")),
                "EdgeX",
                "매수" if t.get("side") == "Buy" else "매도",
                "",
                "",
                price,
                usd_val * usd_to_krw_rate,
                fee,
                usd_to_krw_rate,
            ))
    rows.sort(key=lambda x: x[0])
    for r in rows:
        writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], round(r[6], 2), round(r[7], 6), r[8]])
    return output.getvalue()


async def print_summary():
    """잔고 및 요약 출력."""
    print("=" * 50)
    print("📊 EdgeX 계정 요약")
    print("=" * 50)
    b = await get_balance()
    if "error" in b:
        print("잔고 오류:", b["error"])
        print("=" * 50)
        return
    print(f"\n💰 잔고: {b.get('collateral_usd')} USD")
    print(f"   총 자산 가치: {b.get('total_asset_value_usd')} USD")
    p = await get_pnl()
    if "error" not in p:
        print(f"\n📊 PNL: 미실현 {p.get('total_unrealized_pnl_usd')} USD, 실현 {p.get('total_realized_pnl_usd')} USD")
    print("\n" + "=" * 50)


if __name__ == "__main__":
    asyncio.run(print_summary())
