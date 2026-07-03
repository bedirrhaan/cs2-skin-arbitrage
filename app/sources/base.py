"""Kaynak bağlayıcıları için ortak tipler."""
from __future__ import annotations
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class PriceResult:
    source: str
    price: float | None = None   # kaynağın kendi para biriminde
    currency: str = "USD"
    url: str | None = None
    error: str | None = None
