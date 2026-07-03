"""Döviz kurları — open.er-api.com (ücretsiz, anahtarsız), 6 saat önbellek."""
from __future__ import annotations
import time
import httpx

_cache: dict = {"rates": None, "ts": 0}
TTL = 6 * 3600
FALLBACK = {"USD": 1.0, "EUR": 0.92, "TRY": 41.0}


async def get_rates() -> dict:
    """USD bazlı kurlar: {'USD':1, 'TRY':41.2, 'EUR':0.92, ...}"""
    now = time.time()
    if _cache["rates"] and now - _cache["ts"] < TTL:
        return _cache["rates"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://open.er-api.com/v6/latest/USD")
            r.raise_for_status()
            data = r.json()
            if data.get("result") == "success":
                _cache["rates"] = data["rates"]
                _cache["ts"] = now
                return _cache["rates"]
    except Exception:
        pass
    return _cache["rates"] or FALLBACK


async def to_try(amount: float, currency: str) -> float | None:
    if amount is None:
        return None
    currency = (currency or "TRY").upper()
    if currency == "TRY":
        return amount
    rates = await get_rates()
    if currency not in rates or "TRY" not in rates:
        return None
    usd = amount / rates[currency]
    return usd * rates["TRY"]


async def convert(amount_try: float, target: str) -> float | None:
    """TRY tutarını hedef para birimine çevir."""
    if amount_try is None:
        return None
    target = (target or "TRY").upper()
    if target == "TRY":
        return amount_try
    rates = await get_rates()
    if target not in rates or "TRY" not in rates:
        return None
    usd = amount_try / rates["TRY"]
    return usd * rates[target]
