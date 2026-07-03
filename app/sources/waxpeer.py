"""Waxpeer — halka açık fiyat listesi API.

GET /v1/prices?game=rust → {items: [{name, count, min}]}
min değeri USD'nin binde biri (1000 = 1 USD). Liste önbellekte tutulur.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx

from .. import catalog_cache as cache
from ..itemname import ParsedItem
from .base import PriceResult

CACHE_KEY = "waxpeer:rust"
TTL = 300


async def _get_items(client: httpx.AsyncClient) -> dict:
    now = time.time()
    entry = await cache.get(CACHE_KEY)
    if entry and entry.fresh(TTL, now):
        return entry.items

    async with cache.lock(CACHE_KEY):
        now = time.time()
        entry = await cache.get(CACHE_KEY)
        if entry and entry.fresh(TTL, now):
            return entry.items

        r = await client.get(
            "https://api.waxpeer.com/v1/prices",
            params={"game": "rust"},
            timeout=90,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise ValueError("Waxpeer API hatası")
        items = {}
        for it in data.get("items") or []:
            name = it.get("name")
            if not name:
                continue
            try:
                qty = int(it.get("count") or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = int(it.get("min") or 0) / 1000.0
            except (TypeError, ValueError):
                price = 0
            items[name] = {"quantity": qty, "min_price": price}
        await cache.put(CACHE_KEY, items, TTL)
        return items


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="waxpeer", currency="USD")
    try:
        items = await _get_items(client)
        it = items.get(parsed.full_name)
        if not it:
            res.error = "item bulunamadı"
            return res
        qty = it.get("quantity") or 0
        min_price = it.get("min_price")
        if qty <= 0 or not min_price or min_price <= 0:
            res.error = "satışta yok"
            return res
        res.price = min_price
        res.url = "https://waxpeer.com/rust?search=" + quote(parsed.full_name)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res
