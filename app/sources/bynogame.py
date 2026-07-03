"""ByNoGame — gw.bynogame.com steam-products API.

CS2 ve Rust (app_id 252490) destekler. Fiyatlar TRY.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from ..itemname import ParsedItem
from ..ko_item import bng_name_matches
from .base import PriceResult, USER_AGENT
API = "https://gw.bynogame.com/steam-products/v2/products"
KO_PRODUCTS_API = "https://gw.bynogame.com/knight-items/v2/products"
KO_LISTINGS_API = "https://gw.bynogame.com/knight-item-listings/v2/listings"
BASE = "https://www.bynogame.com"
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Origin": BASE,
    "Referer": BASE + "/",
}


def _filter_names(parsed: ParsedItem, *, rust: bool = False) -> str:
    base = parsed.base_name
    if rust:
        return parsed.full_name
    if parsed.knife:
        normal = f"★ {base}"
        st = f"★ StatTrak™ {base}"
    else:
        normal = base
        st = f"StatTrak™ {base}"
    if parsed.stattrak:
        return st
    return f"{normal},{st}"


async def _fetch(
    client: httpx.AsyncClient,
    parsed: ParsedItem,
    *,
    path: str,
) -> PriceResult:
    res = PriceResult(source="bynogame", currency="TRY")
    rust = path == "rust-skin"
    try:
        names = _filter_names(parsed, rust=rust)
        url = f"{API}?filters=MarketHashNameShort:{quote(names, safe='')}"
        r = await client.get(url, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        body = r.json()
        if not body.get("success"):
            res.error = body.get("message", "API hatası")[:200]
            return res

        items = body.get("data", {}).get("result", [])
        match = next((it for it in items if it.get("marketHashName") == parsed.full_name), None)
        if not match:
            res.error = "ilan bulunamadı"
            return res

        qty = match.get("listingCount") or 0
        price = match.get("priceMin")
        if qty <= 0 or not price or float(price) <= 0:
            res.error = "satışta yok"
            return res

        slug = match.get("slug", "")
        lid = match.get("cheapestListingId")
        if slug and lid:
            res.url = f"{BASE}/tr/oyunlar/{path}/{slug}?id={lid}"
        elif slug:
            res.url = f"{BASE}/tr/oyunlar/{path}/{slug}"
        res.price = float(price)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, path="cs2-skin")


async def fetch_rust(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, path="rust-skin")


async def _search_ko_products(
    client: httpx.AsyncClient,
    name: str,
) -> list[dict]:
    url = (
        f"{KO_PRODUCTS_API}?page=1&limit=48&sort=MostSelling:-1"
        f"&filters=OnlyInStock:true;Name:{quote(name, safe='')}"
    )
    r = await client.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    body = r.json()
    if not body.get("success"):
        return []
    return body.get("data", {}).get("result") or []


async def _ko_min_listing_price(
    client: httpx.AsyncClient,
    product_id: int,
) -> float | None:
    url = (
        f"{KO_LISTINGS_API}?page=1&limit=1000&sort=Price:1"
        f"&filters=Product:{product_id};OnlyInStock:true"
    )
    r = await client.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    body = r.json()
    if not body.get("success"):
        return None
    listings = body.get("data", {}).get("result") or []
    prices = [float(it["price"]) for it in listings if it.get("price")]
    return min(prices) if prices else None


async def fetch_ko(client: httpx.AsyncClient, parsed) -> PriceResult:
    """Knight Online item — gw.bynogame.com knight-items API + listings."""
    res = PriceResult(source="bynogame", currency="TRY")
    search_url = (
        f"{BASE}/tr/oyunlar/knight-online/item?searchText={quote(parsed.keyword)}"
    )
    try:
        seen_ids: set[int] = set()
        products: list[dict] = []
        for name in (parsed.base_name, parsed.keyword):
            for item in await _search_ko_products(client, name):
                pid = item.get("id")
                if pid is None or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                products.append(item)

        matches: list[tuple[float, str, str]] = []
        for item in products:
            title = item.get("displayName") or item.get("displayNameShort") or item.get("name") or ""
            if not bng_name_matches(parsed, title):
                continue
            pid = item.get("id")
            slug = item.get("slug") or ""
            if pid is None or not slug:
                continue
            price = await _ko_min_listing_price(client, int(pid))
            if price is None or price <= 0:
                continue
            matches.append((price, f"{BASE}/tr/oyunlar/knight-online/{slug}", search_url))

        if not matches:
            res.error = "ilan bulunamadı"
            res.url = search_url
            return res
        res.price, res.url, _ = min(matches, key=lambda x: x[0])
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
        res.url = search_url
    return res