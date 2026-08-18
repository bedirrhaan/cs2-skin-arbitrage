"""Fiyat toplama döngüsü ve alarm motoru."""
from __future__ import annotations
import asyncio
import datetime as dt
import json

import httpx

from . import fx, telegram
from .catalog import week_sale_stats
from .db import enabled_sources_for, get_conn, get_settings, top_popular_names
from .games import GAMES
from .itemname import cs2_wear_variants, norm, parse_item_name
from .sources import skinport
from .sources.base import PriceResult, short_error
from .sources.skinport import CS2_APP_ID, RUST_APP_ID

status: dict = {
    "last_run": None,
    "running": False,
    "errors": {},
    "next_run": None,
    "popular_running": False,
    "popular_game": None,
    "popular": {},
}

SOURCE_TIMEOUT = 22.0


def source_labels(game: str = "cs2") -> dict:
    return {k: v["label"] for k, v in GAMES.get(game, GAMES["cs2"])["sources"].items()}


SOURCE_LABELS = source_labels("cs2")


def _source_fetch(src: dict, key: str, client, parsed, settings: dict):
    fn = src.get("fetch") or src["module"].fetch
    if key == "bitskins":
        return fn(client, parsed, settings.get("bitskins_api_key", ""))
    return fn(client, parsed)


def _price_tasks(client, name: str, settings: dict, game: str):
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
    return tasks, keys


async def _run_source(key: str, coro):
    try:
        return await asyncio.wait_for(coro, SOURCE_TIMEOUT)
    except asyncio.TimeoutError:
        return PriceResult(source=key, error="zaman aşımı — site yavaş yanıt verdi")
    except Exception as e:
        return PriceResult(source=key, error=short_error(e))


async def iter_item_prices(client, name: str, settings: dict, game: str = "cs2"):
    tasks, keys = _price_tasks(client, name, settings, game)
    wrapped = [asyncio.create_task(_run_source(k, t)) for k, t in zip(keys, tasks)]
    for fut in asyncio.as_completed(wrapped):
        yield await fut


async def fetch_item_prices(
    client: httpx.AsyncClient,
    name: str,
    settings: dict,
    game: str = "cs2",
) -> list:
    out = []
    async for r in iter_item_prices(client, name, settings, game):
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
        from .sources.dmarket import CS2_GAME_ID, RUST_GAME_ID, cheapest_offer_usd
        gid = RUST_GAME_ID if game == "rust" else CS2_GAME_ID
        for title in {base_name}:
            if not title:
                continue
            price = await cheapest_offer_usd(client, title, gid)
            if price is not None and _name_matches(target, title, game):
                out.add(title)
    except Exception as e:
        status["errors"]["resolve_dmarket"] = f"{type(e).__name__}: {e}"[:200]
    return out


async def resolve_variants(query: str, game: str = "cs2") -> dict:
    if game == "ko":
        return await _resolve_ko_variants(query)

    parsed = parse_item_name(query)
    if game == "cs2":
        local = cs2_wear_variants(parsed)
        if len(local) > 1:
            return {"variants": local}
        if len(local) == 1:
            return {"resolved": local[0]}

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
            items = [dict(r) for r in conn.execute("SELECT * FROM items ORDER BY id").fetchall()]

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for item in items:
                await _fetch_and_store(client, item, settings)
                await asyncio.sleep(0.5)

        status["last_run"] = dt.datetime.now().isoformat(timespec="seconds")
        return {"ok": True}
    finally:
        status["running"] = False


async def refresh_item(item_id: int) -> dict:
    """Tek ürün için fiyat çek — arka plan taramasını beklemez."""
    settings = get_settings()
    with get_conn() as conn:
        item = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        return {"ok": False, "msg": "item bulunamadı"}
    item = dict(item)
    async with httpx.AsyncClient(follow_redirects=True, timeout=SOURCE_TIMEOUT) as client:
        await _fetch_and_store(client, item, settings)
    status["last_run"] = dt.datetime.now().isoformat(timespec="seconds")
    return {"ok": True}


async def _store_one_price(item: dict, game: str, r) -> None:
    price_try = await fx.to_try(r.price, r.currency) if r.price else None
    offers_out = []
    for o in r.offers or []:
        op = o.get("price")
        ot = await fx.to_try(op, r.currency) if op is not None else None
        if ot is None:
            continue
        offers_out.append({
            "price_try": round(float(ot), 2),
            "url": o.get("url"),
            "price_orig": op,
            "currency": r.currency,
        })
        if price_try is None:
            price_try = float(ot)
    if offers_out and (price_try is None or (r.price is None and offers_out)):
        price_try = offers_out[0]["price_try"]
        if not r.url:
            r.url = offers_out[0].get("url")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO prices(item_id, source, price_orig, currency, price_try, url, error, offers) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                item["id"], r.source, r.price, r.currency, price_try, r.url, r.error,
                json.dumps(offers_out) if offers_out else None,
            ),
        )
        if price_try is not None:
            conn.execute(
                "INSERT INTO price_history(game, name, source, price_try) VALUES(?,?,?,?)",
                (game, item["name"], r.source, price_try),
            )


