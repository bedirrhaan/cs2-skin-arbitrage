"""DMarket — halka açık market-depth API. Fiyatlar USD cent olarak döner.

Eski /exchange/v1/market/items 410 Gone döner; yerine
GET /marketplace-api/v1/market-depth kullanılır.
"""
from __future__ import annotations
from urllib.parse import quote

import httpx
from ..itemname import ParsedItem, cs2_wear_variants
from .base import USER_AGENT, PriceResult

API = "https://api.dmarket.com/marketplace-api/v1/market-depth"
CS2_GAME_ID = "a8db"
RUST_GAME_ID = "rust"


def _cent_price(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw) / 100.0
    except (TypeError, ValueError):
        return None


async def cheapest_offer_usd(
    client: httpx.AsyncClient, title: str, game_id: str
) -> float | None:
    r = await client.get(
        API,
        params={"gameId": game_id, "title": title},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    r.raise_for_status()
    offers = r.json().get("offers") or []
    prices = []
    for o in offers:
        p = _cent_price(o.get("price"))
        if p is not None:
            prices.append(p)
    return min(prices) if prices else None


async def _fetch(
    client: httpx.AsyncClient,
    parsed: ParsedItem,
    game_id: str,
    url_base: str,
) -> PriceResult:
    res = PriceResult(source="dmarket", currency="USD")
    try:
        titles = []
        seen: set[str] = set()
        extra = cs2_wear_variants(parsed) if game_id == CS2_GAME_ID else []
        for t in [parsed.full_name, *extra]:
            if t and t not in seen:
                seen.add(t)
                titles.append(t)
        best = None
        best_title = None
        for title in titles:
            price = await cheapest_offer_usd(client, title, game_id)
            if price is None:
                continue
            if best is None or price < best:
                best = price
                best_title = title
            if parsed.wear:
                break
        if best is None:
            res.error = "ilan bulunamadı"
            return res
        res.price = best
        res.url = url_base + quote(best_title or parsed.full_name)
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
