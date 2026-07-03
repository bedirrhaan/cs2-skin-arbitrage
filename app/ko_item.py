"""Knight Online item adı ayrıştırma.

Örnekler:
  Shard +9
  Shard +1 (Reverse)
  Iron Bow +7
  Ring of Courage +1
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedKoItem:
    full_name: str
    base_name: str
    keyword: str
    plus: int | None
    reverse: bool


def parse_ko_item(name: str) -> ParsedKoItem:
    original = name.strip()
    s = original
    reverse = bool(re.search(r"(?i)\breverse\b|\(\s*reverse\s*\)", s))
    s = re.sub(r"(?i)\(?\s*reverse\s*\)?", "", s).strip()
    s = re.sub(r"\s+", " ", s)

    plus = None
    m = re.search(r"\+(\d+)", s)
    if m:
        plus = int(m.group(1))
        base_name = s[: m.start()].strip()
    else:
        base_name = s

    keyword = original
    return ParsedKoItem(
        full_name=original,
        base_name=base_name or original,
        keyword=keyword,
        plus=plus,
        reverse=reverse,
    )


def norm_ko(s: str) -> str:
    s = re.sub(r"(?i)\(?\s*reverse\s*\)?", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _listing_meta(title: str) -> tuple[str, int | None, bool]:
    reverse = bool(re.search(r"(?i)\(?\s*reverse\s*\)?", title))
    m = re.search(r"\+(\d+)", title)
    plus = int(m.group(1)) if m else None
    base = title
    if m:
        base = title[: m.start()].strip()
    base = re.sub(r"(?i)\(?\s*reverse\s*\)?", "", base).strip()
    return base, plus, reverse


def ko_listing_matches(parsed: ParsedKoItem, listing_title: str) -> bool:
    title = listing_title.strip()
    if not title:
        return False

    base, plus, reverse = _listing_meta(title)
    target_base = norm_ko(parsed.base_name)
    listing_base = norm_ko(base)

    if target_base not in listing_base and listing_base not in target_base:
        if not (listing_base.endswith(target_base) or target_base.endswith(listing_base)):
            return False

    if parsed.plus is not None and plus != parsed.plus:
        return False
    if parsed.reverse and not reverse:
        return False
    if not parsed.reverse and reverse:
        return False
    return True


def canonical_ko_title(listing_title: str) -> str:
    base, plus, reverse = _listing_meta(listing_title)
    if plus is None:
        return base
    if reverse:
        return f"{base} +{plus} (Reverse)"
    return f"{base} +{plus}"


def ko_base_matches(target_base: str, listing_title: str) -> bool:
    base, _, _ = _listing_meta(listing_title)
    target = norm_ko(target_base)
    listing = norm_ko(base)
    if target in listing or listing in target:
        return True
    return listing.endswith(target) or target.endswith(listing)


def ko_plus_level_matches(parsed: ParsedKoItem, listing_title: str) -> bool:
    if not ko_base_matches(parsed.base_name, listing_title):
        return False
    _, plus, _ = _listing_meta(listing_title)
    if parsed.plus is not None and plus != parsed.plus:
        return False
    return True


def resolve_keywords(parsed: ParsedKoItem) -> list[str]:
    kws = [parsed.keyword, parsed.base_name]
    if parsed.plus is not None:
        kws.append(f"{parsed.base_name} +{parsed.plus}")
    elif parsed.base_name:
        for lvl in (7, 8, 9, 10, 11):
            kws.append(f"{parsed.base_name} +{lvl}")
    out: list[str] = []
    seen: set[str] = set()
    for kw in kws:
        k = kw.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def bng_listing_meta(title: str) -> tuple[str, int | None, bool]:
    """ByNoGame: 'Raptor (+11) Rev' gibi başlıklar."""
    reverse = bool(re.search(r"(?i)\brev\b|\(\s*reverse\s*\)", title))
    m = re.search(r"\(\+(\d+)\)", title) or re.search(r"\+(\d+)", title)
    plus = int(m.group(1)) if m else None
    base = re.sub(r"\(\+\d+\).*", "", title)
    base = re.sub(r"(?i)\s*rev.*", "", base).strip()
    return base, plus, reverse


def bng_name_matches(parsed: ParsedKoItem, title: str) -> bool:
    base, plus, reverse = bng_listing_meta(title)
    target = norm_ko(parsed.base_name)
    listing = norm_ko(base)
    if target not in listing and listing not in target:
        if not (listing.endswith(target) or target.endswith(listing)):
            return False
    if parsed.plus is not None and plus != parsed.plus:
        return False
    if parsed.reverse and not reverse:
        return False
    if not parsed.reverse and reverse:
        return False
    return True
