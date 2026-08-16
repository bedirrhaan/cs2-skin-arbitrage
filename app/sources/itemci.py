"""Itemci — HTML ayrıştırma.

/categories/cs2-skin?q=<kelime> arama sayfasındaki kartlar:
.item-name + .item-subtext (Türkçe wear) + .cs-price ("230,00 TL").
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from ..itemname import ParsedItem, WEAR_TR, listing_contains_skin, norm, norm_listing
from .base import PriceResult, USER_AGENT

BASE = "https://itemci.com"


def _parse_price(text: str) -> float | None:
    text = text.replace("\xa0", "").replace(" ", "")
    m = re.search(r"([\d.]+)(?:,(\d+))?", text)
    if not m:
        return None
    whole = m.group(1).replace(".", "")
    frac = m.group(2) or "0"
    try:
        return float(f"{whole}.{frac}")
    except ValueError:
        return None


def _wear_from_subtext(text: str) -> str | None:
    return WEAR_TR.get(text.strip().lower())


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="itemci", currency="TRY")
    try:
        keywords = [parsed.keyword]
        if "|" in parsed.base_name:
            pattern = parsed.base_name.split("|", 1)[1].strip()
            if pattern and pattern not in keywords:
                keywords.append(pattern)

        soup = None
        url = None
        for kw in keywords:
            url = f"{BASE}/categories/cs2-skin?q={quote(kw)}"
            r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=40)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.select(".cs-skin-card"):
                break

        target = norm(parsed.base_name)
        candidates: list[tuple[float, str]] = []
        for card in soup.select(".cs-skin-card"):
            name_el = card.select_one(".item-name")
            wear_el = card.select_one(".item-subtext")
            price_el = card.select_one(".cs-price")
            if not name_el or not price_el:
                continue
            raw_name = name_el.get_text(" ", strip=True)
            has_st = "stattrak" in raw_name.lower()
            if norm_listing(raw_name) != target and not listing_contains_skin(raw_name, parsed):
                continue
            if parsed.stattrak != has_st:
                continue
            wear_text = wear_el.get_text(strip=True) if wear_el else ""
            listing_wear = _wear_from_subtext(wear_text)
            if parsed.wear and listing_wear and listing_wear != parsed.wear:
                continue
            p = _parse_price(price_el.get_text(" ", strip=True))
            if not p:
                continue
            link = card.select_one("a[href*='/product/']")
            href = link.get("href", "") if link else ""
            if href and not href.startswith("http"):
                href = BASE + href
            candidates.append((p, href))

        if not candidates:
            res.error = "ilan bulunamadı"
            return res
        res.price, listing_url = min(candidates, key=lambda x: x[0])
        res.url = listing_url or url
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res
