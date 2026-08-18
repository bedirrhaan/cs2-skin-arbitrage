"""SQLite veritabanı katmanı."""
import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("PANEL_DB", os.path.join(os.path.dirname(__file__), "..", "data", "panel.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL DEFAULT 'cs2',
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(game, name)
);
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    price_orig REAL,
    currency TEXT,
    price_try REAL,
    url TEXT,
    error TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_prices_item ON prices(item_id, source, fetched_at DESC);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('below','above','spread')),
    threshold REAL NOT NULL,
    source TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    cooldown_min INTEGER NOT NULL DEFAULT 30,
    last_triggered_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER,
    message TEXT NOT NULL,
    sent_ok INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS depo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(game, name)
);
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    price_try REAL,
    captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_hist_lookup ON price_history(game, name, captured_at);
CREATE INDEX IF NOT EXISTS idx_depo_game ON depo(game);
CREATE TABLE IF NOT EXISTS catalog_names (
    game TEXT NOT NULL,
    name TEXT NOT NULL,
    price_try REAL,
    quantity INTEGER NOT NULL DEFAULT 0,
    url TEXT,
    source TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    chg_24h REAL,
    chg_48h REAL,
    rank_score REAL,
    PRIMARY KEY (game, name)
);
CREATE INDEX IF NOT EXISTS idx_catalog_game_name ON catalog_names(game, name);
CREATE TABLE IF NOT EXISTS popular_hits (
    game TEXT NOT NULL,
    name TEXT NOT NULL,
    last_notified_at TEXT,
    PRIMARY KEY (game, name)
);
"""

DEFAULT_SETTINGS = {
    "telegram_token": "",
    "telegram_chat_id": "",
    "check_interval_min": "5",
    "bitskins_api_key": "",
    "display_currency": "TRY",
    "enabled_sources": "steam,skinport,dmarket,bitskins,kopazar,gamesatis,bynogame,csfloat,itemsatis,itemci",
    "enabled_sources_cs2": "steam,skinport,dmarket,bitskins,kopazar,gamesatis,bynogame,csfloat,itemsatis,itemci",
    "enabled_sources_rust": "skinport,dmarket,rust_tm,bynogame,waxpeer,steam,gamesatis",
    "enabled_sources_ko": "kopazar,bynogame,klasgame,oyunfor",
    "popular_top_n": "20",
    "popular_min_spread": "8",
}


def _migrate_items_game(conn: sqlite3.Connection):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    if "game" in cols:
        return
    conn.executescript("""
        CREATE TABLE items_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game TEXT NOT NULL DEFAULT 'cs2',
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(game, name)
        );
        INSERT INTO items_new(id, game, name, created_at)
            SELECT id, 'cs2', name, created_at FROM items;
        DROP TABLE items;
        ALTER TABLE items_new RENAME TO items;
    """)


def _migrate_catalog_rank(conn: sqlite3.Connection):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(catalog_names)").fetchall()}
    if not cols:
        return
    if "chg_24h" not in cols:
        conn.execute("ALTER TABLE catalog_names ADD COLUMN chg_24h REAL")
    if "chg_48h" not in cols:
        conn.execute("ALTER TABLE catalog_names ADD COLUMN chg_48h REAL")
    if "rank_score" not in cols:
        conn.execute("ALTER TABLE catalog_names ADD COLUMN rank_score REAL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_rank ON catalog_names(game, rank_score DESC)"
    )


def _migrate_price_offers(conn: sqlite3.Connection):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prices)").fetchall()}
    if cols and "offers" not in cols:
        conn.execute("ALTER TABLE prices ADD COLUMN offers TEXT")


def _migrate_settings(conn: sqlite3.Connection):
    old = conn.execute(
        "SELECT value FROM settings WHERE key='enabled_sources'"
    ).fetchone()
    cs2 = conn.execute(
        "SELECT value FROM settings WHERE key='enabled_sources_cs2'"
    ).fetchone()
    if old and not cs2:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES('enabled_sources_cs2', ?)",
            (old["value"],),
        )


_ENV_SETTINGS = {
    "telegram_token": "TELEGRAM_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
}


def _append_missing_sources(conn: sqlite3.Connection):
    """Mevcut DB'de yeni pazarları enabled listesine ekler (kullanıcı silmişse bir kez geri gelir)."""
    extras = {
        "enabled_sources_rust": ["gamesatis"],
    }
    for key, add in extras.items():
        flag = f"migrated_{key}_tr_sites_v1"
        if conn.execute("SELECT 1 FROM settings WHERE key=?", (flag,)).fetchone():
            continue
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        parts = []
        if row and row["value"]:
            parts = [s.strip() for s in row["value"].split(",") if s.strip()]
        for src in add:
            if src not in parts:
                parts.append(src)
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, ",".join(parts)),
        )
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (flag, "1"))

    flag_steam = "migrated_cs2_steam_ref_v1"
    if not conn.execute("SELECT 1 FROM settings WHERE key=?", (flag_steam,)).fetchone():
        row = conn.execute(
            "SELECT value FROM settings WHERE key='enabled_sources_cs2'"
        ).fetchone()
        parts = [s.strip() for s in (row["value"] if row else "").split(",") if s.strip()]
        if "steam" in parts:
            parts = ["steam"] + [s for s in parts if s != "steam"]
        else:
            parts = ["steam"] + parts
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('enabled_sources_cs2',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (",".join(parts),),
        )
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (flag_steam, "1"))

    # İtemSatış KO: GB mağazası / boş kategori — kaynak olarak kalmasın
    ko_row = conn.execute(
        "SELECT value FROM settings WHERE key='enabled_sources_ko'"
    ).fetchone()
    if ko_row and ko_row["value"] and "itemsatis" in ko_row["value"]:
        parts = [
            s.strip()
            for s in ko_row["value"].split(",")
            if s.strip() and s.strip() != "itemsatis"
        ]
        conn.execute(
            "UPDATE settings SET value=? WHERE key='enabled_sources_ko'",
            (",".join(parts) or "kopazar,bynogame,klasgame,oyunfor",),
        )

    flag_ko = "migrated_ko_markets_v2"
    if not conn.execute("SELECT 1 FROM settings WHERE key=?", (flag_ko,)).fetchone():
        row = conn.execute(
            "SELECT value FROM settings WHERE key='enabled_sources_ko'"
        ).fetchone()
        parts = [s.strip() for s in (row["value"] if row else "").split(",") if s.strip()]
        parts = [s for s in parts if s != "itemsatis"]
        for src in ("klasgame", "oyunfor"):
            if src not in parts:
                parts.append(src)
        if not parts:
            parts = ["kopazar", "bynogame", "klasgame", "oyunfor"]
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('enabled_sources_ko',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (",".join(parts),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (flag_ko, "1")
        )


def _apply_env_settings(conn: sqlite3.Connection):
    """Docker/.env doluysa Telegram ayarlarını yazar; boş env mevcut kaydı ezmez."""
    for key, env_name in _ENV_SETTINGS.items():
        val = os.environ.get(env_name, "").strip()
        if val:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, val),
            )


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with get_conn() as conn:
        # Eski şema (game kolonu yok) varsa migrate et
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "items" in tables:
            _migrate_items_game(conn)
        conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))
        _migrate_settings(conn)
        _migrate_catalog_rank(conn)
        _migrate_price_offers(conn)
        _apply_env_settings(conn)
        _append_missing_sources(conn)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    return s


