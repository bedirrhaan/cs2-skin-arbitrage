"""Kopazar — resmi API yok, HTML ayrıştırma.

Önce ana sayfadan çerez alınır, sonra /cs2/skin?keyword=... ile aranır.
Kart yapısı: .skin-v2-name (silah) + .skin-v2-subname (desen) +
.float-short (FN/MW/FT/WW/BS) + .skin-v2-price .price ("3.500,00 TL").
Fiyatlar TRY.
"""
from __future__ import annotations
import re
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from ..itemname import ParsedItem, listing_contains_skin, norm, norm_listing
from ..ko_item import ParsedKoItem, ko_listing_matches
from .base import PriceResult, USER_AGENT, attach_top_offers

BASE = "https://www.kopazar.com"
_cookies: httpx.Cookies | None = None


def _parse_price(text: str) -> float | None:
    # "3.500,00 TL" -> 3500.0
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


async def _ensure_cookies(client: httpx.AsyncClient):
    global _cookies
    if _cookies is None:
        r = await client.get(BASE + "/", headers={"User-Agent": USER_AGENT}, timeout=30)
        _cookies = r.cookies


def _parse_ko_card_price(card) -> float | None:
    price_el = card.select_one("strong.card-price")
    if price_el:
        sup = price_el.select_one("sup")
        whole = price_el.get_text("", strip=True)
        if sup:
            whole = whole.replace(sup.get_text("", strip=True), "").strip()
            text = f"{whole}{sup.get_text('', strip=True)}"
        else:
            text = whole
        return _parse_price(text + " TL")
    for el in card.select(".skin-v2-price .price, .price"):
        p = _parse_price(el.get_text(" ", strip=True))
        if p:
            return p
    return None


async def search_ko_listings(
    client: httpx.AsyncClient, parsed: ParsedKoItem, *, merge_keywords: bool = False
) -> list[dict]:
    await _ensure_cookies(client)
    keywords = [parsed.keyword]
    if parsed.base_name and parsed.base_name not in keywords:
        keywords.append(parsed.base_name)

    rows: list[dict] = []
    seen: set[str] = set()
    for kw in keywords:
        url = f"{BASE}/knight-online-item?keyword={quote(kw)}&sort=cheap&limit=48"
        r = await client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Referer": BASE + "/knight-online-item"},
            cookies=_cookies,
            timeout=40,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        found = 0
        for card in soup.select("a.card.item"):
            title_el = card.select_one(".item-title strong")
            if not title_el:
                continue
            title = title_el.get_text(" ", strip=True)
            href = card.get("href", "")
            if href and not href.startswith("http"):
                href = BASE + href
            key = f"{title}|{href}"
            if key in seen:
                continue
            seen.add(key)
            price = _parse_ko_card_price(card)
            rows.append({"title": title, "price": price, "url": href or url})
            found += 1
        if found and not merge_keywords:
            break
    return rows


