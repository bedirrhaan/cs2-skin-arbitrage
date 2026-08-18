"""Oyun bazlı kaynak kayıtları."""
from __future__ import annotations

from .sources import (
    skinport,
    dmarket,
    bitskins,
    kopazar,
    gamesatis,
    bynogame,
    csfloat,
    itemci,
    rust_tm,
    waxpeer,
    steam_market,
    klasgame,
    oyunfor,
)
from .sources import SOURCES as CS2_SOURCES

RUST_SOURCES = {
    "skinport": {
        "label": "Skinport",
        "module": skinport,
        "currency": "TRY",
        "fetch": skinport.fetch_rust,
    },
    "dmarket": {
        "label": "DMarket",
        "module": dmarket,
        "currency": "USD",
        "fetch": dmarket.fetch_rust,
    },
    "rust_tm": {"label": "rust.tm", "module": rust_tm, "currency": "USD"},
    "bynogame": {
        "label": "ByNoGame",
        "module": bynogame,
        "currency": "TRY",
        "fetch": bynogame.fetch_rust,
    },
    "waxpeer": {"label": "Waxpeer", "module": waxpeer, "currency": "USD"},
    "steam": {
        "label": "Steam Market",
        "module": steam_market,
        "currency": "TRY",
        "fetch": steam_market.fetch_rust,
    },
    "bitskins": {
        "label": "Bitskins",
        "module": bitskins,
        "currency": "USD",
        "fetch": bitskins.fetch_rust,
    },
    "gamesatis": {
        "label": "GameSatis",
        "module": gamesatis,
        "currency": "TRY",
        "fetch": gamesatis.fetch_rust,
    },
}

KO_SOURCES = {
    "kopazar": {
        "label": "Kopazar",
        "module": kopazar,
        "currency": "TRY",
        "fetch": kopazar.fetch_ko,
    },
    "bynogame": {
        "label": "ByNoGame",
        "module": bynogame,
        "currency": "TRY",
        "fetch": bynogame.fetch_ko,
    },
    "klasgame": {
        "label": "Klasgame",
        "module": klasgame,
        "currency": "TRY",
        "fetch": klasgame.fetch_ko,
    },
    "oyunfor": {
        "label": "Oyunfor",
        "module": oyunfor,
        "currency": "TRY",
        "fetch": oyunfor.fetch_ko,
    },
}

GAMES = {
    "cs2": {"label": "CS2", "sources": CS2_SOURCES},
    "rust": {"label": "Rust", "sources": RUST_SOURCES},
    "ko": {"label": "Knight Online", "sources": KO_SOURCES},
}

SOURCES = CS2_SOURCES
