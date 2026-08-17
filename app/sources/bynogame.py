"""ByNoGame — gw.bynogame.com steam-products API.

CS2 ve Rust (app_id 252490) destekler. Fiyatlar TRY.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from ..itemname import ParsedItem, listing_matches_parsed
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
        matches = [
            it for it in items
            if listing_matches_parsed(it.get("marketHashName") or "", parsed)
        ]
        if not matches:
            res.error = "ilan bulunamadı"
            return res

        def _price(it):
            qty = it.get("listingCount") or 0
            price = it.get("priceMin")
            if qty <= 0 or not price:
                return None
            try:
                val = float(price)
            except (TypeError, ValueError):
                return None
            return val if val > 0 else None

        priced = [(it, _price(it)) for it in matches]
        priced = [(it, p) for it, p in priced if p is not None]
        if not priced:
            res.error = "satışta yok"
            return res
        match, price = min(priced, key=lambda x: x[1])

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


async def _ko_listings(
    client: httpx.AsyncClient,
    product_id: int,
) -> list[dict]:
    url = (
        f"{KO_LISTINGS_API}?page=1&limit=1000&sort=Price:1"
        f"&filters=Product:{product_id};OnlyInStock:true"
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
    listings = await _ko_listings(client, product_id)
    prices = [float(it["price"]) for it in listings if it.get("price")]
    return min(prices) if prices else None


def _ko_listing_ts(it: dict):
    import datetime as dt
    raw = (
        it.get("createdAt") or it.get("created_at") or it.get("updatedAt")
        or it.get("updated_at") or it.get("date")
    )
    if not raw:
        return dt.datetime.utcnow().replace(microsecond=0)
    s = str(raw).replace("Z", "").split(".")[0]
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return dt.datetime.utcnow().replace(microsecond=0)


async def ko_price_points(
    client: httpx.AsyncClient,
    name: str,
) -> list[tuple[str, float]]:
    """KO ürününün ByNoGame ilan fiyatları (tarihli, yoksa güncel min)."""
    from ..ko_item import parse_ko_item, bng_name_matches
    parsed = parse_ko_item(name)
    seen_ids: set[int] = set()
    points: list[tuple[str, float]] = []
    now = __import__("datetime").datetime.utcnow().replace(microsecond=0).isoformat()
    for qn in (parsed.base_name, parsed.keyword, name):
        if not qn:
            continue
        for item in await _search_ko_products(client, qn):
            title = item.get("displayName") or item.get("displayNameShort") or item.get("name") or ""
            if not bng_name_matches(parsed, title):
                continue
            pid = item.get("id")
            if pid is None or int(pid) in seen_ids:
                continue
            seen_ids.add(int(pid))
            listings = await _ko_listings(client, int(pid))
            priced = []
            for it in listings:
                try:
                    p = float(it["price"])
                except (TypeError, ValueError, KeyError):
                    continue
                if p <= 0:
                    continue
                ts = _ko_listing_ts(it).replace(microsecond=0).isoformat()
                priced.append((ts, round(p, 2)))
            if priced:
                points.extend(priced)
                continue
            pmin = item.get("priceMin") or item.get("price")
            try:
                val = float(pmin) if pmin else None
            except (TypeError, ValueError):
                val = None
            if val and val > 0:
                points.append((now, round(val, 2)))
    return points


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


async def list_steam_catalog(
    client: httpx.AsyncClient,
    *,
    app_id: int,
    page: int = 1,
    limit: int = 80,
    q: str = "",
) -> dict:
    """Sayfalı ByNoGame katalog — Skinport limitinde anlık liste için."""
    filters = f"AppId:{app_id}"
    if q.strip():
        filters += f";Name:{quote(q.strip(), safe='')}"
    url = (
        f"{API}?page={max(1, page)}&limit={min(max(1, limit), 100)}"
        f"&sort=MostSelling:-1&filters={filters}"
    )
    r = await client.get(url, headers=_HEADERS, timeout=20)
    r.raise_for_status()
    body = r.json()
    data = body.get("data") or {}
    rows = data.get("result") or []
    total = int(data.get("totalCount") or data.get("total") or len(rows))
    items = []
    for it in rows:
        name = it.get("marketHashName") or it.get("displayName") or ""
        if not name:
            continue
        price = it.get("priceMin") or it.get("price")
        try:
            price_try = float(price) if price else None
        except (TypeError, ValueError):
            price_try = None
        slug = it.get("slug") or ""
        path = "rust-skin" if app_id == 252490 else "cs2-skin"
        url_item = f"{BASE}/tr/oyunlar/{path}/{slug}" if slug else None
        items.append({
            "name": name,
            "price_try": price_try,
            "url": url_item,
            "quantity": it.get("listingCount") or 0,
        })
    return {"items": items, "total": total}