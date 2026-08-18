"""Klasgame Knight Online item pazarı — HTML ayrıştırma.

/oyuncu-pazari/knightonline/usko-item-pazari?keyword=<kelime>
Kart: h3.pm-title a + .pm-price [data-type=price]
Fiyatlar TRY (6,000.00 veya 6.000,00).
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from ..ko_item import ParsedKoItem, ko_listing_matches
from .base import PriceResult, USER_AGENT, attach_top_offers, short_error

BASE = "https://www.klasgame.com"
LIST_PATH = "/oyuncu-pazari/knightonline/usko-item-pazari"


def _parse_price(text: str) -> float | None:
    text = (text or "").replace("\xa0", " ")
    compact = re.sub(r"[^\d.,]", "", text)
    if not compact:
        return None
    if "," in compact and "." in compact:
        if compact.rfind(",") > compact.rfind("."):
            compact = compact.replace(".", "").replace(",", ".")
        else:
            compact = compact.replace(",", "")
    elif "," in compact:
        if re.search(r",\d{1,2}$", compact):
            compact = compact.replace(".", "").replace(",", ".")
        else:
            compact = compact.replace(",", "")
    try:
        val = float(compact)
    except ValueError:
        return None
    return val if val > 0 else None


async def search_ko_listings(client: httpx.AsyncClient, parsed: ParsedKoItem) -> list[dict]:
    keywords = [parsed.keyword]
    if parsed.base_name and parsed.base_name not in keywords:
        keywords.append(parsed.base_name)

    rows: list[dict] = []
    seen: set[str] = set()
    for kw in keywords:
        url = f"{BASE}{LIST_PATH}?keyword={quote(kw)}&sort=2"
        r = await client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Referer": BASE + LIST_PATH},
            timeout=40,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        found = 0
        for title_el in soup.select("h3.pm-title a"):
            title = title_el.get_text(" ", strip=True)
            href = title_el.get("href") or ""
            if href and not href.startswith("http"):
                href = BASE + href
            card = title_el.find_parent("div", class_=re.compile(r"pm-")) or title_el.parent
            price_el = None
            scope = card
            for _ in range(6):
                if not scope:
                    break
                price_el = scope.select_one(".pm-price [data-type=price], [data-type=price]")
                if price_el:
                    break
                scope = scope.parent
            price = _parse_price(price_el.get_text(" ", strip=True) if price_el else "")
            key = f"{title}|{href}"
            if key in seen:
                continue
            seen.add(key)
            rows.append({"title": title, "price": price, "url": href or url})
            found += 1
        if found:
            break
    return rows


async def fetch_ko(client: httpx.AsyncClient, parsed: ParsedKoItem) -> PriceResult:
    res = PriceResult(source="klasgame", currency="TRY")
    search_url = f"{BASE}{LIST_PATH}?keyword={quote(parsed.keyword)}&sort=2"
    try:
        candidates: list[tuple[float, str]] = []
        for row in await search_ko_listings(client, parsed):
            if not ko_listing_matches(parsed, row["title"]):
                continue
            if row.get("price") is None:
                continue
            candidates.append((row["price"], row["url"]))
        if not candidates:
            res.error = "ilan bulunamadı"
            res.url = search_url
            return res
        attach_top_offers(res, candidates)
        if not res.url:
            res.url = search_url
    except Exception as e:
        res.error = short_error(e)
        res.url = search_url
    return res
