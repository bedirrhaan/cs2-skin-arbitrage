"""Oyunfor Knight Online item ilanları — HTML ayrıştırma.

/ilanlar/knight-online/item — item kategorisi (karakter ilanları elenir).
Kart: .ilanTitle + .ilanPrice / .new_price
Fiyatlar TRY ("3200.00 TL").
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from ..ko_item import ParsedKoItem, ko_listing_matches
from .base import PriceResult, USER_AGENT, attach_top_offers, short_error

BASE = "https://www.oyunfor.com"
LIST_PATH = "/ilanlar/knight-online/item"


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


def _abs(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return BASE + href


def _is_character_listing(title: str, category: str) -> bool:
    cat = (category or "").lower()
    if "karakter" in cat or "account" in cat or "hesap" in cat:
        return True
    if re.search(r"\b\d{2,3}\s*/\s*\d+", title):
        return True
    if re.search(r"\b(lvl|level|reb(?:irth)?|priest|warrior|rogue|mage|ok[cç]u)\b", title, re.I):
        if not re.search(r"\+\d+", title):
            return True
    return False


def _parse_cards(soup: BeautifulSoup, page_url: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for title_el in soup.select(".ilanTitle"):
        title = title_el.get_text(" ", strip=True)
        if not title:
            continue
        scope = title_el.parent
        for _ in range(10):
            if not scope:
                break
            if scope.select_one(".ilanPrice, .new_price"):
                break
            scope = scope.parent
        if not scope:
            continue
        cat_el = scope.select_one(".ilanCategory")
        category = cat_el.get_text(" ", strip=True) if cat_el else ""
        if _is_character_listing(title, category):
            continue
        price_el = scope.select_one(".new_price, .ilanPrice")
        price = _parse_price(price_el.get_text(" ", strip=True) if price_el else "")
        link = title_el.find_parent("a") or scope.find("a", href=True)
        href = _abs(link.get("href") if link else "") or page_url
        key = f"{title}|{href}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({"title": title, "price": price, "url": href})
    return rows


async def search_ko_listings(client: httpx.AsyncClient, parsed: ParsedKoItem) -> list[dict]:
    keywords = [parsed.keyword]
    if parsed.base_name and parsed.base_name not in keywords:
        keywords.append(parsed.base_name)

    rows: list[dict] = []
    seen: set[str] = set()
    urls: list[str] = []
    for kw in keywords:
        urls.append(f"{BASE}{LIST_PATH}?ilanq={quote(kw)}")
        urls.append(f"{BASE}/ilanlar/knight-online?ilanq={quote(kw)}")
    urls.append(f"{BASE}{LIST_PATH}")

    for url in urls:
        r = await client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Referer": BASE + LIST_PATH},
            timeout=40,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        batch = _parse_cards(soup, url)
        found = 0
        for row in batch:
            key = f"{row['title']}|{row['url']}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            found += 1
        if found and "ilanq=" in url:
            break
    return rows


async def fetch_ko(client: httpx.AsyncClient, parsed: ParsedKoItem) -> PriceResult:
    res = PriceResult(source="oyunfor", currency="TRY")
    search_url = f"{BASE}{LIST_PATH}?ilanq={quote(parsed.keyword)}"
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