def set_settings(values: dict):
    with get_conn() as conn:
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                conn.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, str(v)),
                )


def enabled_sources_for(settings: dict, game: str) -> list[str]:
    key = f"enabled_sources_{game}"
    raw = settings.get(key) or settings.get("enabled_sources", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def list_depo(game: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM depo WHERE game=? ORDER BY id DESC", (game,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_depo(game: str, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("isim boş")
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO depo(game, name) VALUES(?,?)", (game, name)
        )
        row = conn.execute(
            "SELECT * FROM depo WHERE game=? AND name=?", (game, name)
        ).fetchone()
    return dict(row) if row else {}


def remove_depo(depo_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM depo WHERE id=?", (depo_id,))


def depo_has(game: str, name: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM depo WHERE game=? AND name=?", (game, name)
        ).fetchone()
    return bool(row)


def record_history(game: str, name: str, source: str, price_try: float | None):
    if price_try is None:
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO price_history(game, name, source, price_try) VALUES(?,?,?,?)",
            (game, name, source, price_try),
        )


def record_history_bulk(rows: list[tuple]):
    """(game, name, source, price_try) satırlarını tek işlemde yazar."""
    batch = [r for r in rows if r[3] is not None]
    if not batch:
        return
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO price_history(game, name, source, price_try) VALUES(?,?,?,?)",
            batch,
        )


def replace_priced_history(game: str, name: str, source: str, rows: list[tuple]) -> int:
    """rows: (captured_at, price_try). Aynı kaynak geçmişini yeniler."""
    batch = [(game, name, source, p, ts) for ts, p in rows if p is not None and ts]
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM price_history WHERE game=? AND name=? AND source=?",
            (game, name, source),
        )
        if batch:
            conn.executemany(
                "INSERT INTO price_history(game, name, source, price_try, captured_at) VALUES(?,?,?,?,?)",
                batch,
            )
    return len(batch)


