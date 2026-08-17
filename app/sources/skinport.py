"""Skinport — resmi halka açık API.

Tüm item listesi tek istekte gelir (Brotli zorunlu, ~5 dk sunucu önbelleği).
Rate limit sıkıdır (8 istek / 5 dk); liste süreç içinde önbellekte tutulur.
CS2 app_id=730, Rust app_id=252490 — ayrı önbellek.
"""
from __future__ import annotations

import time

import httpx

from .. import catalog_cache as cache
from ..itemname import ParsedItem, pick_catalog_row
from .base import PriceResult, attach_top_offers

CS2_APP_ID = 730
RUST_APP_ID = 252490
TTL = 300
_COOLDOWN = 300


class SkinportRateLimited(Exception):
    """Skinport API istek limiti aşıldı."""


def _key(app_id: int) -> str:
    return f"skinport:{app_id}"


def _parse_items(data) -> dict:
    if isinstance(data, dict) and data.get("errors"):
        err = data["errors"][0] if data["errors"] else {}
        if err.get("id") == "rate_limit_exceeded":
            raise SkinportRateLimited(err.get("message", "rate limit"))
        raise ValueError(err.get("message", "Skinport API hatası"))
    if not isinstance(data, list):
        raise ValueError("beklenmeyen Skinport yanıtı")
    return {it["market_hash_name"]: it for it in data}


async def _get_items(
    client: httpx.AsyncClient,
    app_id: int = CS2_APP_ID,
    currency: str = "TRY",
) -> dict:
    key = _key(app_id)
    now = time.time()
    entry = await cache.get(key)
    if entry and entry.fresh(TTL, now):
        return entry.items
    if entry and entry.in_cooldown(now):
        return entry.items

    async with cache.lock(key):
        now = time.time()
        entry = await cache.get(key)
        if entry and entry.fresh(TTL, now):
            return entry.items
        if entry and entry.in_cooldown(now):
            return entry.items

        try:
            r = await client.get(
                "https://api.skinport.com/v1/items",
                params={"app_id": app_id, "currency": currency},
                headers={"Accept-Encoding": "br"},
                timeout=20,
            )
            if r.status_code == 429:
                raise SkinportRateLimited()
            r.raise_for_status()
            items = _parse_items(r.json())
            await cache.put(key, items, TTL)
            return items
        except (httpx.HTTPStatusError, SkinportRateLimited):
            if entry and entry.items:
                await cache.set_cooldown(key, _COOLDOWN)
                return entry.items
            raise


async def _fetch(
    client: httpx.AsyncClient,
    parsed: ParsedItem,
    app_id: int = CS2_APP_ID,
) -> PriceResult:
    res = PriceResult(source="skinport", currency="TRY")
    try:
        items = await _get_items(client, app_id=app_id)
        name, it = pick_catalog_row(items, parsed)
        if not it:
            res.error = "item bulunamadı"
            return res
        res.url = it.get("item_page")
        qty = it.get("quantity") or 0
        min_price = it.get("min_price")
        if qty <= 0 or min_price is None:
            res.error = "satışta yok"
            return res
        res.price = min_price
        attach_top_offers(res, [(float(min_price), res.url)])
        if name and name != parsed.full_name:
            res.url = it.get("item_page")
            if res.offers:
                res.offers[0]["url"] = res.url
    except (httpx.HTTPStatusError, SkinportRateLimited):
        res.error = "Skinport istek limiti — birkaç dakika sonra tekrar dene"
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, app_id=CS2_APP_ID)


async def fetch_rust(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, app_id=RUST_APP_ID)
