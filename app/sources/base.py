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
    offers: list | None = None  # [{price, url}] en ucuz 3 ilan


def short_error(exc: BaseException) -> str:
    """Kartta taşmayacak kısa hata — URL ve uzun httpx metni yok."""
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            code = exc.response.status_code
            if code == 429:
                return "istek limiti doldu — biraz sonra dene"
            if code == 403:
                return "erişim reddedildi"
            if code == 404:
                return "bulunamadı"
            return f"HTTP {code}"
        if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
            return "zaman aşımı — site yavaş yanıt verdi"
    except Exception:
        pass
    msg = str(exc).split(" for url ", 1)[0].strip()
    msg = msg.replace("Client error ", "").replace("Server error ", "")
    if len(msg) > 72:
        msg = msg[:70] + "…"
    return msg or type(exc).__name__


def attach_top_offers(res: PriceResult, rows: list, n: int = 3) -> None:
    """rows: (price, url) — en ucuz n ilanı res.offers'a yazar."""
    clean = []
    for row in rows or []:
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            continue
        try:
            price = float(row[0])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        url = row[1] or None
        clean.append((price, url))
    clean.sort(key=lambda x: x[0])
    top = clean[:n]
    res.offers = [{"price": p, "url": u} for p, u in top]
    if top:
        res.price = top[0][0]
        if top[0][1]:
            res.url = top[0][1]

