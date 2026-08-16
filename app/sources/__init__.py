"""Kaynak kayıt defteri (CS2)."""
from . import skinport, dmarket, bitskins, kopazar, gamesatis, bynogame, csfloat, itemsatis, itemci, rust_tm, steam_market

SOURCES = {
    "steam": {"label": "Steam Market", "module": steam_market, "currency": "TRY"},
    "skinport": {"label": "Skinport", "module": skinport, "currency": "TRY"},
    "dmarket": {"label": "DMarket", "module": dmarket, "currency": "USD"},
    "bitskins": {"label": "Bitskins", "module": bitskins, "currency": "USD"},
    "kopazar": {"label": "Kopazar", "module": kopazar, "currency": "TRY"},
    "gamesatis": {"label": "GameSatis", "module": gamesatis, "currency": "TRY"},
    "bynogame": {"label": "ByNoGame", "module": bynogame, "currency": "TRY"},
    "csfloat": {"label": "CSFloat", "module": csfloat, "currency": "USD"},
    "itemsatis": {"label": "İtemSatış", "module": itemsatis, "currency": "TRY"},
    "itemci": {"label": "Itemci", "module": itemci, "currency": "TRY"},
}
