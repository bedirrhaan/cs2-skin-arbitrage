"""Oyun katalogları: yerel SQLite + arka plan senkron (Skinport/CSFloat/ByNoGame)."""
from __future__ import annotations

import asyncio
import datetime as dt
import time

import httpx

from . import fx
from .db import (
    catalog_count,
    catalog_names_by_price,
    catalog_ranked_count,
    catalog_updated_at,
    get_conn,
    query_catalog,
    record_history_bulk,
    replace_priced_history,
    tracked_names,
    update_catalog_trends,
    upsert_catalog,
)
from .sources.skinport import CS2_APP_ID, RUST_APP_ID, SkinportRateLimited, _get_items

_last_hourly = 0.0
_last_daily = 0.0
_syncing: set[str] = set()
_last_full_sync: dict[str, float] = {}
_ranking: set[str] = set()
_last_rank: dict[str, float] = {}


def _skinport_price(row: dict) -> float | None:
    qty = row.get("quantity") or 0
    p = row.get("min_price")
    if qty and p is not None:
        try:
            return float(p)
        except (TypeError, ValueError):
            return None
    sug = row.get("suggested_price")
    if sug is not None:
        try:
            return float(sug)
        except (TypeError, ValueError):
            return None
    return None


def _skinport_rows(game: str, catalog: dict) -> list[tuple]:
    out = []
    for name, row in catalog.items():
        out.append((
            name,
            _skinport_price(row),
            row.get("quantity") or 0,
            row.get("item_page"),
            "skinport",
        ))
    return out


async def _csfloat_rows(client: httpx.AsyncClient) -> list[tuple]:
    from .sources import csfloat
    items = await csfloat._get_items(client)
    try_rate = await fx.to_try(1.0, "USD") or 41.0
    out = []
    for name, row in items.items():
        cents = row.get("min_price")
        qty = row.get("quantity") or 0
        price_try = None
        if cents is not None and qty:
            try:
                price_try = (float(cents) / 100.0) * try_rate
            except (TypeError, ValueError):
                price_try = None
        out.append((
            name,
            price_try,
            qty,
            None,
            "csfloat",
        ))
    return out


async def sync_catalog(game: str, force: bool = False) -> dict:
    """Binlerce ismi SQLite'a yazar. Skinport limitinde CSFloat / ByNoGame dener."""
    if game not in ("cs2", "rust"):
        return {"ok": False, "reason": "skip"}
    if game in _syncing:
        return {"ok": False, "reason": "busy"}
    now = time.time()
    n = catalog_count(game)
    if not force and n > 200 and now - _last_full_sync.get(game, 0) < 6 * 3600:
        return {"ok": True, "reason": "fresh", "count": n}

    _syncing.add(game)
    info: dict = {"ok": False, "game": game, "count": n}
    try:
        app_id = RUST_APP_ID if game == "rust" else CS2_APP_ID
        rows: list[tuple] = []
        source = None
        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                catalog = await _get_items(client, app_id=app_id, currency="TRY")
                rows = _skinport_rows(game, catalog)
                source = "skinport"
            except (SkinportRateLimited, httpx.HTTPStatusError, Exception) as e:
                info["skinport"] = f"{type(e).__name__}"
                if game == "cs2":
                    try:
                        rows = await _csfloat_rows(client)
                        source = "csfloat"
                    except Exception as e2:
                        info["csfloat"] = f"{type(e2).__name__}"
                if not rows:
                    from .sources.bynogame import list_steam_catalog
                    seed = []
                    total = 0
                    for page in range(1, 8):
                        chunk = await list_steam_catalog(
                            client, app_id=app_id, page=page, limit=100
                        )
                        total = chunk.get("total") or total
                        for it in chunk.get("items") or []:
                            seed.append((
                                it["name"],
                                it.get("price_try"),
                                it.get("quantity") or 0,
                                it.get("url"),
                                "bynogame",
                            ))
                        if page * 100 >= total:
                            break
                    rows = seed
                    source = "bynogame"

        if rows:
            written = await asyncio.to_thread(upsert_catalog, game, rows)
            _last_full_sync[game] = time.time()
            info.update(ok=True, source=source, written=written, count=catalog_count(game))
        else:
            info["reason"] = "empty"
        return info
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"[:200]
        return info
    finally:
        _syncing.discard(game)


def _schedule_sync(game: str) -> None:
    if game in _syncing:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(sync_catalog(game))


def _schedule_rank(game: str) -> None:
    if game not in ("cs2", "rust") or game in _ranking:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(rank_catalog_trends(game))


