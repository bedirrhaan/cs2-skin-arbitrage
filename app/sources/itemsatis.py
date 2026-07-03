"""İtemSatış — HTML ayrıştırma.

/ilanlar/cs-2-skins/skin.html?searchText=<kelime> arama sayfası.
İlan kartları /cs2-skin-pazari/... linkleri; Steam adı genelde >> sonrasında.
Fiyatlar TRY ("İlan Ücreti 325 .00 ₺").
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from ..itemname import ParsedItem, detect_listing_wear, norm, norm_listing
from ..ko_item import ParsedKoItem, ko_listing_matches, norm_ko
from .base import PriceResult, USER_AGENT

BASE = "https://www.itemsatis.com"


def _parse_price(text: str) -> float | None:
    text = text.replace("\xa0", " ").strip()
    if "," in text:
        compact = re.sub(r"\s+", "", text)
        m = re.search(r"([\d.]+)(?:,(\d+))?", compact)
        if m:
            whole = m.group(1).replace(".", "")
            frac = m.group(2) or "0"
            try:
                return float(f"{whole}.{frac}")
            except ValueError:
                pass
    m = re.search(r"([\d\s.]+)", text)
    if m:
        try:
            return float(m.group(1).replace(" ", ""))
        except ValueError:
            pass
    return None


def _listing_block(anchor) -> str:
    node = anchor
    for _ in range(10):
        node = node.parent
        if not node:
            return ""
        txt = node.get_text(" ", strip=True)
        if "İlan Ücreti" in txt and len(txt) < 700:
            return txt
    return ""


def _market_name(block: str, link_text: str) -> str:
    m = re.search(r">>\s*(.+?)(?:\s*\.\.\.|$)", block)
    if m:
        return m.group(1).strip()
    return link_text


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="itemsatis", currency="TRY")
    try:
        keywords = [parsed.keyword]
        if "|" in parsed.base_name:
            pattern = parsed.base_name.split("|", 1)[1].strip()
            if pattern and pattern not in keywords:
                keywords.append(pattern)

        soup = None
        url = None
        for kw in keywords:
            url = f"{BASE}/ilanlar/cs-2-skins/skin.html?searchText={quote(kw)}"
            r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.select('a[href*="/cs2-skin-pazari/"]'):
                break

        target = norm(parsed.base_name)
        seen: set[str] = set()
        candidates: list[tuple[float, str]] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/cs2-skin-pazari/" not in href or href in seen:
                continue
            seen.add(href)
            link_text = a.get_text(" ", strip=True)
            block = _listing_block(a)
            if not block:
                continue
            market = _market_name(block, link_text)
            has_st = "stattrak" in market.lower() or "stattrak" in link_text.lower()
            if norm_listing(market) != target:
                continue
            if parsed.stattrak != has_st:
                continue
            listing_wear = detect_listing_wear(market + " " + link_text, href)
            if parsed.wear and listing_wear and listing_wear != parsed.wear:
                continue
            pm = re.search(r"İlan Ücreti\s*([\d\s.,]+)\s*₺", block)
            if not pm:
                continue
            p = _parse_price(pm.group(1))
            if not p:
                continue
            full_href = href if href.startswith("http") else BASE + href
            candidates.append((p, full_href))

        if not candidates:
            res.error = "ilan bulunamadı"
            return res
        res.price, listing_url = min(candidates, key=lambda x: x[0])
        res.url = listing_url
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


def _itemsatis_ko_paths(parsed: ParsedKoItem) -> list[str]:
    q = quote(parsed.keyword)
    paths = []
    if "ring" in parsed.base_name.lower():
        paths.append(f"{BASE}/ilanlar/knight-online-gb/ring.html?searchText={q}")
    paths.append(f"{BASE}/ilanlar/knight-online-gb/item.html?searchText={q}")
    if parsed.base_name != parsed.keyword:
        paths.append(
            f"{BASE}/ilanlar/knight-online-gb/item.html?searchText={quote(parsed.base_name)}"
        )
    return paths


async def fetch_ko(client: httpx.AsyncClient, parsed: ParsedKoItem) -> PriceResult:
    res = PriceResult(source="itemsatis", currency="TRY")
    try:
        soup = None
        url = None
        for page_url in _itemsatis_ko_paths(parsed):
            r = await client.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=45)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            url = page_url
            if "IlanYokDiv" not in r.text:
                break

        if soup is None:
            res.error = "sayfa yüklenemedi"
            return res

        target = norm_ko(parsed.base_name)
        seen: set[str] = set()
        candidates: list[tuple[float, str]] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "knight-online" not in href.lower() or href in seen:
                continue
            if "/ilan/" not in href and "ilanlar/knight-online-gb/" not in href:
                continue
            seen.add(href)
            link_text = a.get_text(" ", strip=True)
            block = _listing_block(a)
            if not block:
                continue
            market = _market_name(block, link_text)
            if not ko_listing_matches(parsed, market):
                listing_base = norm_ko(market.split("+")[0])
                if target not in listing_base and listing_base not in target:
                    continue
            pm = re.search(r"İlan Ücreti\s*([\d\s.,]+)\s*₺", block)
            if not pm:
                continue
            p = _parse_price(pm.group(1))
            if not p:
                continue
            full_href = href if href.startswith("http") else BASE + href
            candidates.append((p, full_href))

        if not candidates:
            res.error = "ilan bulunamadı"
            res.url = url
            return res
        res.price, listing_url = min(candidates, key=lambda x: x[0])
        res.url = listing_url
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res
