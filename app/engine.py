"""Fiyat toplama döngüsü ve alarm motoru."""
from __future__ import annotations
import asyncio
import datetime as dt

import httpx

from . import fx, telegram
from .db import enabled_sources_for, get_conn, get_settings
from .games import GAMES
from .itemname import norm, parse_item_name
from .sources import skinport
from .sources.skinport import CS2_APP_ID, RUST_APP_ID

status: dict = {"last_run": None, "running": False, "errors": {}, "next_run": None}


def source_labels(game: str = "cs2") -> dict:
    return {k: v["label"] for k, v in GAMES.get(game, GAMES["cs2"])["sources"].items()}


SOURCE_LABELS = source_labels("cs2")


def _source_fetch(src: dict, key: str, client, parsed, settings: dict):
    fn = src.get("fetch") or src["module"].fetch
    if key == "bitskins":
        return fn(client, parsed, settings.get("bitskins_api_key", ""))
    return fn(client, parsed)


async def fetch_item_prices(
    client: httpx.AsyncClient,
    name: str,
    settings: dict,
    game: str = "cs2",
) -> list:
    if game == "ko":
        from .ko_item import parse_ko_item

        parsed = parse_ko_item(name)
    else:
        parsed = parse_item_name(name)
    game_cfg = GAMES.get(game, GAMES["cs2"])
    sources = game_cfg["sources"]
    enabled = enabled_sources_for(settings, game)
    tasks, keys = [], []
    for key in enabled:
        if key not in sources:
            continue
        tasks.append(_source_fetch(sources[key], key, client, parsed, settings))
        keys.append(key)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for key, r in zip(keys, results):
        if isinstance(r, Exception):
            from .sources.base import PriceResult
            r = PriceResult(source=key, error=f"{type(r).__name__}: {r}"[:200])
        out.append(r)
    return out


_WEAR_ORDER = ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]


def _variant_sort_key(name: str):
    p = parse_item_name(name)
    wear_idx = _WEAR_ORDER.index(p.wear) if p.wear in _WEAR_ORDER else len(_WEAR_ORDER)
    return (p.stattrak, p.souvenir, wear_idx, name)


def _name_matches(target: str, name: str, game: str) -> bool:
    n = norm(parse_item_name(name).base_name)
    if game == "rust":
        return n == target or n.startswith(target + " ") or target.startswith(n + " ")
    return n == target


async def _resolve_from_skinport(client, target: str, game: str, app_id: int) -> set[str]:
    out: set[str] = set()
    try:
        items = await skinport._get_items(client, app_id=app_id)
        for name in items:
            if _name_matches(target, name, game):
                out.add(name)
    except Exception as e:
        status["errors"]["resolve_skinport"] = f"{type(e).__name__}: {e}"[:200]
    return out


async def _resolve_from_rust_tm(client, target: str) -> set[str]:
    out: set[str] = set()
    try:
        from .sources import rust_tm
        items = await rust_tm._get_items(client)
        for name in items:
            if _name_matches(target, name, "rust"):
                out.add(name)
    except Exception as e:
        status["errors"]["resolve_rust_tm"] = f"{type(e).__name__}: {e}"[:200]
    return out


async def _resolve_from_waxpeer(client, target: str) -> set[str]:
    out: set[str] = set()
    try:
        from .sources import waxpeer
        items = await waxpeer._get_items(client)
        for name in items:
            if _name_matches(target, name, "rust"):
                out.add(name)
    except Exception as e:
        status["errors"]["resolve_waxpeer"] = f"{type(e).__name__}: {e}"[:200]
    return out


async def _resolve_from_dmarket(client, target: str, game: str, base_name: str) -> set[str]:
    out: set[str] = set()
    try:
        from .sources.dmarket import API, CS2_GAME_ID, RUST_GAME_ID
        gid = RUST_GAME_ID if game == "rust" else CS2_GAME_ID
        r = await client.get(
            API,
            params={
                "gameId": gid,
                "title": base_name,
                "limit": 100,
                "currency": "USD",
                "orderBy": "price",
                "orderDir": "asc",
            },
            timeout=30,
        )
        r.raise_for_status()
        for o in r.json().get("objects", []):
            title = o.get("title", "")
            if title and _name_matches(target, title, game):
                out.add(title)
    except Exception as e:
        status["errors"]["resolve_dmarket"] = f"{type(e).__name__}: {e}"[:200]
    return out


