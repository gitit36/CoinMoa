#!/usr/bin/env python3
"""Build a local domestic asset catalog from Upbit, Bithumb, and CoinMarketCap."""

from __future__ import annotations

import json
import re
import ssl
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.request import Request, urlopen

UPBIT_MARKETS_URL = "https://api.upbit.com/v1/market/all?isDetails=false"
BITHUMB_MARKETS_URL = "https://api.bithumb.com/v1/market/all?isDetails=false"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
CMC_SEARCH_URL = "https://s2.coinmarketcap.com/generated/search/quick_search.json"
CMC_IMAGE_URL = "https://s2.coinmarketcap.com/static/img/coins/64x64/{id}.png"
CMC_LISTING_PAGE_URL = "https://coinmarketcap.com/?page={page}"

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "public" / "assets" / "domestic-asset-catalog.json"
OVERRIDES_PATH = ROOT / "data" / "asset_name_overrides.json"

SSL_CONTEXT = ssl.create_default_context()
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_json(url: str) -> Any:
    request = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(request, context=SSL_CONTEXT, timeout=30) as response:
        return json.load(response)


def fetch_text(url: str) -> str:
    request = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(request, context=SSL_CONTEXT, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def normalize_name(value: str) -> str:
    lowered = value.lower().strip()
    lowered = lowered.replace("&", "and")
    lowered = re.sub(r"\[[^\]]+\]", "", lowered)
    lowered = re.sub(r"[^a-z0-9가-힣]+", "", lowered)
    return lowered


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if not value:
            continue
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def clean_korean_name(value: str) -> str:
    cleaned = re.sub(r"\s*[\[(].*?[\])]\s*", "", value).strip()
    return re.sub(r"\s{2,}", " ", cleaned)


def safe_rank(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**9


def choose_cmc_entry(symbol: str, english_names: List[str], cmc_entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cmc_entries:
        return None

    normalized_names = {normalize_name(name) for name in english_names if name}

    exact_name_matches = [
        entry
        for entry in cmc_entries
        if normalize_name(str(entry.get("name", ""))) in normalized_names
        or normalize_name(str(entry.get("slug", ""))) in normalized_names
        or any(normalize_name(str(token)) in normalized_names for token in entry.get("tokens", []))
    ]
    if exact_name_matches:
        return sorted(exact_name_matches, key=lambda item: safe_rank(item.get("rank")))[0]

    ranked_entries = sorted(cmc_entries, key=lambda item: safe_rank(item.get("rank")))
    if len(ranked_entries) == 1:
        return ranked_entries[0]

    top_ranked = [entry for entry in ranked_entries if safe_rank(entry.get("rank")) <= 200]
    if top_ranked:
        ranked_entries = top_ranked

    # Prefer non-wrapped assets when symbol collisions happen.
    preferred = [
        entry
        for entry in ranked_entries
        if "wrapped" not in str(entry.get("name", "")).lower()
        and "bridged" not in str(entry.get("name", "")).lower()
    ]
    return preferred[0] if preferred else ranked_entries[0]


def apply_cmc_override(item: Dict[str, Any], override: Dict[str, Any]) -> None:
    if not any(key in override for key in ("cmc_id", "cmc_slug", "cmc_name", "cmc_rank", "image_url")):
        return

    existing_cmc = item.get("cmc") if isinstance(item.get("cmc"), dict) else {}
    override_cmc_id = override.get("cmc_id")
    existing_cmc_id = existing_cmc.get("id")

    cmc_id = int(override_cmc_id) if override_cmc_id else existing_cmc_id
    if cmc_id:
        item["cmc"] = {
            "id": cmc_id,
            "slug": override.get("cmc_slug") or (existing_cmc.get("slug") if existing_cmc_id == cmc_id else None),
            "name": override.get("cmc_name") or (existing_cmc.get("name") if existing_cmc_id == cmc_id else item["english_name"]),
            "rank": override["cmc_rank"] if "cmc_rank" in override else (existing_cmc.get("rank") if existing_cmc_id == cmc_id else None),
        }

    if override.get("image_url"):
        item["image_url"] = override["image_url"]
    elif cmc_id:
        item["image_url"] = CMC_IMAGE_URL.format(id=cmc_id)


def apply_cmc_entry(item: Dict[str, Any], cmc_entry: Dict[str, Any], *, is_top_200: bool = False) -> None:
    item["cmc"] = {
        "id": int(cmc_entry["id"]),
        "slug": cmc_entry.get("slug"),
        "name": cmc_entry.get("name"),
        "rank": cmc_entry.get("rank"),
    }
    item["image_url"] = CMC_IMAGE_URL.format(id=cmc_entry["id"])
    item["is_cmc_top_200"] = is_top_200


def fetch_cmc_top_200() -> List[Dict[str, Any]]:
    pattern = re.compile(
        r'\{"id":(?P<id>\d+),"name":"(?P<name>[^"]+)","symbol":"(?P<symbol>[^"]+)","slug":"(?P<slug>[^"]+)","cmcRank":(?P<rank>\d+)'
    )

    rows: List[Dict[str, Any]] = []
    seen_ids = set()
    for page in (1, 2):
        html = fetch_text(CMC_LISTING_PAGE_URL.format(page=page))
        for match in pattern.finditer(html):
            coin_id = int(match.group("id"))
            if coin_id in seen_ids:
                continue
            seen_ids.add(coin_id)
            rows.append(
                {
                    "id": coin_id,
                    "name": match.group("name"),
                    "symbol": match.group("symbol").upper(),
                    "slug": match.group("slug"),
                    "rank": int(match.group("rank")),
                    "tokens": [
                        match.group("name"),
                        match.group("slug"),
                        match.group("symbol").upper(),
                    ],
                }
            )
    return sorted(rows, key=lambda item: safe_rank(item.get("rank")))[:200]


def main() -> None:
    upbit_markets = fetch_json(UPBIT_MARKETS_URL)
    bithumb_markets = fetch_json(BITHUMB_MARKETS_URL)
    binance_exchange_info = fetch_json(BINANCE_EXCHANGE_INFO_URL)
    cmc_search = fetch_json(CMC_SEARCH_URL)
    cmc_top_200 = fetch_cmc_top_200()
    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8")) if OVERRIDES_PATH.exists() else {}

    cmc_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for entry in cmc_search:
        symbol = str(entry.get("symbol", "")).upper()
        if not symbol:
            continue
        cmc_by_symbol.setdefault(symbol, []).append(entry)

    cmc_top_by_symbol: Dict[str, Dict[str, Any]] = {}
    for entry in cmc_top_200:
        symbol = str(entry.get("symbol", "")).upper()
        if not symbol:
            continue
        existing = cmc_top_by_symbol.get(symbol)
        if existing is None or safe_rank(entry.get("rank")) < safe_rank(existing.get("rank")):
            cmc_top_by_symbol[symbol] = entry

    assets: Dict[str, Dict[str, Any]] = {}

    def upsert(symbol: str) -> Dict[str, Any]:
        return assets.setdefault(
            symbol,
            {
                "symbol": symbol,
                "display_name_ko": None,
                "english_name": None,
                "aliases": [],
                "exchanges": [],
                "upbit": {"markets": [], "korean_name": None, "english_name": None},
                "bithumb": {"markets": [], "korean_name": None, "english_name": None},
                "binance": {"markets": []},
                "cmc": None,
                "image_url": None,
                "preferred_source": None,
                "is_cmc_top_200": False,
            },
        )

    for market in upbit_markets:
        symbol = str(market["market"]).split("-")[-1].upper()
        item = upsert(symbol)
        item["upbit"]["markets"].append(market["market"])
        item["upbit"]["korean_name"] = market.get("korean_name") or item["upbit"]["korean_name"]
        item["upbit"]["english_name"] = market.get("english_name") or item["upbit"]["english_name"]
        item["exchanges"] = unique([*item["exchanges"], "upbit"])
        item["aliases"] = unique(
            [
                *item["aliases"],
                symbol,
                str(market.get("korean_name", "")),
                str(market.get("english_name", "")),
            ]
        )

    for market in bithumb_markets:
        symbol = str(market["market"]).split("-")[-1].upper()
        item = upsert(symbol)
        item["bithumb"]["markets"].append(market["market"])
        item["bithumb"]["korean_name"] = market.get("korean_name") or item["bithumb"]["korean_name"]
        item["bithumb"]["english_name"] = market.get("english_name") or item["bithumb"]["english_name"]
        item["exchanges"] = unique([*item["exchanges"], "bithumb"])
        item["aliases"] = unique(
            [
                *item["aliases"],
                symbol,
                str(market.get("korean_name", "")),
                str(market.get("english_name", "")),
            ]
        )

    for market in binance_exchange_info.get("symbols", []):
        base_asset = str(market.get("baseAsset", "")).upper()
        symbol = str(market.get("symbol", "")).upper()
        if not base_asset or not symbol:
            continue
        item = upsert(base_asset)
        item["binance"]["markets"].append(symbol)
        item["exchanges"] = unique([*item["exchanges"], "binance"])
        item["aliases"] = unique([*item["aliases"], base_asset])

    for entry in cmc_top_200:
        symbol = str(entry.get("symbol", "")).upper()
        if not symbol:
            continue

        item = upsert(symbol)
        if not item["english_name"]:
            item["english_name"] = str(entry.get("name") or symbol)
        item["aliases"] = unique(
            [
                *item["aliases"],
                symbol,
                str(entry.get("name", "")),
                str(entry.get("slug", "")),
                *[str(token) for token in entry.get("tokens", [])],
            ]
        )
        apply_cmc_entry(item, entry, is_top_200=True)

    for symbol, item in assets.items():
        english_names = unique(
            [
                str(item["upbit"].get("english_name") or ""),
                str(item["bithumb"].get("english_name") or ""),
                str(item.get("english_name") or ""),
                str((item.get("cmc") or {}).get("name") or ""),
            ]
        )
        ko_names = unique(
            [
                clean_korean_name(str(item["upbit"].get("korean_name") or "")),
                clean_korean_name(str(item["bithumb"].get("korean_name") or "")),
            ]
        )
        item["display_name_ko"] = ko_names[0] if ko_names else symbol
        item["english_name"] = english_names[0] if english_names else symbol
        item["aliases"] = unique([*item["aliases"], *ko_names, *english_names])

        cmc_entry = cmc_top_by_symbol.get(symbol) or choose_cmc_entry(symbol, english_names, cmc_by_symbol.get(symbol, []))
        if cmc_entry:
            apply_cmc_entry(item, cmc_entry, is_top_200=symbol in cmc_top_by_symbol)

        override = overrides.get(symbol)
        if override:
            if override.get("display_name_ko"):
                item["display_name_ko"] = override["display_name_ko"]
            if override.get("aliases"):
                item["aliases"] = unique([*item["aliases"], *override["aliases"]])
            if override.get("upbit", {}).get("korean_name"):
                item["upbit"]["korean_name"] = override["upbit"]["korean_name"]
            if override.get("bithumb", {}).get("korean_name"):
                item["bithumb"]["korean_name"] = override["bithumb"]["korean_name"]
            apply_cmc_override(item, override)

        if item["upbit"]["markets"]:
            item["preferred_source"] = "upbit"
        elif item["bithumb"]["markets"]:
            item["preferred_source"] = "bithumb"
        elif item["binance"]["markets"]:
            item["preferred_source"] = "binance"
        elif item["is_cmc_top_200"]:
            item["preferred_source"] = "cmc_top_200"
        elif item.get("cmc"):
            item["preferred_source"] = "cmc"
        else:
            item["preferred_source"] = "symbol_only"

    output = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "sources": {
            "upbit": UPBIT_MARKETS_URL,
            "bithumb": BITHUMB_MARKETS_URL,
            "binance": BINANCE_EXCHANGE_INFO_URL,
            "coinmarketcap": CMC_SEARCH_URL,
            "coinmarketcap_top_200": [CMC_LISTING_PAGE_URL.format(page=1), CMC_LISTING_PAGE_URL.format(page=2)],
        },
        "assets": dict(sorted(assets.items())),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(assets)} assets to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
