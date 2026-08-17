"""Steam Community Market — resmi referans fiyat.

CS2 appid=730, Rust=252490. currency=17 → TRY (en doğru TL karşılaştırması).
Alım yeri değil; piyasa referansı ve grafik için kullanılır.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from ..itemname import ParsedItem
from .base import PriceResult, USER_AGENT, short_error

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
        res.error = short_error(e)
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, CS2_APP)


async def fetch_rust(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    return await _fetch(client, parsed, RUST_APP)


_MONTH = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_LINE1 = re.compile(r"var line1\s*=\s*(\[\[.*?\]\]);", re.DOTALL)


def _parse_steam_chart_date(raw: str):
    import datetime as dt
    m = re.match(r"([A-Za-z]+) (\d{1,2}) (\d{4}) (\d{1,2})", (raw or "").strip())
    if not m:
        return None
    mon = _MONTH.get(m.group(1)[:3].title())
    if not mon:
        return None
    try:
        return dt.datetime(int(m.group(3)), mon, int(m.group(2)), int(m.group(4)))
    except ValueError:
        return None


def _pairs_from_steam_prices(raw, try_rate: float) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ts = _parse_steam_chart_date(str(row[0]))
        try:
            usd = float(row[1])
        except (TypeError, ValueError):
            continue
        if ts is None or usd <= 0:
            continue
        out.append((ts.replace(microsecond=0).isoformat(), round(usd * try_rate, 2)))
    return out


async def fetch_price_history(
    client: httpx.AsyncClient,
    *,
    app_id: int,
    name: str,
    try_rate: float,
) -> list[tuple[str, float]]:
    """Steam Market satış geçmişi (line1 / pricehistory). Fiyat USD → TRY."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json",
        "Referer": f"https://steamcommunity.com/market/listings/{app_id}/",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = await client.get(
            "https://steamcommunity.com/market/pricehistory/",
            params={"appid": app_id, "market_hash_name": name, "currency": 1},
            headers=headers,
            timeout=20,
        )
        if r.status_code < 400:
            body = r.json()
            if body.get("success"):
                got = _pairs_from_steam_prices(body.get("prices") or [], try_rate)
                if len(got) >= 2:
                    return got
    except Exception:
        pass
    try:
        r = await client.get(
            f"https://steamcommunity.com/market/listings/{app_id}/{quote(name)}",
            headers=headers,
            timeout=25,
        )
        if r.status_code >= 400:
            return []
        m = _LINE1.search(r.text or "")
        if not m:
            return []
        import json
        return _pairs_from_steam_prices(json.loads(m.group(1)), try_rate)
    except Exception:
        return []