async def resolve_variants(query: str, game: str = "cs2") -> dict:
    if game == "ko":
        return await _resolve_ko_variants(query)

    parsed = parse_item_name(query)
    target = norm(parsed.base_name)
    variants: set[str] = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        app_id = RUST_APP_ID if game == "rust" else CS2_APP_ID
        tasks = [_resolve_from_skinport(client, target, game, app_id)]
        if game == "rust":
            tasks.append(_resolve_from_rust_tm(client, target))
            tasks.append(_resolve_from_waxpeer(client, target))
        else:
            tasks.append(_resolve_from_dmarket(client, target, game, parsed.base_name))

        if game == "rust":
            # DMarket ayrı; Skinport + rust.tm + Waxpeer paralel
            parts = await asyncio.gather(*tasks)
            for part in parts:
                variants |= part
            if not variants:
                variants |= await _resolve_from_dmarket(client, target, game, parsed.base_name)
        else:
            parts = await asyncio.gather(tasks[0], tasks[1])
            variants |= parts[0]
            if not variants:
                variants |= parts[1]

    if not variants:
        return {"resolved": query}

    filtered = variants
    if parsed.wear:
        filtered = {v for v in filtered if parse_item_name(v).wear == parsed.wear}
    if parsed.stattrak:
        filtered = {v for v in filtered if parse_item_name(v).stattrak}
    if parsed.souvenir:
        filtered = {v for v in filtered if parse_item_name(v).souvenir}
    if filtered:
        variants = filtered

    if query in variants:
        return {"resolved": query}
    if len(variants) == 1:
        return {"resolved": next(iter(variants))}
    return {"variants": sorted(variants, key=_variant_sort_key)}


async def _resolve_ko_variants(query: str) -> dict:
    from .ko_item import (
        canonical_ko_title,
        ko_listing_matches,
        ko_plus_level_matches,
        parse_ko_item,
        resolve_keywords,
    )
    from .sources.kopazar import search_ko_listings

    parsed = parse_ko_item(query)
    strict: set[str] = set()
    loose: set[str] = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            for kw in resolve_keywords(parsed):
                probe = parse_ko_item(kw)
                rows = await search_ko_listings(client, probe)
                for row in rows:
                    title = row["title"]
                    if not ko_plus_level_matches(parsed, title):
                        continue
                    canon = canonical_ko_title(title)
                    loose.add(canon)
                    if ko_listing_matches(parsed, title):
                        strict.add(canon)
        except Exception as e:
            status["errors"]["resolve_kopazar_ko"] = f"{type(e).__name__}: {e}"[:200]

    variants = loose or strict
    if not variants:
        return {"resolved": query}
    if query in variants:
        return {"resolved": query}
    if len(variants) == 1:
        return {"resolved": next(iter(variants))}
    return {"variants": sorted(variants)}


async def run_cycle() -> dict:
    if status["running"]:
        return {"ok": False, "msg": "zaten çalışıyor"}
    status["running"] = True
    try:
        settings = get_settings()
        with get_conn() as conn:
            items = conn.execute("SELECT * FROM items ORDER BY id").fetchall()

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for item in items:
                await _fetch_and_store(client, item, settings)
                await asyncio.sleep(0.5)

        status["last_run"] = dt.datetime.now().isoformat(timespec="seconds")
        return {"ok": True}
    finally:
        status["running"] = False


async def refresh_item(item_id: int) -> dict:
    """Tek ürün için fiyat çek — arama sonrası hızlı güncelleme."""
    if status["running"]:
        return {"ok": False, "msg": "tam tarama sürüyor, biraz bekle"}
    status["running"] = True
    try:
        settings = get_settings()
        with get_conn() as conn:
            item = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            return {"ok": False, "msg": "item bulunamadı"}
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await _fetch_and_store(client, item, settings)
        status["last_run"] = dt.datetime.now().isoformat(timespec="seconds")
        return {"ok": True}
    finally:
        status["running"] = False


async def _fetch_and_store(client: httpx.AsyncClient, item, settings: dict):
    game = item["game"] if "game" in item.keys() else "cs2"
    results = await fetch_item_prices(client, item["name"], settings, game=game)
    with get_conn() as conn:
        for r in results:
            price_try = await fx.to_try(r.price, r.currency) if r.price else None
            conn.execute(
                "INSERT INTO prices(item_id, source, price_orig, currency, price_try, url, error) "
                "VALUES(?,?,?,?,?,?,?)",
                (item["id"], r.source, r.price, r.currency, price_try, r.url, r.error),
            )
    await check_alerts(item, settings)


