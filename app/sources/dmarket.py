"""DMarket — halka açık market API'si. Fiyatlar USD cent olarak döner."""
from __future__ import annotations
from urllib.parse import quote

import httpx
from ..itemname import ParsedItem
from .base import PriceResult

API = "https://api.dmarket.com/exchange/v1/market/items"
CS2_GAME_ID = "a8db"
RUST_GAME_ID = "rust"


async def _fetch(
    client: httpx.AsyncClient,
    parsed: ParsedItem,
    game_id: str,
    url_base: str,
) -> PriceResult:
    res = PriceResult(source="dmarket", currency="USD")
    try:
        r = await client.get(
            API,
            params={
                "gameId": game_id,
                "title": parsed.full_name,
                "limit": 20,
                "currency": "USD",
                "orderBy": "price",
                "orderDir": "asc",
            },
            timeout=30,
        )
        r.raise_for_status()
        objects = r.json().get("objects", [])
        prices = []
        for o in objects:
            if o.get("title") != parsed.full_name:
                continue
            p = o.get("price", {}).get("USD")
            if p is not None:
                prices.append(int(p) / 100.0)
        if not prices:
            res.error = "ilan bulunamadı"
            return res
        res.price = min(prices)
        res.url = url_base + quote(parsed.full_name)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(
        client,
        parsed,
        CS2_GAME_ID,
        "https://dmarket.com/ingame-items/item-list/csgo-skins?title=",
    )


async def fetch_rust(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(
        client,
        parsed,
        RUST_GAME_ID,
        "https://dmarket.com/ingame-items/item-list/rust-skins?title=",
    )
