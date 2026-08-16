"""Steam Community Market — resmi referans fiyat.

CS2 appid=730, Rust=252490. currency=17 → TRY (en doğru TL karşılaştırması).
Alım yeri değil; piyasa referansı ve grafik için kullanılır.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from ..itemname import ParsedItem
from .base import PriceResult, USER_AGENT

CS2_APP = 730
RUST_APP = 252490
TRY = 17


def _parse_try(text: str | None) -> float | None:
    if not text:
        return None
    s = text.replace("\xa0", " ").strip()
    m = re.search(r"([\d.]+,\d{2}|\d+,\d{2}|\d+)", s.replace(" ", ""))
    if not m:
        m = re.search(r"([\d.,]+)", s)
        if not m:
            return None
    raw = m.group(1)
    try:
        if "," in raw:
            return float(raw.replace(".", "").replace(",", "."))
        return float(raw)
    except ValueError:
        return None


async def _fetch(client: httpx.AsyncClient, parsed: ParsedItem, app_id: int) -> PriceResult:
    res = PriceResult(source="steam", currency="TRY")
    name = parsed.full_name
    try:
        r = await client.get(
            "https://steamcommunity.com/market/priceoverview/",
            params={
                "appid": app_id,
                "currency": TRY,
                "market_hash_name": name,
            },
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Referer": f"https://steamcommunity.com/market/listings/{app_id}/{quote(name)}",
            },
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            res.error = "Steam'de bulunamadı"
            return res
        price = _parse_try(data.get("lowest_price") or data.get("median_price"))
        if not price:
            res.error = "fiyat yok"
            return res
        res.price = price
        res.url = (
            "https://steamcommunity.com/market/listings/"
            f"{app_id}/{quote(name)}"
        )
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, CS2_APP)


async def fetch_rust(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, RUST_APP)