async def list_ko_cheap(client: httpx.AsyncClient, limit: int = 24) -> list[dict]:
    """Kopazar KO item listesi — ucuzdan pahalıya, popüler tarama tohumu."""
    await _ensure_cookies(client)
    url = f"{BASE}/knight-online-item?sort=cheap&limit={min(max(int(limit or 24), 8), 48)}"
    r = await client.get(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": BASE + "/knight-online-item"},
        cookies=_cookies,
        timeout=40,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    rows: list[dict] = []
    seen: set[str] = set()
    for card in soup.select("a.card.item"):
        title_el = card.select_one(".item-title strong")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        href = card.get("href", "")
        if href and not href.startswith("http"):
            href = BASE + href
        if title in seen:
            continue
        seen.add(title)
        rows.append({
            "title": title,
            "price": _parse_ko_card_price(card),
            "url": href or url,
        })
        if len(rows) >= limit:
            break
    return rows


async def fetch_ko(client: httpx.AsyncClient, parsed: ParsedKoItem) -> PriceResult:
    res = PriceResult(source="kopazar", currency="TRY")
    try:
        candidates: list[tuple[float, str]] = []
        search_url = f"{BASE}/knight-online-item?keyword={quote(parsed.keyword)}&sort=cheap"
        for row in await search_ko_listings(client, parsed):
            if not ko_listing_matches(parsed, row["title"]):
                continue
            if row["price"] is None:
                continue
            candidates.append((row["price"], row["url"]))
        if not candidates:
            rev_hint = ""
            if parsed.plus and not parsed.reverse:
                rev_parsed = ParsedKoItem(
                    full_name=f"{parsed.base_name} +{parsed.plus} (Reverse)",
                    base_name=parsed.base_name,
                    keyword=f"{parsed.base_name} +{parsed.plus} (Reverse)",
                    plus=parsed.plus,
                    reverse=True,
                )
                rev_rows = [
                    row
                    for row in await search_ko_listings(client, rev_parsed)
                    if ko_listing_matches(rev_parsed, row["title"]) and row.get("price")
                ]
                if rev_rows:
                    rev_hint = f" — sadece Reverse var (~{min(r['price'] for r in rev_rows):.0f} TL)"
            res.error = ("Reverse olmayan ilan yok" + rev_hint) if rev_hint else "ilan bulunamadı"
            res.url = search_url
            return res
        attach_top_offers(res, candidates)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="kopazar", currency="TRY")
    try:
        await _ensure_cookies(client)
        # Kopazar araması birleşik kelimeleri eşleyemiyor; önce tam anahtar
        # kelime, sonuç yoksa sadece desen adı (| sonrası) ile dene.
        keywords = [parsed.keyword]
        if "|" in parsed.base_name:
            pattern = parsed.base_name.split("|", 1)[1].strip()
            if pattern and pattern not in keywords:
                keywords.append(pattern)

        soup = None
        url = None
        for kw in keywords:
            url = f"{BASE}/cs2/skin?page=1&limit=48&keyword={quote(kw)}&sort=cheap"
            r = await client.get(
                url,
                headers={"User-Agent": USER_AGENT, "Referer": BASE + "/cs2/skin"},
                cookies=_cookies,
                timeout=40,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.select(".skin-v2-content"):
                break

        target = norm(parsed.base_name)
        candidates: list[tuple[float, str]] = []
        for card in soup.select(".skin-v2-content"):
            name_el = card.select_one(".skin-v2-name")
            sub_el = card.select_one(".skin-v2-subname")
            if not name_el:
                continue
            full = name_el.get_text(" ", strip=True)
            if sub_el:
                full += " " + sub_el.get_text(" ", strip=True)
            if norm_listing(full) != target and not listing_contains_skin(full, parsed):
                continue

            # kartın tamamı bir <a> içinde; wear rozeti ve fiyat kardeş bloklarda
            scope = card.find_parent("a") or card.parent or card
            wear_el = scope.select_one(".float-short") if scope else None
            wear_short = wear_el.get_text(strip=True) if wear_el else None
            if parsed.wear_short and wear_short and wear_short != parsed.wear_short:
                continue

            st_text = scope.get_text(" ", strip=True) if scope else full
            has_st = "stattrak" in st_text.lower()
            if parsed.stattrak != has_st:
                continue

            price_el = scope.select_one(".skin-v2-price .price") if scope else None
            if not price_el:
                continue
            p = _parse_price(price_el.get_text(" ", strip=True))
            if not p:
                continue
            href = scope.get("href", "") if scope and scope.name == "a" else ""
            if not href and scope:
                link = scope.find("a", href=True)
                href = link.get("href", "") if link else ""
            if href and not href.startswith("http"):
                href = BASE + href
            candidates.append((p, href))

        if not candidates:
            res.error = "ilan bulunamadı"
            return res
        attach_top_offers(res, candidates)
        if not res.url:
            res.url = url
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res