def trend_score(chg_48h, chg_24h) -> float | None:
    """Sadece artış öne. İki periyotta da artı + büyük fark = en üst."""
    c48 = float(chg_48h) if chg_48h is not None else None
    c24 = float(chg_24h) if chg_24h is not None else None
    u48 = max(0.0, c48 or 0.0)
    u24 = max(0.0, c24 or 0.0)
    if u48 <= 0 and u24 <= 0:
        vals = [v for v in (c48, c24) if v is not None]
        return min(vals) if vals else None
    both = c48 is not None and c48 > 0 and c24 is not None and c24 > 0
    return u48 + u24 + (min(u48, u24) if both else 0.0)


def _parse_hist_ts(raw) -> dt.datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        n = float(raw)
        if n > 1e12:
            n /= 1000.0
        try:
            return dt.datetime.utcfromtimestamp(n)
        except (OSError, OverflowError, ValueError):
            return None
    s = str(raw).replace("Z", "").strip()
    if s.replace(".", "", 1).isdigit():
        return _parse_hist_ts(float(s))
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is not None:
        t = t.replace(tzinfo=None)
    return t


def _bucket_key(ts: dt.datetime, bucket: str) -> str:
    if bucket == "hour":
        return ts.replace(minute=0, second=0, microsecond=0).isoformat()
    if bucket == "day":
        return ts.date().isoformat()
    if bucket == "week":
        return (ts.date() - dt.timedelta(days=ts.weekday())).isoformat()
    return f"{ts.year:04d}-{ts.month:02d}"


