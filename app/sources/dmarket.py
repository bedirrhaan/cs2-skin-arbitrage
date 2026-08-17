"""DMarket — halka açık market-depth API. Fiyatlar USD cent olarak döner.

Eski /exchange/v1/market/items 410 Gone döner; yerine
GET /marketplace-api/v1/market-depth kullanılır.
"""
from __future__ import annotations
from urllib.parse import quote

import httpx
from ..itemname import ParsedItem, cs2_wear_variants
from .base import USER_AGENT, PriceResult, attach_top_offers

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


async def _offer_rows(
    client: httpx.AsyncClient, title: str, game_id: str, url_base: str
) -> list[tuple[float, str]]:
    r = await client.get(
        API,
        params={"gameId": game_id, "title": title},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    r.raise_for_status()
    rows = []
    for o in r.json().get("offers") or []:
        p = _cent_price(o.get("price"))
        if p is None:
            continue
        extra = o.get("extra") or {}
        iid = extra.get("link") or extra.get("itemId") or o.get("itemId") or o.get("offerId")
        url = url_base + quote(title)
        if iid:
            url = f"https://dmarket.com/ingame-items/item/{iid}"
        rows.append((p, url))
    return rows


async def cheapest_offer_usd(
    client: httpx.AsyncClient, title: str, game_id: str
) -> float | None:
    rows = await _offer_rows(client, title, game_id, "")
    return min((p for p, _ in rows), default=None)


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
        best_rows: list[tuple[float, str]] = []
        best_title = None
        for title in titles:
            rows = await _offer_rows(client, title, game_id, url_base)
            if not rows:
                continue
            low = min(p for p, _ in rows)
            if not best_rows or low < min(p for p, _ in best_rows):
                best_rows = rows
                best_title = title
            if parsed.wear:
                break
        if not best_rows:
            res.error = "ilan bulunamadı"
            return res
        attach_top_offers(res, best_rows)
        if not res.url:
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
