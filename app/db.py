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
"""

DEFAULT_SETTINGS = {
    "telegram_token": "",
    "telegram_chat_id": "",
    "check_interval_min": "5",
    "bitskins_api_key": "",
    "display_currency": "TRY",
    "enabled_sources": "skinport,dmarket,bitskins,kopazar,gamesatis,bynogame,csfloat,itemsatis,itemci",
    "enabled_sources_cs2": "skinport,dmarket,bitskins,kopazar,gamesatis,bynogame,csfloat,itemsatis,itemci",
    "enabled_sources_rust": "skinport,dmarket,rust_tm,bynogame,waxpeer,steam",
    "enabled_sources_ko": "kopazar,bynogame",
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


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