def _filter_outliers(vals: list[float]) -> list[float]:
    if len(vals) < 3:
        return vals
    mid = sorted(vals)[len(vals) // 2]
    if mid <= 0:
        return vals
    kept = [v for v in vals if mid / 6.0 <= v <= mid * 6.0]
    return kept or vals


SPAN_WINDOWS = {
    "1h": {
        "delta": dt.timedelta(days=10),
        "bucket": "hour",
        "interval": "hourly",
        "fetch_days": 12,
        "min_buckets": 10,
        "sources": ("steam_hourly", "skinport_hourly"),
    },
    "1d": {
        "delta": dt.timedelta(days=14),
        "bucket": "day",
        "interval": "daily",
        "fetch_days": 16,
        "min_buckets": 7,
        "sources": ("steam", "steam_hourly", "skinport_daily"),
    },
    "1w": {
        "delta": dt.timedelta(weeks=8),
        "bucket": "week",
        "interval": "daily",
        "fetch_days": 70,
        "min_buckets": 6,
        "sources": ("steam", "steam_hourly", "skinport_daily"),
    },
    "1m": {
        "delta": dt.timedelta(days=186),
        "bucket": "month",
        "interval": "daily",
        "fetch_days": 190,
        "min_buckets": 5,
        "sources": ("steam", "skinport_daily"),
    },
}


def _pct(now_p, old_p) -> float | None:
    if now_p is None or old_p is None or old_p <= 0:
        return None
    return round((now_p - old_p) / old_p * 100.0, 2)


def changes_from_points(points: list[tuple]) -> tuple:
    if len(points) < 2:
        return None, None
    points = sorted((t, p) for t, p in points if t and p is not None)
    if len(points) < 2:
        return None, None
    last_t, last_p = points[-1]
    t24 = last_t - dt.timedelta(hours=24)
    t48 = last_t - dt.timedelta(hours=48)

    def near(target: dt.datetime, max_h: float):
        best = min(points, key=lambda x: abs((x[0] - target).total_seconds()))
        if abs((best[0] - target).total_seconds()) > max_h * 3600:
            return None
        return best[1]

    p24 = near(t24, 10)
    p48 = near(t48, 16)
    if p24 is None:
        for t, p in reversed(points[:-1]):
            if (last_t - t).total_seconds() >= 16 * 3600:
                p24 = p
                break
        if p24 is None:
            p24 = points[-2][1]
    if p48 is None and (last_t - points[0][0]).total_seconds() >= 30 * 3600:
        p48 = points[0][1]
    return _pct(last_p, p24), _pct(last_p, p48)


OPENSKIN_BATCH = "https://api.openskin.dev/v1/history/batch"


async def rank_catalog_trends(game: str, force: bool = False) -> dict:
    """Steam 48s / 1g değişimine göre katalog sırası."""
    if game not in ("cs2", "rust"):
        return {"ok": False}
    if game in _ranking:
        return {"ok": False, "reason": "busy"}
    now = time.time()
    if not force and now - _last_rank.get(game, 0) < 6 * 3600 and catalog_ranked_count(game) > 200:
        return {"ok": True, "reason": "fresh"}
    names = catalog_names_by_price(game)
    if not names:
        return {"ok": False, "reason": "empty"}
    _ranking.add(game)
    done = 0
    try:
        from .sources.base import USER_AGENT
        start = (dt.datetime.utcnow() - dt.timedelta(days=3)).strftime("%Y-%m-%d")
        end = dt.datetime.utcnow().strftime("%Y-%m-%d")
        async with httpx.AsyncClient(follow_redirects=True, timeout=40, headers={"User-Agent": USER_AGENT}) as client:
            for i in range(0, len(names), 80):
                chunk = names[i : i + 80]
                rows = []
                try:
                    r = await client.post(
                        OPENSKIN_BATCH,
                        json={
                            "items": chunk,
                            "marketplace": "steam",
                            "interval": "hourly",
                            "from": start,
                            "to": end,
                        },
                    )
                    body = r.json() if r.status_code < 400 else {}
                    blob = body.get("data") or {}
                    if not isinstance(blob, dict):
                        blob = {}
                    for name in chunk:
                        series = blob.get(name)
                        if isinstance(series, dict):
                            series = series.get("data") or []
                        pts = []
                        for pt in series or []:
                            ts = _parse_hist_ts(pt.get("timestamp") or pt.get("date") or pt.get("t"))
                            price = pt.get("price") or pt.get("ask") or pt.get("median")
                            try:
                                price = float(price) if price is not None else None
                            except (TypeError, ValueError):
                                price = None
                            if ts and price and price > 0:
                                pts.append((ts, price))
                        c24, c48 = changes_from_points(pts)
                        if c24 is None and c48 is None:
                            continue
                        rows.append((name, c24, c48, trend_score(c48, c24)))
                except Exception:
                    rows = []
                if rows:
                    await asyncio.to_thread(update_catalog_trends, game, rows)
                    done += len(rows)
                await asyncio.sleep(0.35)
        _last_rank[game] = time.time()
        return {"ok": True, "ranked": done, "count": catalog_ranked_count(game)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    finally:
        _ranking.discard(game)


async def list_catalog(game: str, q: str = "", offset: int = 0, limit: int = 80) -> dict:
    offset = max(0, offset)
    limit = min(max(1, limit), 200)

    if game not in ("cs2", "rust"):
        return await _list_ko(q=q, offset=offset, limit=limit)

    local = query_catalog(game, q=q, offset=offset, limit=limit)
    n = local["total"] if not (q or "").strip() else catalog_count(game)
    stale = n < 50
    if stale:
        _schedule_sync(game)
        try:
            from .sources.bynogame import list_steam_catalog
            app_id = RUST_APP_ID if game == "rust" else CS2_APP_ID
            page = offset // limit + 1
            async with httpx.AsyncClient(follow_redirects=True) as client:
                live = await list_steam_catalog(
                    client, app_id=app_id, page=page, limit=limit, q=q
                )
            if live.get("items"):
                await asyncio.to_thread(
                    upsert_catalog,
                    game,
                    [
                        (
                            it["name"],
                            it.get("price_try"),
                            it.get("quantity") or 0,
                            it.get("url"),
                            "bynogame",
                        )
                        for it in live["items"]
                    ],
                )
                return {
                    "items": live["items"],
                    "total": live.get("total") or len(live["items"]),
                    "offset": offset,
                    "limit": limit,
                    "syncing": True,
                    "source": "bynogame",
                    "hint": "Tam katalog arka planda dolduruluyor (binlerce item).",
                    "ranked": catalog_ranked_count(game),
                    "ranking": game in _ranking,
                }
        except Exception:
            pass
        return {
            **local,
            "syncing": True,
            "hint": "Katalog ilk kez yazılıyor. Skinport limiti varsa ByNoGame/CSFloat yedeklenir.",
            "ranked": catalog_ranked_count(game),
            "ranking": game in _ranking,
        }

    updated = catalog_updated_at(game)
    try:
        if updated:
            ts = dt.datetime.fromisoformat(updated)
            if (dt.datetime.now() - ts).total_seconds() > 6 * 3600:
                _schedule_sync(game)
    except ValueError:
        pass

    _schedule_rank(game)
    return {
        **local,
        "syncing": game in _syncing,
        "updated_at": updated,
        "source": "sqlite",
        "ranked": catalog_ranked_count(game),
        "ranking": game in _ranking,
    }


async def _list_ko(q: str = "", offset: int = 0, limit: int = 80) -> dict:
    from .sources.bynogame import KO_PRODUCTS_API, _HEADERS
    page_n = offset // limit + 1
    url = (
        f"{KO_PRODUCTS_API}?page={page_n}&limit={limit}&sort=MostSelling:-1"
        f"&filters=OnlyInStock:true"
    )
    if q:
        from urllib.parse import quote
        url += f";Name:{quote(q, safe='')}"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(url, headers=_HEADERS, timeout=40)
        r.raise_for_status()
        body = r.json()
    data = body.get("data") or {}
    rows = data.get("result") or []
    total = int(data.get("totalCount") or data.get("total") or len(rows))
    items = []
    for it in rows:
        title = it.get("displayName") or it.get("displayNameShort") or it.get("name") or ""
        if not title:
            continue
        price = it.get("priceMin") or it.get("price")
        try:
            price_try = float(price) if price else None
        except (TypeError, ValueError):
            price_try = None
        items.append({"name": title, "price_try": price_try, "url": None, "quantity": 1})
    if q:
        ql = q.lower()
        items = [x for x in items if ql in x["name"].lower()]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


OPENSKIN_HISTORY = "https://api.openskin.dev/v1/history"
_hist_fetched: set[tuple[str, str, str]] = set()


def _history_rows(game: str, name: str, sources: tuple[str, ...], since: str) -> list:
    placeholders = ",".join("?" * len(sources))
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT captured_at, price_try FROM price_history
                WHERE game=? AND name=? AND source IN ({placeholders})
                  AND price_try IS NOT NULL AND captured_at>=?
                ORDER BY captured_at""",
            (game, name, *sources, since),
        ).fetchall()


def _series_from_rows(rows, bucket: str) -> list[dict]:
    grouped: dict[str, list[float]] = {}
    for r in rows:
        ts = _parse_hist_ts(r["captured_at"])
        if ts is None:
            continue
        grouped.setdefault(_bucket_key(ts, bucket), []).append(float(r["price_try"]))
    series = []
    for key in sorted(grouped):
        vals = _filter_outliers(grouped[key])
        series.append({"t": key, "v": round(sum(vals) / len(vals), 2)})
    if len(series) >= 4:
        kept = set(_filter_outliers([p["v"] for p in series]))
        series = [p for p in series if p["v"] in kept]
    return series


def _parse_bucket_start(key: str, bucket: str) -> dt.datetime | None:
    if bucket == "month" and len(key) >= 7:
        try:
            return dt.datetime(int(key[:4]), int(key[5:7]), 1)
        except ValueError:
            return None
    t = _parse_hist_ts(key)
    if t:
        return t
    try:
        return dt.datetime.fromisoformat(str(key)[:10])
    except ValueError:
        return None


def _coverage_ok(game: str, name: str, spec: dict) -> bool:
    now = dt.datetime.utcnow()
    since = (now - spec["delta"]).isoformat(timespec="seconds")
    rows = _history_rows(game, name, spec["sources"], since)
    series = _series_from_rows(rows, spec["bucket"])
    if len(series) < spec["min_buckets"]:
        return False
    first = _parse_bucket_start(series[0]["t"], spec["bucket"])
    if first is None:
        return False
    slack = {
        "hour": dt.timedelta(days=2),
        "day": dt.timedelta(days=4),
        "week": dt.timedelta(days=14),
        "month": dt.timedelta(days=40),
    }.get(spec["bucket"], dt.timedelta(days=3))
    return first <= now - spec["delta"] + slack


async def ensure_market_history(game: str, name: str, span: str = "1d") -> None:
    """Steam geçmişini çekip SQLite'a yazar — grafik 'eski vs şimdi' için."""
    if game not in ("cs2", "rust"):
        return
    spec = SPAN_WINDOWS.get(span, SPAN_WINDOWS["1d"])
    key = (game, name, span)
    if key in _hist_fetched or _coverage_ok(game, name, spec):
        _hist_fetched.add(key)
        return

    now = dt.datetime.utcnow()
    interval = spec["interval"]
    days = spec["fetch_days"]
    start = (now - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    from .sources.base import USER_AGENT
    try_rate = await fx.to_try(1.0, "USD") or 41.0
    best: list[tuple] = []
    best_source = "steam_hourly" if interval == "hourly" else "steam"
    async with httpx.AsyncClient(follow_redirects=True, timeout=45, headers={"User-Agent": USER_AGENT}) as client:
        for marketplace in ("steam", "skinport"):
            try:
                r = await client.post(
                    OPENSKIN_HISTORY,
                    json={
                        "item": name,
                        "marketplace": marketplace,
                        "interval": interval,
                        "from": start,
                        "to": end,
                    },
                )
                if r.status_code >= 400:
                    continue
                data = r.json().get("data") or []
                got = []
                for pt in data:
                    ts = _parse_hist_ts(pt.get("timestamp") or pt.get("date") or pt.get("t"))
                    price = pt.get("price")
                    if price is None:
                        price = pt.get("median") or pt.get("ask")
                    if ts is None or price is None:
                        continue
                    try:
                        val = float(price) * try_rate
                    except (TypeError, ValueError):
                        continue
                    if val <= 0:
                        continue
                    got.append((ts.replace(microsecond=0).isoformat(), round(val, 2)))
                if len(got) > len(best):
                    best = got
                    if interval == "hourly":
                        best_source = f"{marketplace}_hourly"
                    elif marketplace == "skinport":
                        best_source = "skinport_daily"
                    else:
                        best_source = "steam"
                if marketplace == "steam" and len(got) >= spec["min_buckets"]:
                    break
            except Exception:
                continue
    if len(best) >= 2:
        await asyncio.to_thread(replace_priced_history, game, name, best_source, best)
    _hist_fetched.add(key)


def history_series(game: str, name: str, span: str = "1d") -> dict:
    """span: 1h saatlik | 1d günlük | 1w haftalık | 1m aylık"""
    spec = SPAN_WINDOWS.get(span, SPAN_WINDOWS["1d"])
    now = dt.datetime.now()
    since = (now - spec["delta"]).isoformat(timespec="seconds")
    bucket = spec["bucket"]
    rows = []
    for src in spec["sources"]:
        part = _history_rows(game, name, (src,), since)
        if len(_series_from_rows(part, bucket)) >= spec["min_buckets"]:
            rows = part
            break
        if len(part) > len(rows):
            rows = part
    if not rows:
        rows = _history_rows(game, name, spec["sources"], since)
    series = _series_from_rows(rows, bucket)
    latest = series[-1]["v"] if series else None
    first = series[0]["v"] if series else None
    low = min((p["v"] for p in series), default=None)
    high = max((p["v"] for p in series), default=None)
    change_pct = None
    if first and latest and first > 0:
        change_pct = round((latest - first) / first * 100, 1)
    return {
        "span": span,
        "bucket": bucket,
        "points": series,
        "latest": latest,
        "first": first,
        "low": low,
        "high": high,
        "change_pct": change_pct,
        "from_t": series[0]["t"] if series else None,
        "to_t": series[-1]["t"] if series else None,
    }


def _write_snapshot_rows(rows: list[tuple], mark_daily: bool) -> None:
    record_history_bulk(rows)
    if mark_daily:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES('last_catalog_snapshot',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (dt.datetime.now().isoformat(timespec="seconds"),),
            )


def _should_daily(now: float, force: bool) -> bool:
    if force:
        return True
    if now - _last_daily < 20 * 3600:
        return False
    if _last_daily == 0.0:
        return False
    return True


async def snapshot_catalogs(force: bool = False) -> dict:
    """Saatlik: depo + takip fiyatı. Ayrıca yerel katalog senkronu."""
    global _last_hourly, _last_daily
    now = time.time()
    out = {"hourly": False, "daily": False}
    for game in ("cs2", "rust"):
        try:
            await sync_catalog(game, force=force)
        except Exception:
            pass
    if not force and now - _last_hourly < 50 * 60:
        return out

    daily = _should_daily(now, force)
    rows: list[tuple] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for game, app_id in (("cs2", CS2_APP_ID), ("rust", RUST_APP_ID)):
            names = set(tracked_names(game))
            if not names and not daily:
                continue
            try:
                catalog = await _get_items(client, app_id=app_id, currency="TRY")
            except Exception:
                continue
            for name in names:
                row = catalog.get(name)
                if not row:
                    continue
                p = _skinport_price(row)
                if p is not None:
                    rows.append((game, name, "skinport", p))
            if daily:
                n = 0
                for name, row in catalog.items():
                    if name in names:
                        continue
                    p = _skinport_price(row)
                    if p is None:
                        continue
                    rows.append((game, name, "skinport", p))
                    n += 1
                out["daily"] = True
                out["daily_rows"] = out.get("daily_rows", 0) + n

    await asyncio.to_thread(_write_snapshot_rows, rows, bool(out["daily"]))
    _last_hourly = now
    if out["daily"] or _last_daily == 0.0:
        _last_daily = now
    out["hourly"] = True
    return out


async def warm_catalogs() -> None:
    await asyncio.sleep(2)
    for game in ("cs2", "rust"):
        try:
            await sync_catalog(game)
        except Exception:
            pass
        try:
            asyncio.create_task(rank_catalog_trends(game))
        except Exception:
            pass
