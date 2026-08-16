# Skin Arbitrage Panel

A watercolor-themed web panel that tracks **CS2 item prices across five marketplaces** and
sends a Telegram alert the moment an opportunity appears.

> Web-scraping + multi-source price aggregation project with a background monitoring engine,
> REST API and real-time alerting.

**Sources:** Skinport · DMarket · Bitskins · Kopazar · GameSatis
All prices are converted to a common currency (FX from open.er-api.com, 6-hour cache) for
apples-to-apples comparison.

## Features

- **Multi-source scraping** — official APIs where available, HTML parsing where not (Kopazar, GameSatis)
- **Background engine** — scans all items on a configurable interval
- **Smart alerts** via Telegram:
  - price drops **below** a threshold (per source or "cheapest")
  - price rises **above** a threshold
  - **cross-site spread** (arbitrage) exceeds a set percentage
- **Currency normalization** with cached FX rates
- **Alert cooldown** (30 min per alert) to avoid spam
- **Dockerized** for 24/7 self-hosting

## Tech stack

`Python` · `FastAPI` · `httpx` · `BeautifulSoup` · `SQLite` · `Docker` · Telegram Bot API

## Getting started

```bash
git clone https://github.com/bedirrhaan/item_skin_arbitrage.git
cd item_skin_arbitrage
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

Open **http://127.0.0.1:8090**

### Docker

Panel ve Redis aynı Compose ağında çalışır (`REDIS_URL=redis://redis:6379/0`).

```bash
cp .env.example .env   # isteğe bağlı: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
docker compose up -d --build
```

Panel **http://127.0.0.1:8000** (veya sunucu IP). Veri `panel-data`, önbellek `redis-data` volume'unda kalır.

## Usage

1. **Add items** using the full Steam market_hash_name, one per line:
   `AK-47 | Redline (Field-Tested)` — `StatTrak™` and `★` are supported.
2. **Telegram** — create a bot via @BotFather, enter the token + chat id, verify with "Test Message"
   (remember to `/start` your bot once).
3. **Create alerts** from an item card: below/above threshold or cross-site spread.
4. **Settings** — scan interval (min), Bitskins API key, active sources.

## Project structure

```
app/
  main.py       FastAPI app + REST API
  engine.py     price-collection loop + alert engine
  db.py         SQLite schema & helpers
  fx.py         currency rates (USD/EUR → TRY)
  itemname.py   market_hash_name parsing (wear, StatTrak, ★)
  telegram.py   Telegram Bot API sender
  sources/      source connectors (one module per site)
static/         frontend (watercolor theme)
```

## Notes

- **Bitskins** prices require a free API key entered in Settings.
- **Kopazar / GameSatis** are HTML-scraped; update `app/sources/*.py` if the sites change layout.
- **Skinport** has strict rate limits; the panel fetches the full list once and caches it for 5 min.

## Disclaimer

For educational purposes. Respect each marketplace's Terms of Service and rate limits.