def latest_prices(item_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.* FROM prices p
               JOIN (SELECT source, MAX(id) mid FROM prices WHERE item_id=? GROUP BY source) x
               ON p.id = x.mid""",
            (item_id,),
        ).fetchall()
    return {r["source"]: dict(r) for r in rows}


def spread_info(prices: dict) -> dict | None:
    vals = {s: p["price_try"] for s, p in prices.items() if p.get("price_try")}
    if len(vals) < 2:
        return None
    lo_src = min(vals, key=vals.get)
    hi_src = max(vals, key=vals.get)
    lo, hi = vals[lo_src], vals[hi_src]
    return {
        "low_source": lo_src, "low": lo,
        "high_source": hi_src, "high": hi,
        "spread_pct": (hi - lo) / lo * 100 if lo else 0,
    }


async def opportunities(
    min_spread_pct: float = 5.0,
    min_discount_pct: float = 15.0,
    min_price_try: float = 50.0,
    limit: int = 40,
    game: str = "cs2",
) -> dict:
    labels = source_labels(game)
    spreads = []
    with get_conn() as conn:
        items = conn.execute(
            "SELECT * FROM items WHERE game=? ORDER BY id", (game,)
        ).fetchall()
    for item in items:
        prices = latest_prices(item["id"])
        sp = spread_info(prices)
        if not sp or sp["spread_pct"] < min_spread_pct:
            continue
        spreads.append({
            "item_id": item["id"],
            "name": item["name"],
            "low_source": sp["low_source"],
            "low_label": labels.get(sp["low_source"], sp["low_source"]),
            "low": sp["low"],
            "low_url": prices.get(sp["low_source"], {}).get("url"),
            "high_source": sp["high_source"],
            "high_label": labels.get(sp["high_source"], sp["high_source"]),
            "high": sp["high"],
            "high_url": prices.get(sp["high_source"], {}).get("url"),
            "spread_pct": sp["spread_pct"],
            "diff": sp["high"] - sp["low"],
        })
    spreads.sort(key=lambda x: x["spread_pct"], reverse=True)

    discounts = []
    if game == "cs2":
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                catalog = await skinport._get_items(client, app_id=CS2_APP_ID)
            for name, it in catalog.items():
                mp = it.get("min_price")
                sug = it.get("suggested_price")
                qty = it.get("quantity") or 0
                if not mp or not sug or qty <= 0 or mp < min_price_try:
                    continue
                pct = (sug - mp) / sug * 100
                if pct < min_discount_pct:
                    continue
                discounts.append({
                    "name": name,
                    "price": mp,
                    "suggested": sug,
                    "discount_pct": pct,
                    "quantity": qty,
                    "url": it.get("item_page"),
                })
            discounts.sort(key=lambda x: x["discount_pct"], reverse=True)
            discounts = discounts[:limit]
        except Exception as e:
            status["errors"]["opportunities"] = f"{type(e).__name__}: {e}"[:200]

    return {"spreads": spreads[:limit], "discounts": discounts}


async def check_alerts(item, settings: dict):
    game = item["game"] if "game" in item.keys() else "cs2"
    labels = source_labels(game)
    prices = latest_prices(item["id"])
    sp = spread_info(prices)
    now = dt.datetime.now()

    with get_conn() as conn:
        alerts = conn.execute(
            "SELECT * FROM alerts WHERE item_id=? AND enabled=1", (item["id"],)
        ).fetchall()

    for alert in alerts:
        if alert["last_triggered_at"]:
            last = dt.datetime.fromisoformat(alert["last_triggered_at"])
            if (now - last).total_seconds() < alert["cooldown_min"] * 60:
                continue

        msg = None
        if alert["kind"] in ("below", "above"):
            if alert["source"]:
                p = prices.get(alert["source"], {}).get("price_try")
                src_label = labels.get(alert["source"], alert["source"])
            else:
                cands = {s: p["price_try"] for s, p in prices.items() if p.get("price_try")}
                if not cands:
                    continue
                src = min(cands, key=cands.get)
                p = cands[src]
                src_label = labels.get(src, src)
            if p is None:
                continue
            if alert["kind"] == "below" and p <= alert["threshold"]:
                msg = (f"📉 <b>{item['name']}</b>\n"
                       f"{src_label}: <b>{tl(p)} TL</b> — eşik {tl(alert['threshold'])} TL altına indi!")
            elif alert["kind"] == "above" and p >= alert["threshold"]:
                msg = (f"📈 <b>{item['name']}</b>\n"
                       f"{src_label}: <b>{tl(p)} TL</b> — eşik {tl(alert['threshold'])} TL üzerine çıktı!")

        elif alert["kind"] == "spread" and sp:
            if sp["spread_pct"] >= alert["threshold"]:
                msg = (f"⚖️ <b>{item['name']}</b> arbitraj fırsatı!\n"
                       f"En ucuz: {labels.get(sp['low_source'])} — {tl(sp['low'])} TL\n"
                       f"En pahalı: {labels.get(sp['high_source'])} — {tl(sp['high'])} TL\n"
                       f"Fark: <b>%{sp['spread_pct']:.1f}</b> (eşik %{alert['threshold']:g})")

        if msg:
            ok, info = await telegram.send_message(
                settings.get("telegram_token", ""), settings.get("telegram_chat_id", ""), msg
            )
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO notifications(alert_id, message, sent_ok) VALUES(?,?,?)",
                    (alert["id"], msg, 1 if ok else 0),
                )
                conn.execute(
                    "UPDATE alerts SET last_triggered_at=? WHERE id=?",
                    (now.isoformat(timespec="seconds"), alert["id"]),
                )


def tl(v: float) -> str:
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


async def scheduler_loop():
    await asyncio.sleep(3)
    while True:
        try:
            await run_cycle()
        except Exception as e:
            status["errors"]["cycle"] = f"{type(e).__name__}: {e}"[:300]
        try:
            interval = max(1, int(float(get_settings().get("check_interval_min", "5"))))
        except ValueError:
            interval = 5
        status["next_run"] = (
            dt.datetime.now() + dt.timedelta(minutes=interval)
        ).isoformat(timespec="seconds")
        await asyncio.sleep(interval * 60)
