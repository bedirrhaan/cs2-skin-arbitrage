"""Steam Community Market — resmi referans fiyat (Rust appid 252490).

GET /market/priceoverview/ — lowest_price USD string döner.
Alım yeri değil; piyasa referansı için kullanılır.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from ..itemname import ParsedItem
from .base import PriceResult, USER_AGENT

APP_ID = 252490


def _parse_usd(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"([\d.,]+)", text.replace("\xa0", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="steam", currency="USD")
    try:
        r = await client.get(
            "https://steamcommunity.com/market/priceoverview/",
            params={
                "appid": APP_ID,
                "currency": 1,
                "market_hash_name": parsed.full_name,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            res.error = "Steam'de bulunamadı"
            return res
        price = _parse_usd(data.get("lowest_price") or data.get("median_price"))
        if not price:
            res.error = "fiyat yok"
            return res
        res.price = price
        res.url = (
            "https://steamcommunity.com/market/listings/"
            f"{APP_ID}/{quote(parsed.full_name)}"
        )
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res
