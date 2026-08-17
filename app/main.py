"""Skin Arbitraj Paneli — FastAPI uygulaması."""
import asyncio
import contextlib
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine, telegram
from .catalog import ensure_market_history, history_series, list_catalog, warm_catalogs
from .catalog_cache import close as close_cache, init as init_cache
from .db import (
    add_depo,
    depo_has,
    get_conn,
    get_settings,
    init_db,
    list_depo,
    record_history,
    remove_depo,
    set_settings,
)
from .games import GAMES
from .sources import SOURCES

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    engine.status["cache_backend"] = await init_cache()
    task = asyncio.create_task(engine.scheduler_loop())
    asyncio.create_task(warm_catalogs())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await close_cache()


app = FastAPI(title="Skin Arbitraj Paneli", lifespan=lifespan)


# ---------- şemalar ----------

class ItemIn(BaseModel):
    names: str  # her satıra bir item adı
    game: str = "cs2"


class ResolveIn(BaseModel):
    query: str
    game: str = "cs2"


class SettingsIn(BaseModel):
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    check_interval_min: Optional[str] = None
    bitskins_api_key: Optional[str] = None
    enabled_sources: Optional[str] = None
    enabled_sources_cs2: Optional[str] = None
    enabled_sources_rust: Optional[str] = None
    enabled_sources_ko: Optional[str] = None


class AlertIn(BaseModel):
    item_id: int
    kind: str            # below | above | spread
    threshold: float
    source: Optional[str] = None
    cooldown_min: int = 30


# ---------- item uçları ----------

@app.get("/api/items")
def list_items(game: str = "cs2"):
    if game not in GAMES:
        raise HTTPException(400, "geçersiz oyun")
    labels = {k: v["label"] for k, v in GAMES[game]["sources"].items()}
    with get_conn() as conn:
        items = conn.execute(
            "SELECT * FROM items WHERE game=? ORDER BY id", (game,)
        ).fetchall()
        alerts = conn.execute("SELECT * FROM alerts ORDER BY id").fetchall()
    alerts_by_item: dict = {}
    for a in alerts:
        alerts_by_item.setdefault(a["item_id"], []).append(dict(a))
    out = []
    for it in items:
        prices = engine.latest_prices(it["id"])
        out.append({
            "id": it["id"],
            "game": it["game"] if "game" in it.keys() else "cs2",
            "name": it["name"],
            "prices": prices,
            "spread": engine.spread_info(prices),
            "cheapest": engine.cheapest_three(prices, labels),
            "alerts": alerts_by_item.get(it["id"], []),
        })
    src = GAMES[game]["sources"]
    return {"items": out, "sources": {k: v["label"] for k, v in src.items()}, "game": game}


@app.post("/api/items/resolve")
async def resolve_item(body: ResolveIn):
    q = body.query.strip()
    if not q:
        raise HTTPException(400, "arama boş")
    game = body.game if body.game in GAMES else "cs2"
    return await engine.resolve_variants(q, game=game)


@app.post("/api/items")
def add_items(body: ItemIn):
    names = [n.strip() for n in body.names.splitlines() if n.strip()]
    if not names:
        raise HTTPException(400, "item adı boş")
    game = body.game if body.game in GAMES else "cs2"
    added, skipped = [], []
    with get_conn() as conn:
        for n in names:
            try:
                conn.execute(
                    "INSERT INTO items(game, name) VALUES(?,?)", (game, n)
                )
                added.append(n)
            except Exception:
                skipped.append(n)
    return {"added": added, "skipped": skipped}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    return {"ok": True}


# ---------- alarm uçları ----------

@app.post("/api/alerts")
def add_alert(body: AlertIn):
    if body.kind not in ("below", "above", "spread"):
        raise HTTPException(400, "geçersiz alarm türü")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts(item_id, kind, threshold, source, cooldown_min) VALUES(?,?,?,?,?)",
            (body.item_id, body.kind, body.threshold, body.source or None, body.cooldown_min),
        )
    return {"ok": True}


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
    return {"ok": True}


