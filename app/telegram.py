"""Telegram Bot API üzerinden mesaj gönderimi."""
from __future__ import annotations
import httpx


async def send_message(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    if not token or not chat_id:
        return False, "Telegram token veya chat id ayarlanmamış"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
            data = r.json()
            if data.get("ok"):
                return True, "ok"
            return False, str(data.get("description", "bilinmeyen hata"))
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
