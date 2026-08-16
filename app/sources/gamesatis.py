"""GameSatis — resmi API yok, HTML ayrıştırma.

/cs2-skin?q=<kelime> arama sayfasındaki ürün kartları:
.product-name (isim, örn "StatTrak AK-47 | Redline") + .selling-price
("1.150,00 ₺"). Wear bilgisi ürün linkinin slug'ında (örn ...-field-tested).
Fiyatlar TRY.
"""
from __future__ import annotations
import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from ..itemname import ParsedItem, listing_contains_skin, norm, norm_listing, WEAR_SLUGS
from .base import PriceResult, USER_AGENT

BASE = "https://www.gamesatis.com"
CS2_PATH = "/cs2-skin"
RUST_PATH = "/rust"


def _parse_price(text: str) -> float | None:
    m = re.search(r"([\d.]+)(?:,(\d+))?", text.replace("\xa0", " "))
    if not m:
        return None
    whole = m.group(1).replace(".", "")
    frac = m.group(2) or "0"
    try:
        return float(f"{whole}.{frac}")
    except ValueError:
        return None


async def _fetch_path(
    client: httpx.AsyncClient, parsed: ParsedItem, path: str
) -> PriceResult:
    res = PriceResult(source="gamesatis", currency="TRY")
    try:
        url = f"{BASE}{path}?q={quote(parsed.keyword)}"
        r = await client.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=40, follow_redirects=True
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        target = norm(parsed.base_name)
        wear_slug = WEAR_SLUGS.get(parsed.wear) if parsed.wear else None
        prices = []
        listing_url = url
        for a in soup.select("a.product.product-skin, a.product-skin, .product.product-skin"):
            name_el = a.select_one(".product-name")
            price_el = a.select_one(".selling-price")
            if not name_el or not price_el:
                continue
            raw_name = name_el.get_text(" ", strip=True)
            has_st = "stattrak" in raw_name.lower()
            if norm_listing(raw_name) != target and not listing_contains_skin(raw_name, parsed):
                continue
            if parsed.stattrak != has_st:
                continue
            href = a.get("href", "") if a.name == "a" else (a.find("a") or {}).get("href", "")
            if wear_slug and href and wear_slug not in href:
                continue
            p = _parse_price(price_el.get_text(" ", strip=True))
            if p:
                prices.append(p)
                if href:
                    listing_url = href if href.startswith("http") else BASE + href

        if not prices:
            res.error = "ilan bulunamadı"
            res.url = url
            return res
        res.price = min(prices)
        res.url = listing_url
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch_path(client, parsed, CS2_PATH)


async def fetch_rust(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch_path(client, parsed, RUST_PATH)
