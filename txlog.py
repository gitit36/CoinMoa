"""
Transaction Log Viewer — query deposits, withdrawals, buys, and sells
from Upbit or Bithumb with date filtering.

Usage:
    python txlog.py <exchange> <start_date> <end_date> <type>

    exchange:   upbit | bithumb
    start_date: YYYY-MM-DD
    end_date:   YYYY-MM-DD
    type:       deposit | withdrawal | buy | sell

Examples:
    python txlog.py upbit 2024-01-01 2024-12-31 deposit
    python txlog.py bithumb 2025-01-01 2025-06-30 sell
"""

import sys
import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from upbit_client import UpbitClient
from bithumb_client import BithumbClient

logging.basicConfig(level=logging.WARNING)
KST = timezone(timedelta(hours=9))

EXCHANGES = {
    "upbit": ("Upbit", UpbitClient),
    "bithumb": ("Bithumb", BithumbClient),
}


# ── USD/KRW historical rates ─────────────────────────────────
class FxRates:
    """Fetches and caches historical USD/KRW rates per date."""

    FALLBACK = 1450.0

    def __init__(self):
        self._cache = {}

    def preload(self, start_date, end_date):
        """Batch-fetch rates for a date range from frankfurter.dev."""
        try:
            url = f"https://api.frankfurter.dev/v1/{start_date}..{end_date}?base=USD&symbols=KRW"
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                rates = data.get("rates", {})
                for date_str, rate_dict in rates.items():
                    self._cache[date_str] = rate_dict.get("KRW", self.FALLBACK)
                print(f"  💱 USD/KRW 환율 {len(self._cache)}일치 로드 완료")
                return
        except Exception as e:
            print(f"  ⚠️  환율 로드 실패: {e}")
        print(f"  💱 Fallback rate: {self.FALLBACK:,.0f} ₩/$")

    def get(self, date_str):
        """Get rate for a specific date (YYYY-MM-DD). Nearest prior date if exact not found."""
        if date_str in self._cache:
            return self._cache[date_str]
        available = sorted(self._cache.keys())
        for d in reversed(available):
            if d <= date_str:
                return self._cache[d]
        if available:
            return self._cache[available[0]]
        return self.FALLBACK


# ── Crypto price lookup ──────────────────────────────────────
class CryptoPrice:
    """Gets historical KRW price for a crypto at a given date via candle API."""

    def __init__(self, client):
        self.client = client
        self._cache = {}  # (market, date) -> price

    def get_krw(self, currency, date_str):
        """Get KRW price of a crypto on a given date. Returns 0 if not found."""
        if currency == "KRW":
            return 1.0
        market = f"KRW-{currency}"
        key = (market, date_str)
        if key in self._cache:
            return self._cache[key]

        # Fetch daily candle for that date
        try:
            # Add 1 day to 'to' so the candle covers the target date
            to_dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
            to_str = to_dt.strftime("%Y-%m-%dT00:00:00")
            r = self.client.get("/v1/candles/days", {
                "market": market,
                "to": to_str,
                "count": 1,
            })
            if isinstance(r, list) and r:
                price = float(r[0].get("trade_price", 0))
                self._cache[key] = price
                return price
        except Exception:
            pass
        self._cache[key] = 0
        return 0


# ── Date-filtered data fetchers ──────────────────────────────

def fetch_deposits_in_range(client, exchange_key, dt_start, dt_end):
    """Fetch only deposits within the date range. Paginates descending, stops early."""
    paths = ["/v1/deposits"]
    if exchange_key == "bithumb":
        paths = ["/v1/deposits/krw", "/v1/deposits"]

    accepted_states = ("ACCEPTED", "DEPOSIT_ACCEPTED")
    results = []

    for path in paths:
        page = 1
        while True:
            data = client.get(path, {"limit": 100, "page": page, "order_by": "desc"})
            if isinstance(data, dict) and "status_code" in data:
                # API error (e.g. 404 for unsupported path) — skip this path
                break
            if not isinstance(data, list) or not data:
                break
            stopped_early = False
            for d in data:
                dt = datetime.fromisoformat(d["created_at"])
                if dt > dt_end:
                    continue  # too new, skip
                if dt < dt_start:
                    stopped_early = True
                    break  # too old, done with this page set
                if d.get("state") in accepted_states:
                    results.append(d)
            if stopped_early or len(data) < 100:
                break
            page += 1

    results.sort(key=lambda d: d["created_at"])
    return results