async def _fetch_and_store(client: httpx.AsyncClient, item, settings: dict):
    game = item["game"] if "game" in item.keys() else "cs2"
    async for r in iter_item_prices(client, item["name"], settings, game=game):
        try:
            await _store_one_price(item, game, r)
        except Exception as e:
            status["errors"]["store"] = f"{type(e).__name__}: {e}"[:200]
    await check_alerts(item, settings)


def latest_prices(item_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.* FROM prices p
               JOIN (SELECT source, MAX(id) mid FROM prices WHERE item_id=? GROUP BY source) x
               ON p.id = x.mid""",
            (item_id,),
        ).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        raw = d.get("offers")
        if isinstance(raw, str) and raw.strip():
            try:
                d["offers"] = json.loads(raw)
            except json.JSONDecodeError:
                d["offers"] = []
        elif not raw:
            d["offers"] = []
        out[r["source"]] = d
    return out


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


def _median(vals: list[float]) -> float | None:
    nums = sorted(v for v in vals if v and v > 0)
    if not nums:
        return None
    n = len(nums)
    if n % 2:
        return nums[n // 2]
    return (nums[n // 2 - 1] + nums[n // 2]) / 2


def _market_rows(prices: dict, labels: dict, low_src: str) -> list[dict]:
    rows = []
    for src, p in (prices or {}).items():
        if not p or p.get("price_try") is None:
            continue
        try:
            price = float(p["price_try"])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        rows.append({
            "source": src,
            "label": labels.get(src, src),
            "price": round(price, 2),
            "url": p.get("url"),
            "is_low": src == low_src,
        })
    rows.sort(key=lambda x: x["price"])
    return rows


def judge_deal(game: str, name: str, prices: dict, min_pct: float = 8.0) -> dict | None:
    """Referans pazar + 1 haftalık satış ortalamasına bakıp güncel en ucuzu fırsat sayar."""
    labels = source_labels(game)
    live = {
        s: float(p["price_try"])
        for s, p in (prices or {}).items()
        if p and p.get("price_try")
    }
    if not live:
        return None
    low_src = min(live, key=live.get)
    low = live[low_src]
    steam = live.get("steam")
    ref_src = "steam" if game != "ko" else "bynogame"
    ref_price = live.get(ref_src)
    ref_label = labels.get(ref_src, "ByNoGame" if game == "ko" else "Steam")
    hist = week_sale_stats(game, name)
    reasons = []
    vs_steam = None
    vs_hist = None
    if ref_price and ref_price > 0 and low + 0.01 < ref_price:
        vs_steam = round((ref_price - low) / ref_price * 100, 1)
        if vs_steam >= min_pct:
            reasons.append("steam")
    week_avg = hist.get("week_avg")
    week_n = int(hist.get("week_n") or 0)
    if week_avg and week_n >= 3 and low + 0.01 < week_avg:
        vs_hist = round((week_avg - low) / week_avg * 100, 1)
        if vs_hist >= min_pct:
            reasons.append("history")
    sp = spread_info(prices)
    if sp and sp["spread_pct"] >= min_pct:
        reasons.append("spread")
    if not reasons:
        return None
    hi_src = max(live, key=live.get)
    others = [v for s, v in live.items() if s != low_src]
    market_band = _median(others) or _median(list(live.values()))
    was_price = None
    if week_avg and week_avg > low:
        was_price = float(week_avg)
    elif market_band and market_band > low:
        was_price = float(market_band)
    discount_pct = 0.0
    if was_price and was_price > 0:
        discount_pct = (was_price - low) / was_price * 100
    return {
        "name": name,
        "reasons": reasons,
        "low_source": low_src,
        "low_label": labels.get(low_src, low_src),
        "low": round(low, 2),
        "low_url": (prices.get(low_src) or {}).get("url"),
        "high_source": hi_src,
        "high_label": labels.get(hi_src, hi_src),
        "high": round(live[hi_src], 2),
        "high_url": (prices.get(hi_src) or {}).get("url"),
        "spread_pct": sp["spread_pct"] if sp else 0,
        "diff": round(live[hi_src] - low, 2) if live[hi_src] else 0,
        "steam": steam if game != "ko" else None,
        "vs_steam": vs_steam if game != "ko" else None,
        "ref_price": ref_price,
        "ref_label": ref_label,
        "vs_ref": vs_steam,
        "week_avg": week_avg,
        "week_n": week_n,
        "week_label": hist.get("week_label"),
        "vs_hist": vs_hist,
        "was_price": round(was_price, 2) if was_price else None,
        "market_band": round(market_band, 2) if market_band else None,
        "discount_pct": round(discount_pct, 1),
        "markets": _market_rows(prices, labels, low_src),
    }


def cheapest_three(prices: dict, labels: dict | None = None, n: int = 3) -> list[dict]:
    """En ucuz n pazar; her sırada bir öncekine TL farkı."""
    labels = labels or {}
    ranked = []
    for src, p in prices.items():
        price = p.get("price_try")
        if price is None:
            continue
        ranked.append({
            "rank": 0,
            "source": src,
            "label": labels.get(src, src),
            "price": float(price),
            "url": p.get("url"),
            "diff_prev": None,
        })
    ranked.sort(key=lambda x: x["price"])
    ranked = ranked[:n]
    for i, row in enumerate(ranked):
        row["rank"] = i + 1
        if i > 0:
            row["diff_prev"] = round(row["price"] - ranked[i - 1]["price"], 2)
    return ranked


async def _live_prices(client, name: str, settings: dict, game: str) -> dict:
    """Item tablosuna yazmadan canlı fiyat çek."""
    out = {}
    async for r in iter_item_prices(client, name, settings, game=game):
        price_try = await fx.to_try(r.price, r.currency) if r.price else None
        offers_out = []
        for o in r.offers or []:
            op = o.get("price")
            ot = await fx.to_try(op, r.currency) if op is not None else None
            if ot is None:
                continue
            offers_out.append({
                "price_try": round(float(ot), 2),
                "url": o.get("url"),
            })
            if price_try is None:
                price_try = float(ot)
        out[r.source] = {
            "price_try": price_try,
            "url": r.url,
            "error": r.error,
            "offers": offers_out,
        }
    return out


async def live_price_payload(name: str, game: str) -> dict:
    settings = get_settings()
    try:
        min_pct = float(settings.get("popular_min_spread") or 8)
    except ValueError:
        min_pct = 8.0
    async with httpx.AsyncClient(follow_redirects=True, timeout=SOURCE_TIMEOUT) as client:
        prices = await _live_prices(client, name, settings, game)
    return {
        "sources": source_labels(game),
        "prices": prices,
        "spread": spread_info(prices),
        "deal": judge_deal(game, name, prices, min_pct),
        "name": name,
        "game": game,
    }


def popular_status(game: str) -> dict:
    d = dict(status.get("popular", {}).get(game) or {
        "hits": [], "scanned": [], "progress": 0, "total": 0, "limit": 20,
        "min_spread": 8, "at": None,
    })
    d["running"] = bool(status.get("popular_running") and status.get("popular_game") == game)
    d["ok"] = True
    return d


async def start_popular_scan(
    game: str, limit: int = 20, min_spread: float = 8.0, notify: bool = True
) -> dict:
    if status.get("popular_running"):
        cur = popular_status(game)
        cur["msg"] = "tarama sürüyor"
        return cur
    asyncio.create_task(scan_popular(game, limit, min_spread, notify))
    return popular_status(game) | {"running": True, "ok": True}


async def scan_popular(
    game: str,
    limit: int = 20,
    min_spread: float = 8.0,
    notify: bool = True,
) -> dict:
    if status.get("popular_running"):
        return popular_status(game)
    status["popular_running"] = True
    status["popular_game"] = game
    limit = min(max(int(limit or 20), 5), 25)
    min_spread = max(float(min_spread or 0), 0)
    if game == "ko":
        try:
            from .catalog import seed_ko_catalog
            await seed_ko_catalog(limit)
        except Exception as e:
            status["errors"]["ko_catalog"] = f"{type(e).__name__}: {e}"[:200]
    rows = top_popular_names(game, limit)
    payload = {
        "hits": [],
        "scanned": [r["name"] for r in rows],
        "progress": 0,
        "total": len(rows),
        "limit": limit,
        "min_spread": min_spread,
        "at": None,
        "game": game,
    }
    status["popular"][game] = payload
    settings = get_settings()
    hits = []
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=SOURCE_TIMEOUT) as client:
            for row in rows:
                prices = await _live_prices(client, row["name"], settings, game)
                payload["progress"] += 1
                status["popular"][game] = payload
                deal = judge_deal(game, row["name"], prices, min_spread)
                if not deal:
                    continue
                hit = {
                    "rank": row["rank"],
                    "in_list": row["in_list"],
                    "in_depo": row["in_depo"],
                    **deal,
                }
                hits.append(hit)
                hits.sort(key=lambda h: float(h.get("discount_pct") or h.get("spread_pct") or 0), reverse=True)
                payload["hits"] = hits
                status["popular"][game] = payload
                if notify:
                    await _notify_popular(game, hit, settings)
                await asyncio.sleep(0.35)
        payload["at"] = dt.datetime.now().isoformat(timespec="seconds")
        hits.sort(key=lambda h: float(h.get("discount_pct") or h.get("spread_pct") or 0), reverse=True)
        payload["hits"] = hits
        status["popular"][game] = payload
        return popular_status(game)
    except Exception as e:
        status["errors"]["popular"] = f"{type(e).__name__}: {e}"[:200]
        payload["error"] = status["errors"]["popular"]
        status["popular"][game] = payload
        return popular_status(game)
    finally:
        status["popular_running"] = False
        status["popular_game"] = None


POPULAR_COOLDOWN_H = 6


async def _notify_popular(game: str, hit: dict, settings: dict) -> None:
    now = dt.datetime.now()
    with get_conn() as conn:
        prev = conn.execute(
            "SELECT last_notified_at FROM popular_hits WHERE game=? AND name=?",
            (game, hit["name"]),
        ).fetchone()
    if prev and prev["last_notified_at"]:
        try:
            last = dt.datetime.fromisoformat(prev["last_notified_at"])
            if (now - last).total_seconds() < POPULAR_COOLDOWN_H * 3600:
                return
        except ValueError:
            pass
    where = "listende yok" if not hit.get("in_list") else "listende var"
    bits = []
    if hit.get("steam"):
        bits.append(f"Steam: {tl(hit['steam'])} TL")
    elif hit.get("ref_price") and hit.get("ref_label"):
        bits.append(f"{hit['ref_label']}: {tl(hit['ref_price'])} TL")
    if hit.get("week_avg") and hit.get("week_n"):
        bits.append(
            f"1 hafta ort. ({hit.get('week_label') or 'pazar'}, {hit['week_n']} satış): {tl(hit['week_avg'])} TL"
        )
    ref = ("\n" + " · ".join(bits)) if bits else ""
    others_txt = ""
    markets = [m for m in (hit.get("markets") or []) if not m.get("is_low")]
    if markets:
        others_txt = "\nDiğer siteler: " + " · ".join(
            f"{m['label']} {tl(m['price'])} TL" for m in markets[:6]
        )
    was = hit.get("was_price")
    disc = hit.get("discount_pct") or 0
    drop = ""
    if was and disc:
        drop = f"\nNormalde {tl(was)} TL → şu an {tl(hit['low'])} TL (−%{disc:.0f})"
    msg = (
        f"🔥 Popüler indirim (#{hit.get('rank', '?')}) — {game.upper()}\n"
        f"<b>{hit['name']}</b>{ref}\n"
        f"{hit['low_label']}: <b>{tl(hit['low'])} TL</b>{drop}{others_txt}\n"
        f"{where}"
    )
    await telegram.send_message(
        settings.get("telegram_token", ""), settings.get("telegram_chat_id", ""), msg
    )
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO popular_hits(game, name, last_notified_at) VALUES(?,?,?) "
            "ON CONFLICT(game, name) DO UPDATE SET last_notified_at=excluded.last_notified_at",
            (game, hit["name"], now.isoformat(timespec="seconds")),
        )


async def scan_popular_all(notify: bool = True) -> None:
    settings = get_settings()
    try:
        limit = int(float(settings.get("popular_top_n") or 20))
    except ValueError:
        limit = 20
    try:
        min_spread = float(settings.get("popular_min_spread") or 8)
    except ValueError:
        min_spread = 8.0
    for game in GAMES:
        await scan_popular(game, limit, min_spread, notify=notify)


async def opportunities(
    min_spread_pct: float = 8.0,
    min_discount_pct: float = 15.0,
    min_price_try: float = 50.0,
    limit: int = 20,
    game: str = "cs2",
) -> dict:
    """Eski uç: son popüler tarama sonucunu döner."""
    return popular_status(game)


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
    # Panel önce açılsın; ilk tarama arayüzü kilitlemesin.
    await asyncio.sleep(20)
    while True:
        try:
            await run_cycle()
        except Exception as e:
            status["errors"]["cycle"] = f"{type(e).__name__}: {e}"[:300]
        try:
            from .catalog import snapshot_catalogs
            await snapshot_catalogs()
        except Exception as e:
            status["errors"]["catalog_snapshot"] = f"{type(e).__name__}: {e}"[:300]
        try:
            await scan_popular_all(notify=True)
        except Exception as e:
            status["errors"]["popular"] = f"{type(e).__name__}: {e}"[:300]
        try:
            interval = max(1, int(float(get_settings().get("check_interval_min", "5"))))
        except ValueError:
            interval = 5
        status["next_run"] = (
            dt.datetime.now() + dt.timedelta(minutes=interval)
        ).isoformat(timespec="seconds")
        await asyncio.sleep(interval * 60)
