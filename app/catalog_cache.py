"""Katalog önbelleği — L1 bellek + L2 Redis (opsiyonel).

REDIS_URL ortam değişkeni tanımlıysa (örn. redis://127.0.0.1:6379/0)
Skinport / Waxpeer / rust.tm / CSFloat fiyat listeleri Redis'te tutulur.
Sunucu yeniden başlasa bile önbellek kalır; ilk arama çok daha hızlı olur.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

_memory: dict[str, dict[str, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_redis = None
_backend = "memory"
_init_done = False


@dataclass
class CatalogEntry:
    items: dict
    ts: float
    cooldown_until: float = 0.0

    def fresh(self, ttl: float, now: float | None = None) -> bool:
        now = now or time.time()
        return bool(self.items) and (now - self.ts) < ttl

    def in_cooldown(self, now: float | None = None) -> bool:
        now = now or time.time()
        return bool(self.items) and now < self.cooldown_until


def backend() -> str:
    return _backend


def lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _entry_from_raw(data: dict[str, Any]) -> CatalogEntry | None:
    items = data.get("items")
    if not isinstance(items, dict) or not items:
        return None
    return CatalogEntry(
        items=items,
        ts=float(data.get("ts") or 0),
        cooldown_until=float(data.get("cooldown_until") or 0),
    )


def _to_raw(entry: CatalogEntry) -> dict[str, Any]:
    return {
        "items": entry.items,
        "ts": entry.ts,
        "cooldown_until": entry.cooldown_until,
    }


async def init() -> str:
    """Redis bağlantısını dene; backend adını döndür."""
    global _init_done
    if not _init_done:
        await _connect_redis()
        _init_done = True
    return _backend


async def close() -> None:
    global _redis, _init_done
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
    _init_done = False


async def _connect_redis() -> None:
    global _redis, _backend
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        _backend = "memory"
        return
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(url, decode_responses=True)
        await client.ping()
        _redis = client
        _backend = "redis"
    except Exception:
        _redis = None
        _backend = "memory"


async def get(key: str) -> CatalogEntry | None:
    mem = _memory.get(key)
    if mem:
        entry = _entry_from_raw(mem)
        if entry:
            return entry

    if _redis is None:
        return None
    try:
        raw = await _redis.get(f"catalog:{key}")
        if not raw:
            return None
        data = json.loads(raw)
        entry = _entry_from_raw(data)
        if entry:
            _memory[key] = data
        return entry
    except Exception:
        return None


async def put(key: str, items: dict, ttl: int = 300) -> None:
    entry = CatalogEntry(items=items, ts=time.time(), cooldown_until=0.0)
    raw = _to_raw(entry)
    _memory[key] = raw
    if _redis is None:
        return
    try:
        await _redis.set(f"catalog:{key}", json.dumps(raw), ex=ttl)
    except Exception:
        pass


async def set_cooldown(key: str, seconds: int) -> None:
    until = time.time() + seconds
    mem = _memory.get(key)
    if mem:
        mem["cooldown_until"] = until
    elif _redis is not None:
        try:
            raw = await _redis.get(f"catalog:{key}")
            if raw:
                mem = json.loads(raw)
                mem["cooldown_until"] = until
                _memory[key] = mem
        except Exception:
            return
    else:
        return

    if _redis is None or mem is None:
        return
    try:
        ttl = await _redis.ttl(f"catalog:{key}")
        ex = max(ttl, seconds) if ttl and ttl > 0 else seconds
        await _redis.set(f"catalog:{key}", json.dumps(mem), ex=ex)
    except Exception:
        pass
