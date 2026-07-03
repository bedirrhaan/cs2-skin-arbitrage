"""Bitskins — API v2. Ücretsiz hesapla alınan API anahtarı gerektirir.

Fiyat birimi: USD'nin binde biri (1000 = 1 USD).
"""
from __future__ import annotations
from urllib.parse import quote

import httpx
from ..itemname import ParsedItem
from .base import PriceResult

CS2_APP = 730
RUST_APP = 252490


async def _fetch(
    client: httpx.AsyncClient,
    parsed: ParsedItem,
    api_key: str,
    app_id: int,
    market_path: str,
) -> PriceResult:
    res = PriceResult(source="bitskins", currency="USD")
    if not api_key:
        res.error = "API anahtarı gerekli (Ayarlar'dan girin)"
        return res
    try:
        r = await client.post(
            f"https://api.bitskins.com/market/search/{app_id}",
            json={
                "limit": 30,
                "order": [{"field": "price", "order": "ASC"}],
                "where": {"name": parsed.full_name},
            },
            headers={"x-apikey": api_key, "Content-Type": "application/json"},
            timeout=30,
        )
        if r.status_code == 401:
            res.error = "API anahtarı geçersiz"
            return res
        r.raise_for_status()
        data = r.json()
        rows = data.get("list", data if isinstance(data, list) else [])
        prices = []
        for o in rows:
            if o.get("name") != parsed.full_name:
                continue
            p = o.get("price")
            if p is not None:
                prices.append(int(p) / 1000.0)
        if not prices:
            res.error = "ilan bulunamadı"
            return res
        res.price = min(prices)
        res.url = f"https://bitskins.com/market/{market_path}?search=" + quote(parsed.full_name)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"[:200]
    return res


async def fetch(client: httpx.AsyncClient, parsed: ParsedItem, api_key: str = "") -> PriceResult:
    return await _fetch(client, parsed, api_key, CS2_APP, "cs2")


async def fetch_rust(client: httpx.AsyncClient, parsed: ParsedItem, api_key: str = "") -> PriceResult:
    return await _fetch(client, parsed, api_key, RUST_APP, "rust")