def history_point_count(game: str, name: str, source: str, since: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM price_history
               WHERE game=? AND name=? AND source=? AND price_try IS NOT NULL AND captured_at>=?""",
            (game, name, source, since),
        ).fetchone()
    return int(row["n"] if row else 0)


def tracked_names(game: str) -> list[str]:
    with get_conn() as conn:
        items = conn.execute("SELECT name FROM items WHERE game=?", (game,)).fetchall()
        depo = conn.execute("SELECT name FROM depo WHERE game=?", (game,)).fetchall()
    names = {r["name"] for r in items}
    names.update(r["name"] for r in depo)
    return sorted(names)


def catalog_count(game: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM catalog_names WHERE game=?", (game,)
        ).fetchone()
    return int(row["n"] if row else 0)


def catalog_updated_at(game: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(updated_at) AS t FROM catalog_names WHERE game=?", (game,)
        ).fetchone()
    return row["t"] if row and row["t"] else None


def query_catalog(game: str, q: str = "", offset: int = 0, limit: int = 80) -> dict:
    offset = max(0, offset)
    limit = min(max(1, limit), 200)
    qn = (q or "").strip()
    with get_conn() as conn:
        if qn:
            like = f"%{qn}%"
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM catalog_names WHERE game=? AND name LIKE ? COLLATE NOCASE",
                (game, like),
            ).fetchone()["n"]
            rows = conn.execute(
                """SELECT name, price_try, quantity, url, chg_24h, chg_48h, rank_score
                   FROM catalog_names
                   WHERE game=? AND name LIKE ? COLLATE NOCASE
                   ORDER BY CASE
                     WHEN rank_score IS NULL THEN 1
                     WHEN rank_score > 0 THEN 0
                     ELSE 2 END,
                     rank_score DESC, name
                   LIMIT ? OFFSET ?""",
                (game, like, limit, offset),
            ).fetchall()
        else:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM catalog_names WHERE game=?", (game,)
            ).fetchone()["n"]
            rows = conn.execute(
                """SELECT name, price_try, quantity, url, chg_24h, chg_48h, rank_score
                   FROM catalog_names
                   WHERE game=?
                   ORDER BY CASE
                     WHEN rank_score IS NULL THEN 1
                     WHEN rank_score > 0 THEN 0
                     ELSE 2 END,
                     rank_score DESC, name
                   LIMIT ? OFFSET ?""",
                (game, limit, offset),
            ).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": int(total),
        "offset": offset,
        "limit": limit,
    }


def upsert_catalog(game: str, rows: list[tuple]) -> int:
    """rows: (name, price_try, quantity, url, source)"""
    batch = [(game, n, p, q or 0, u, s) for n, p, q, u, s in rows if n]
    if not batch:
        return 0
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO catalog_names(game, name, price_try, quantity, url, source, updated_at)
               VALUES(?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(game, name) DO UPDATE SET
                 price_try=excluded.price_try,
                 quantity=excluded.quantity,
                 url=excluded.url,
                 source=excluded.source,
                 updated_at=excluded.updated_at""",
            batch,
        )
    return len(batch)


def top_popular_names(game: str, limit: int = 20) -> list[dict]:
    """Popüler / çok satan katalog: Steam trend skoru, yoksa stok (quantity)."""
    limit = min(max(int(limit or 20), 5), 25)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT name, quantity, rank_score, chg_24h, chg_48h, url
               FROM catalog_names
               WHERE game=?
               ORDER BY CASE
                 WHEN rank_score IS NULL THEN 1
                 WHEN rank_score > 0 THEN 0
                 ELSE 2 END,
                 rank_score DESC, quantity DESC, name
               LIMIT ?""",
            (game, limit),
        ).fetchall()
        listed = {
            r["name"]
            for r in conn.execute("SELECT name FROM items WHERE game=?", (game,)).fetchall()
        }
        tracked = {
            r["name"]
            for r in conn.execute("SELECT name FROM depo WHERE game=?", (game,)).fetchall()
        }
    out = []
    for i, r in enumerate(rows, 1):
        d = dict(r)
        d["rank"] = i
        d["in_list"] = d["name"] in listed
        d["in_depo"] = d["name"] in tracked
        out.append(d)
    return out


def catalog_ranked_count(game: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM catalog_names WHERE game=? AND rank_score IS NOT NULL",
            (game,),
        ).fetchone()
    return int(row["n"] if row else 0)


def update_catalog_trends(game: str, rows: list[tuple]) -> int:
    """rows: (name, chg_24h, chg_48h, rank_score)"""
    batch = [(a, b, c, game, n) for n, a, b, c in rows if n]
    if not batch:
        return 0
    with get_conn() as conn:
        conn.executemany(
            """UPDATE catalog_names
               SET chg_24h=?, chg_48h=?, rank_score=?
               WHERE game=? AND name=?""",
            batch,
        )
    return len(batch)


def catalog_names_by_price(game: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT name FROM catalog_names WHERE game=?
               ORDER BY price_try IS NULL, price_try DESC, name""",
            (game,),
        ).fetchall()
    return [r["name"] for r in rows]