@app.post("/api/alerts/{alert_id}/toggle")
def toggle_alert(alert_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE alerts SET enabled = 1 - enabled WHERE id=?", (alert_id,))
    return {"ok": True}


# ---------- ayarlar / telegram ----------

@app.get("/api/settings")
def read_settings():
    s = get_settings()
    return s


@app.put("/api/settings")
def write_settings(body: SettingsIn):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    set_settings(values)
    return get_settings()


@app.post("/api/telegram/test")
async def telegram_test():
    s = get_settings()
    ok, info = await telegram.send_message(
        s["telegram_token"], s["telegram_chat_id"],
        "✅ Skin Arbitraj Paneli test mesajı — bağlantı çalışıyor!",
    )
    if not ok:
        raise HTTPException(400, info)
    return {"ok": True}


# ---------- fırsatlar ----------

@app.get("/api/opportunities")
async def get_opportunities(
    min_spread: float = 5.0,
    min_discount: float = 15.0,
    game: str = "cs2",
):
    if game not in GAMES:
        raise HTTPException(400, "geçersiz oyun")
    return await engine.opportunities(
        min_spread_pct=min_spread, min_discount_pct=min_discount, game=game
    )


# ---------- döngü ----------

@app.post("/api/items/{item_id}/refresh")
async def refresh_one_item(item_id: int):
    result = await engine.refresh_item(item_id)
    if not result.get("ok"):
        raise HTTPException(409, result.get("msg", "tarama başarısız"))
    return result


@app.post("/api/refresh")
async def refresh():
    result = await engine.run_cycle()
    return result


@app.get("/api/status")
def get_status():
    with get_conn() as conn:
        notifs = conn.execute(
            "SELECT * FROM notifications ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return {**engine.status, "notifications": [dict(n) for n in notifs]}


# ---------- katalog / depo / grafik ----------

@app.get("/api/catalog")
async def api_catalog(game: str = "cs2", q: str = "", offset: int = 0, limit: int = 80):
    if game not in GAMES:
        raise HTTPException(400, "geçersiz oyun")
    try:
        return await list_catalog(game, q=q, offset=offset, limit=limit)
    except Exception as e:
        return {
            "items": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "syncing": True,
            "error": f"{type(e).__name__}: {e}"[:200],
            "hint": "Katalog yerelde tutulur; Skinport limiti sayfayı kilitlemez.",
        }


@app.get("/api/catalog/history")
async def api_history(game: str = "cs2", name: str = "", span: str = "1h"):
    if game not in GAMES:
        raise HTTPException(400, "geçersiz oyun")
    if not name.strip():
        raise HTTPException(400, "isim gerekli")
    if span not in ("1h", "1d", "1w", "1m"):
        span = "1h"
    nm = name.strip()
    try:
        await ensure_market_history(game, nm, span)
    except Exception:
        pass
    data = history_series(game, nm, span)
    if not data.get("points"):
        try:
            cat = await list_catalog(game, q=nm, offset=0, limit=20)
            hit = next((x for x in cat.get("items") or [] if x.get("name") == nm), None)
            if hit and hit.get("price_try") is not None:
                src = "bynogame" if game == "ko" else "skinport"
                record_history(game, nm, src, hit["price_try"])
                data = history_series(game, nm, span)
        except Exception:
            pass
    data["in_depo"] = depo_has(game, nm)
    if "chart_label" not in data:
        data["chart_label"] = "Pazar fiyat" if game == "ko" else "Steam fiyat"
    return data


@app.get("/api/depo")
def api_depo_list(game: str = "cs2"):
    if game not in GAMES:
        raise HTTPException(400, "geçersiz oyun")
    return {"items": list_depo(game)}


class DepoIn(BaseModel):
    name: str
    game: str = "cs2"


@app.post("/api/depo")
def api_depo_add(body: DepoIn):
    if body.game not in GAMES:
        raise HTTPException(400, "geçersiz oyun")
    try:
        return add_depo(body.game, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/depo/{depo_id}")
def api_depo_del(depo_id: int):
    remove_depo(depo_id)
    return {"ok": True}


# ---------- statik ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
