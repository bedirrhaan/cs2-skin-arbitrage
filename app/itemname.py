"""Item adı ayrıştırma yardımcıları.

Kullanıcı Steam market_hash_name girer, örn:
  "AK-47 | Redline (Field-Tested)"
  "StatTrak™ AK-47 | Redline (Field-Tested)"
  "★ Karambit | Doppler (Factory New)"
Türk siteleri (Kopazar, GameSatis) tam adla değil, silah+desen anahtar
kelimesiyle arama yapar; wear/StatTrak eşleşmesini sonuçlar üzerinde yaparız.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

WEARS = {
    "Factory New": "FN",
    "Minimal Wear": "MW",
    "Field-Tested": "FT",
    "Well-Worn": "WW",
    "Battle-Scarred": "BS",
}
WEAR_SLUGS = {
    "Factory New": "factory-new",
    "Minimal Wear": "minimal-wear",
    "Field-Tested": "field-tested",
    "Well-Worn": "well-worn",
    "Battle-Scarred": "battle-scarred",
}
# Türk sitelerindeki wear ifadeleri → İngilizce tam ad
WEAR_TR = {
    "fabrikadan yeni çıkmış": "Factory New",
    "az aşınmış": "Minimal Wear",
    "görevde kullanılmış": "Field-Tested",
    "eskimiş": "Well-Worn",
    "savaş görmüş": "Battle-Scarred",
}
_WEAR_SLUG_EXTRA = {
    "az-asinmis": "Minimal Wear",
    "gorevde-kullanilmis": "Field-Tested",
    "fabrikadan-yeni-cikmis": "Factory New",
    "eskimiş": "Well-Worn",
    "eskimiş": "Well-Worn",
    "darmadaginik": "Battle-Scarred",
    "savas-gormus": "Battle-Scarred",
}


@dataclass
class ParsedItem:
    full_name: str          # orijinal market_hash_name
    base_name: str          # ★, StatTrak™ ve wear'sız: "AK-47 | Redline"
    keyword: str            # arama kelimesi: "AK-47 Redline"
    wear: str | None        # "Field-Tested" | None
    wear_short: str | None  # "FT" | None
    stattrak: bool
    souvenir: bool
    knife: bool             # ★ ile başlıyor mu


def parse_item_name(name: str) -> ParsedItem:
    original = name.strip()
    s = original

    knife = s.startswith("★")
    s = s.lstrip("★").strip()

    stattrak = bool(re.match(r"(?i)^stattrak", s))
    s = re.sub(r"(?i)^stattrak[™™]?\s*", "", s)

    souvenir = bool(re.match(r"(?i)^souvenir\s", s))
    s = re.sub(r"(?i)^souvenir\s+", "", s)

    wear = None
    m = re.search(r"\(([^)]+)\)\s*$", s)
    if m and m.group(1) in WEARS:
        wear = m.group(1)
        s = s[: m.start()].strip()

    base_name = s
    keyword = s.replace("|", " ")
    keyword = re.sub(r"\s+", " ", keyword).strip()

    return ParsedItem(
        full_name=original,
        base_name=base_name,
        keyword=keyword,
        wear=wear,
        wear_short=WEARS.get(wear) if wear else None,
        stattrak=stattrak,
        souvenir=souvenir,
        knife=knife,
    )


def norm(s: str) -> str:
    """Karşılaştırma için isim normalize et."""
    s = s.replace("™", "").replace("★", "").replace("|", " ")
    s = re.sub(r"(?i)\bstattrak\b", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


_WEAR_PAREN = re.compile(
    r"\((?:Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)"
)


def detect_listing_wear(text: str, href: str = "") -> str | None:
    """İlan metni veya URL slug'ından wear çıkar (Türk/İngilizce)."""
    for m in re.finditer(r"[\[(]([^)\]]+)[)\]]", text):
        w = m.group(1).strip()
        if w in WEARS:
            return w
        wl = w.lower()
        if wl in WEAR_TR:
            return WEAR_TR[wl]
    for full in WEARS:
        if re.search(rf"\b{re.escape(full)}\b", text, re.I):
            return full
    for full, abbr in WEARS.items():
        if re.search(rf"\b{abbr}\b", text):
            return full
    href_l = href.lower()
    slug_map = {v: k for k, v in WEAR_SLUGS.items()}
    slug_map.update(_WEAR_SLUG_EXTRA)
    for slug, wear in slug_map.items():
        if slug in href_l:
            return wear
    return None


def norm_listing(s: str) -> str:
    """Site ilan adını taban adla karşılaştırmak için normalize et.

    Türk siteleri ilan adında wear parantezini ve sonuna Türkçe çeviri
    ekleyebilir, örn: "AK-47 | Elite Build (Minimal Wear) - Seçkin Yapım".
    Wear parantezi ve " - ..." kuyruğu atılıp norm() uygulanır.
    """
    s = _WEAR_PAREN.sub(" ", s)
    s = re.sub(r"\s+-\s+[^|]+$", "", s)
    return norm(s)
