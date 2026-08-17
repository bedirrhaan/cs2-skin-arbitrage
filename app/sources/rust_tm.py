"""rust.tm — halka açık fiyat listesi API.

GET /api/v2/prices/USD.json → {items: [{market_hash_name, volume, price}]}
price USD string. Liste süreç içinde önbellekte tutulur.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx

from .. import catalog_cache as cache
from ..itemname import ParsedItem
from .base import PriceResult

CACHE_KEY = "rust_tm:usd"
TTL = 300
_COOLDOWN = 300
_HIST_INDEX_URL = "https://rust.tm/api/v2/full-history/all.json"
_HIST_ITEM_URL = "https://rust.tm/api/v2/full-history/{id}.json"
_hist_index: dict[str, int] | None = None
_hist_index_at = 0.0


async def _get_items(client: httpx.AsyncClient) -> dict:
    now = time.time()
    entry = await cache.get(CACHE_KEY)
    if entry and entry.fresh(TTL, now):
        return entry.items
    if entry and entry.in_cooldown(now):
        return entry.items

    async with cache.lock(CACHE_KEY):
        now = time.time()
        entry = await cache.get(CACHE_KEY)
        if entry and entry.fresh(TTL, now):
            return entry.items
        if entry and entry.in_cooldown(now):
            return entry.items

        try:
            r = await client.get(
                "https://rust.tm/api/v2/prices/USD.json",
                timeout=90,
            )
            if r.status_code == 429:
                raise httpx.HTTPStatusError("rate limit", request=r.request, response=r)
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise ValueError("rust.tm API hatası")
            raw = data.get("items") or []
            items = {}
            for it in raw:
                name = it.get("market_hash_name")
                if not name:
                    continue
                try:
                    vol = int(it.get("volume") or 0)
                except (TypeError, ValueError):
                    vol = 0
                try:
                    price = float(it.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0
                items[name] = {"quantity": vol, "min_price": price}
            await cache.put(CACHE_KEY, items, TTL)
            return items
        except httpx.HTTPStatusError:
            if entry and entry.items:
                await cache.set_cooldown(CACHE_KEY, _COOLDOWN)
                return entry.items
            raise


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem) -> PriceResult:
    res = PriceResult(source="rust_tm", currency="USD")
    try:
        items = await _get_items(client)
        it = items.get(parsed.full_name)
        if not it:
            res.error = "item bulunamadı"
            return res
        qty = it.get("quantity") or 0
        min_price = it.get("min_price")
        if qty <= 0 or min_price is None or min_price <= 0:
            res.error = "satışta yok"
            return res
        res.price = min_price
        res.url = (
            "https://rust.tm/?search="
            + quote(parsed.full_name)
        )
    except httpx.HTTPStatusError:
        res.error = "rust.tm istek limiti — birkaç dakika sonra tekrar dene"
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def _history_index(client: httpx.AsyncClient) -> dict[str, int]:
    global _hist_index, _hist_index_at
    now = time.time()
    if _hist_index is not None and now - _hist_index_at < 3600:
        return _hist_index
    r = await client.get(_HIST_INDEX_URL, timeout=40)
    r.raise_for_status()
    blob = r.json().get("history") or {}
    _hist_index = {str(k): int(v) for k, v in blob.items() if k and v is not None}
    _hist_index_at = now
    return _hist_index


def _lookup_hist_id(index: dict[str, int], name: str) -> int | None:
    if not name:
        return None
    if name in index:
        return index[name]
    low = name.casefold()
    for k, v in index.items():
        if k.casefold() == low:
            return v
    return None


async def fetch_sales_history(
    client: httpx.AsyncClient,
    name: str,
    try_rate: float,
) -> list[tuple[str, float]]:
    """rust.tm satış geçmişi (USD → TRY). Grafik için asıl kaynak."""
    import datetime as dt
    try:
        index = await _history_index(client)
        iid = _lookup_hist_id(index, name)
        if iid is None:
            return []
        r = await client.get(_HIST_ITEM_URL.format(id=iid), timeout=40)
        r.raise_for_status()
        data = r.json().get("data") or {}
        out: list[tuple[str, float]] = []
        for row in data.get("history") or []:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            try:
                ts = dt.datetime.utcfromtimestamp(int(row[0]))
                usd = float(row[2])
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            if usd <= 0:
                continue
            out.append((ts.replace(microsecond=0).isoformat(), round(usd * try_rate, 2)))
        out.sort(key=lambda x: x[0])
        return out
    except Exception:
        return []

