"""rust.tm — halka açık fiyat listesi API.

GET /api/v2/prices/USD.json → {items: [{market_hash_name, volume, price}]}
price USD string. Liste süreç içinde önbellekte tutulur.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx

from .. import catalog_cache as cache
from ..itemname import ParsedItem
from .base import PriceResult

CACHE_KEY = "rust_tm:usd"
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
                "https://rust.tm/api/v2/prices/USD.json",
                timeout=90,
            )
            if r.status_code == 429:
                raise httpx.HTTPStatusError("rate limit", request=r.request, response=r)
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise ValueError("rust.tm API hatası")
            raw = data.get("items") or []
            items = {}
            for it in raw:
                name = it.get("market_hash_name")
                if not name:
                    continue
                try:
                    vol = int(it.get("volume") or 0)
                except (TypeError, ValueError):
                    vol = 0
                try:
                    price = float(it.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0
                items[name] = {"quantity": vol, "min_price": price}
            await cache.put(CACHE_KEY, items, TTL)
            return items
        except httpx.HTTPStatusError:
            if entry and entry.items:
                await cache.set_cooldown(CACHE_KEY, _COOLDOWN)
                return entry.items
            raise


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="rust_tm", currency="USD")
    try:
        items = await _get_items(client)
        it = items.get(parsed.full_name)
        if not it:
            res.error = "item bulunamadı"
            return res
        qty = it.get("quantity") or 0
        min_price = it.get("min_price")
        if qty <= 0 or min_price is None or min_price <= 0:
            res.error = "satışta yok"
            return res
        res.price = min_price
        res.url = (
            "https://rust.tm/?search="
            + quote(parsed.full_name)
        )
    except httpx.HTTPStatusError:
        res.error = "rust.tm istek limiti — birkaç dakika sonra tekrar dene"
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res