def fetch_withdrawals_in_range(client, exchange_key, dt_start, dt_end):
    """Fetch only withdrawals within the date range. Paginates descending, stops early."""
    paths = ["/v1/withdraws"]
    if exchange_key == "bithumb":
        paths = ["/v1/withdraws/krw", "/v1/withdraws"]

    results = []

    for path in paths:
        page = 1
        while True:
            data = client.get(path, {"limit": 100, "page": page, "order_by": "desc"})
            if isinstance(data, dict) and "status_code" in data:
                break
            if not isinstance(data, list) or not data:
                break
            stopped_early = False
            for w in data:
                dt = datetime.fromisoformat(w["created_at"])
                if dt > dt_end:
                    continue
                if dt < dt_start:
                    stopped_early = True
                    break
                if w.get("state") == "DONE":
                    results.append(w)
            if stopped_early or len(data) < 100:
                break
            page += 1

    results.sort(key=lambda w: w["created_at"])
    return results


def fetch_orders_in_range_upbit(client, start_date, end_date, side):
    """Upbit: efficiently fetch only orders in the date range via /v1/orders/closed."""
    all_orders = []
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=KST)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=KST) + timedelta(days=1)
    now = datetime.now(KST)
    end = min(end, now)
    total_windows = max(1, int((end - start).days / 7) + 1)
    window_num = 0
    while start < end:
        window_end = min(start + timedelta(days=7), end)
        window_num += 1
        print(
            f"\r  📅 주문 조회 중... {start.strftime('%Y-%m-%d')} ~ "
            f"{window_end.strftime('%Y-%m-%d')}  ({window_num}/{total_windows})",
            end="", flush=True,
        )
        start_utc = start - timedelta(hours=9)
        end_utc = window_end - timedelta(hours=9)
        params = [
            ("states[]", "done"),
            ("states[]", "cancel"),
            ("start_time", start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")),
            ("end_time", end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")),
            ("limit", 1000),
            ("order_by", "asc"),
        ]
        data = client.get("/v1/orders/closed", params=params)
        if isinstance(data, list):
            for o in data:
                if o.get("side") == side and float(o.get("executed_volume", 0)) > 0:
                    all_orders.append(o)
        start = window_end
    print()
    return all_orders


def fetch_orders_in_range_bithumb(client, dt_start, dt_end, side):
    """Bithumb: paginate ascending, skip detail for out-of-range, stop when past end."""
    in_range = []
    page = 1
    total_scanned = 0
    reached_range = False

    while True:
        print(f"\r  📅 주문 조회 중... 페이지 {page}", end="", flush=True)
        params = [
            ("states[]", "done"),
            ("states[]", "cancel"),
            ("limit", 100),
            ("page", page),
            ("order_by", "asc"),
        ]
        data = client.get("/v1/orders", params=params)
        if not isinstance(data, list) or not data:
            break

        past_end = False
        for o in data:
            total_scanned += 1
            dt = datetime.fromisoformat(o["created_at"])
            if dt < dt_start:
                continue  # before range, skip
            if dt > dt_end:
                past_end = True
                break  # past range, done
            reached_range = True
            if o.get("side") == side and float(o.get("executed_volume", 0)) > 0:
                in_range.append(o)

        if past_end or len(data) < 100:
            break
        page += 1

    print(f"\r  📅 주문 {total_scanned}건 스캔 → {len(in_range)}건 해당")

    # Compute executed_funds ONLY for matched orders
    needs_detail = []
    for i, o in enumerate(in_range):
        ord_type = o.get("ord_type")
        exec_vol = float(o.get("executed_volume") or 0)
        if ord_type == "limit":
            o["executed_funds"] = float(o.get("price", 0)) * exec_vol
        else:
            needs_detail.append(i)

    if needs_detail:
        total = len(needs_detail)
        print(f"  📦 {total}건 주문 상세 조회 중...")
        for idx, i in enumerate(needs_detail):
            if (idx + 1) % 50 == 0 or idx == 0:
                print(f"\r  📦 주문 상세 조회 중... ({idx+1}/{total})", end="", flush=True)
            o = in_range[i]
            detail = client.get("/v1/order", {"uuid": o["uuid"]})
            if isinstance(detail, dict) and "trades" in detail:
                funds = sum(float(t.get("funds", 0)) for t in detail["trades"])
                o["executed_funds"] = funds
            else:
                price = float(o.get("price", 0))
                exec_vol = float(o.get("executed_volume", 0))
                o["executed_funds"] = price if o.get("ord_type") == "price" else price * exec_vol
        print()

    return in_range


# ── Formatting ───────────────────────────────────────────────
def fmt_krw(v):
    return f"{v:,.0f}"


def fmt_amount(v, currency):
    if currency == "KRW":
        return f"{v:,.0f} KRW"
    return f"{v:,.8f} {currency}".rstrip("0").rstrip(".")


def print_sep():
    print("─" * 110)


def print_header(label):
    print()
    print("═" * 110)
    print(f"  {label}")
    print("═" * 110)


# ── Main ─────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    exchange_key = sys.argv[1].lower()
    start_date = sys.argv[2]
    end_date = sys.argv[3]
    tx_type = sys.argv[4].lower()

    if exchange_key not in EXCHANGES:
        print(f"  ❌ Unknown exchange: {exchange_key}")
        print(f"  Available: {', '.join(EXCHANGES.keys())}")
        sys.exit(1)

    valid_types = ("deposit", "withdrawal", "buy", "sell")
    if tx_type not in valid_types:
        print(f"  ❌ Unknown type: {tx_type}")
        print(f"  Available: {', '.join(valid_types)}")
        sys.exit(1)

    try:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=KST)
        dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=KST) + timedelta(days=1)
    except ValueError:
        print("  ❌ Invalid date format. Use YYYY-MM-DD")
        sys.exit(1)

    exchange_name, ClientClass = EXCHANGES[exchange_key]
    client = ClientClass()
    cp = CryptoPrice(client)

    print(f"\n  🏦 {exchange_name} | {start_date} ~ {end_date} | {tx_type}")
    print(f"  📡 데이터 수집 중...\n")

    fx = FxRates()
    fx.preload(start_date, end_date)
    print()

    # ── DEPOSIT ──────────────────────────────────────────────
    if tx_type == "deposit":
        print("  📥 입금 내역 조회 중...")
        records = fetch_deposits_in_range(client, exchange_key, dt_start, dt_end)

        print_header(f"📥 {exchange_name} 입금 내역  ({start_date} ~ {end_date})  |  {len(records)}건")
        total_krw = 0
        total_usd = 0
        for i, d in enumerate(records, 1):
            currency = d.get("currency", "?")
            amount = float(d.get("amount", 0))
            fee = float(d.get("fee", 0))
            txid = d.get("txid", "-")
            date = d["created_at"][:19].replace("T", " ")
            tx_date = d["created_at"][:10]
            net_type = d.get("net_type", "")
            rate = fx.get(tx_date)

            if currency == "KRW":
                krw_val = amount
            else:
                unit_price = cp.get_krw(currency, tx_date)
                krw_val = amount * unit_price

            usd_val = krw_val / rate if rate else 0
            total_krw += krw_val
            total_usd += usd_val

            print(f"  {i:>4}. [{date}]  {currency}" + (f" ({net_type})" if net_type else ""))
            print(f"        Amount : {fmt_amount(amount, currency)}" + (f"  (fee: {fmt_amount(fee, currency)})" if fee else ""))
            if currency != "KRW":
                unit_price = cp.get_krw(currency, tx_date)
                print(f"        Price  : {fmt_krw(unit_price)} ₩/{currency}")
            print(f"        KRW    : {fmt_krw(krw_val)} ₩")
            print(f"        USD    : ${usd_val:,.2f}  (rate: {rate:,.0f} ₩/$)")
            print(f"        TXID   : {txid}")
            print_sep()

        print(f"\n  📊 합계: {len(records)}건")
        print(f"     합계: {fmt_krw(total_krw)} ₩  (${total_usd:,.2f})")

    # ── WITHDRAWAL ───────────────────────────────────────────
    elif tx_type == "withdrawal":
        print("  📤 출금 내역 조회 중...")
        records = fetch_withdrawals_in_range(client, exchange_key, dt_start, dt_end)

        print_header(f"📤 {exchange_name} 출금 내역  ({start_date} ~ {end_date})  |  {len(records)}건")
        total_krw = 0
        total_usd = 0
        for i, w in enumerate(records, 1):
            currency = w.get("currency", "?")
            amount = float(w.get("amount", 0))
            fee = float(w.get("fee", 0))
            txid = w.get("txid", "-")
            date = w["created_at"][:19].replace("T", " ")
            tx_date = w["created_at"][:10]
            net_type = w.get("net_type", "")
            rate = fx.get(tx_date)

            if currency == "KRW":
                krw_val = amount + fee
            else:
                unit_price = cp.get_krw(currency, tx_date)
                krw_val = (amount + fee) * unit_price

            usd_val = krw_val / rate if rate else 0
            total_krw += krw_val
            total_usd += usd_val

            print(f"  {i:>4}. [{date}]  {currency}" + (f" ({net_type})" if net_type else ""))
            print(f"        Amount : {fmt_amount(amount, currency)}" + (f"  (fee: {fmt_amount(fee, currency)})" if fee else ""))
            if currency != "KRW":
                print(f"        Price  : {fmt_krw(unit_price)} ₩/{currency}")
            print(f"        KRW    : {fmt_krw(krw_val)} ₩" + (" (수수료 포함)" if fee else ""))
            print(f"        USD    : ${usd_val:,.2f}  (rate: {rate:,.0f} ₩/$)")
            print(f"        TXID   : {txid}")
            print_sep()

        print(f"\n  📊 합계: {len(records)}건")
        print(f"     합계: {fmt_krw(total_krw)} ₩  (${total_usd:,.2f})")

    # ── BUY / SELL ───────────────────────────────────────────
    elif tx_type in ("buy", "sell"):
        target_side = "bid" if tx_type == "buy" else "ask"
        label = "매수" if tx_type == "buy" else "매도"
        emoji = "🟢" if tx_type == "buy" else "🔴"

        print(f"  {emoji} {label} 내역 조회 중...")
        if exchange_key == "upbit":
            records = fetch_orders_in_range_upbit(client, start_date, end_date, target_side)
        else:
            records = fetch_orders_in_range_bithumb(client, dt_start, dt_end, target_side)

        records.sort(key=lambda o: o["created_at"])

        print_header(f"{emoji} {exchange_name} {label} 내역  ({start_date} ~ {end_date})  |  {len(records)}건")
        total_krw = 0
        total_usd = 0
        for i, o in enumerate(records, 1):
            market = o.get("market", "")
            parts = market.split("-")
            if len(parts) != 2:
                continue
            quote, coin = parts
            exec_vol = float(o.get("executed_volume") or 0)
            exec_funds = float(o.get("executed_funds") or 0)
            paid_fee = float(o.get("paid_fee") or 0)
            ord_type = o.get("ord_type", "?")
            date = o["created_at"][:19].replace("T", " ")
            tx_date = o["created_at"][:10]
            uuid = o.get("uuid", "-")
            rate = fx.get(tx_date)

            if target_side == "bid":
                krw_val = exec_funds + paid_fee
            else:
                krw_val = exec_funds - paid_fee

            usd_val = krw_val / rate if quote == "KRW" and rate else 0
            avg_price = exec_funds / exec_vol if exec_vol else 0
            total_krw += krw_val
            total_usd += usd_val

            print(f"  {i:>4}. [{date}]  {coin} ({ord_type})")
            print(f"        Volume : {exec_vol:,.8f} {coin}".rstrip("0").rstrip("."))
            print(f"        Price  : {fmt_krw(avg_price)} ₩/{coin}")
            print(f"        KRW    : {fmt_krw(krw_val)} ₩  (수수료: {fmt_krw(paid_fee)} ₩)")
            if quote == "KRW":
                print(f"        USD    : ${usd_val:,.2f}  (rate: {rate:,.0f} ₩/$)")
            print(f"        UUID   : {uuid}")
            print_sep()

        print(f"\n  📊 합계: {len(records)}건")
        print(f"     {label} 합계: {fmt_krw(total_krw)} ₩  (${total_usd:,.2f})")

    print()


if __name__ == "__main__":
    main()
