"""CSFloat — halka açık fiyat listesi API.

GET /api/v1/listings/price-list → [{market_hash_name, quantity, min_price}]
min_price USD cent cinsinden. Tekil arama oturum gerektirir; tüm liste önbellekte tutulur.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx

from .. import catalog_cache as cache
from ..itemname import ParsedItem, pick_catalog_row
from .base import PriceResult

CACHE_KEY = "csfloat:cs2"
TTL = 300
_COOLDOWN = 300


async def _get_items(client: httpx.AsyncClient) -> dict:
    now = time.time()
    entry = await cache.get(CACHE_KEY)
    if entry and entry.fresh(TTL, now):
        return entry.items
    if entry and entry.in_cooldown(now):
        return entry.items

    async with cache.lock(CACHE_KEY):
        now = time.time()
        entry = await cache.get(CACHE_KEY)
        if entry and entry.fresh(TTL, now):
            return entry.items
        if entry and entry.in_cooldown(now):
            return entry.items

        try:
            r = await client.get(
                "https://csfloat.com/api/v1/listings/price-list",
                timeout=20,
            )
            if r.status_code == 429:
                raise httpx.HTTPStatusError("rate limit", request=r.request, response=r)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                raise ValueError("beklenmeyen CSFloat yanıtı")
            items = {it["market_hash_name"]: it for it in data}
            await cache.put(CACHE_KEY, items, TTL)
            return items
        except httpx.HTTPStatusError:
            if entry and entry.items:
                await cache.set_cooldown(CACHE_KEY, _COOLDOWN)
                return entry.items
            raise


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="csfloat", currency="USD")
    try:
        items = await _get_items(client)
        name, it = pick_catalog_row(items, parsed)
        if not it:
            res.error = "item bulunamadı"
            return res
        qty = it.get("quantity") or 0
        min_price = it.get("min_price")
        if qty <= 0 or min_price is None:
            res.error = "satışta yok"
            return res
        res.price = min_price / 100.0
        res.url = (
            "https://csfloat.com/search?market_hash_name="
            + quote(name or parsed.full_name)
        )
    except httpx.HTTPStatusError:
        res.error = "CSFloat istek limiti — birkaç dakika sonra tekrar dene"
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res
