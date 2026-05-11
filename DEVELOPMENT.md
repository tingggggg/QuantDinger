# QuantDinger — Development Guide

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Docker & Docker Compose | 20+ | required for the default setup |
| Python | 3.10+ | only if running backend outside Docker |
| Node.js | 18+ | only if you maintain the private Vue repo and sync `dist/` here |

## Quick Start (Docker)

```bash
# 1. Clone
git clone https://github.com/<your-org>/quantdinger.git
cd quantdinger

# 2. Configure
cp backend_api_python/env.example backend_api_python/.env
# Edit .env — at minimum set SECRET_KEY to a random value:
#   SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
# Optional: project-root `.env` with `IMAGE_PREFIX` if Docker Hub pulls are slow (see .env.example).

# 3. Launch
docker compose up -d --build

# 4. Open http://localhost:8888
```

The stack includes:

| Service | Port | Description |
|---------|------|-------------|
| `frontend` | 8888 | Nginx serving Vue SPA |
| `backend` | 5000 | Flask API (gunicorn) |
| `postgres` | 5432 | PostgreSQL 16 |
| `redis` | 6379 | Cache layer (LRU, 128 MB) |

## Project Structure

```
quantdinger/
├── backend_api_python/          # Flask API
│   ├── app/
│   │   ├── config/              # Settings, API keys, DB config
│   │   ├── data_providers/      # Market data fetchers (crypto, forex, …)
│   │   ├── data_sources/        # Exchange/broker adapters (CCXT, yfinance, …)
│   │   ├── routes/              # Flask Blueprints (REST endpoints)
│   │   ├── services/            # Business logic (strategy, trading, AI, …)
│   │   └── utils/               # DB helpers, auth, caching, logger
│   ├── migrations/              # SQL schema + seed data
│   ├── gunicorn_config.py       # Production WSGI config
│   ├── run.py                   # App entrypoint
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── dist/                    # Pre-built SPA (sync from private Vue repo)
│   ├── Dockerfile               # Nginx image; copies `frontend/dist` only
│   └── nginx.conf
├── docs/                        # Changelog, architecture notes
├── docker-compose.yml
└── README.md
```

## Running Backend Locally (without Docker)

```bash
cd backend_api_python
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp env.example .env   # edit .env
python run.py
```

The dev server starts on `http://localhost:5000` with auto-reload.

## Frontend Vue source — clone & sync workflow

The open-source tree **does not** contain Vue source. The UI lives in
[QuantDinger-Vue](https://github.com/brokermr810/QuantDinger-Vue). The recommended
layout clones it inside this repo as `quantdinger_vue/` — already gitignored, so
it stays out of the main repo's git index.

```
QuantDinger/
├── backend_api_python/
├── frontend/dist/        ← committed build artefact (what Docker copies)
├── quantdinger_vue/      ← Vue source (gitignored)
└── scripts/sync-frontend-dist.sh
```

### One-time setup

```bash
cd /path/to/QuantDinger
git clone https://github.com/brokermr810/QuantDinger-Vue.git quantdinger_vue
( cd quantdinger_vue && npm install --legacy-peer-deps )
```

### Day-to-day: build + sync + rebuild container

```bash
./scripts/sync-frontend-dist.sh
```

What it does:
1. `npm install --legacy-peer-deps` + `npm run build` inside `quantdinger_vue/`
2. Replaces `frontend/dist/` with the fresh build
3. Runs `docker compose up -d --build frontend`

Useful flags:

| Flag | Effect |
|------|--------|
| `--no-build`  | Skip npm; just sync an already-built `dist/` |
| `--no-docker` | Skip the container rebuild |

If you keep the Vue repo somewhere else, override the path:

```bash
QUANTDINGER_VUE_SRC=~/work/QuantDinger-Vue ./scripts/sync-frontend-dist.sh
```

### Hot-reload dev loop (no Docker rebuild per change)

While iterating on Vue code, run the backend in Docker but the Vue dev server
natively — far faster than rebuilding the nginx image each time:

```bash
# Terminal 1 — backend stack only
docker compose up -d postgres redis backend

# Terminal 2 — vue-cli dev server (proxies /api to localhost:5000)
cd quantdinger_vue && npm run serve
```

Open <http://localhost:8000> (port + `/api` proxy are pre-configured in
`quantdinger_vue/vue.config.js`). Only run `sync-frontend-dist.sh` when you
want a production build inside the Docker container (for deploys or demos).

> Legacy script `scripts/build-frontend.sh` still works and requires
> `QUANTDINGER_VUE_SRC` to be set explicitly (no Docker rebuild step).

## Adding a New Data Source

1. Create `backend_api_python/app/data_sources/<name>.py` implementing a class
   with `get_ticker(symbol)` and `get_kline(symbol, timeframe, limit)`.
2. Register it in `data_sources/factory.py`.
3. If it serves the global market dashboard, add a fetcher in
   `data_providers/` and wire it into the fallback chain.

## Adding a New Exchange (Live Trading)

1. Create `backend_api_python/app/services/live_trading/<exchange>.py`
   inheriting from `BaseLiveTrading`.
2. Implement `place_order`, `cancel_order`, `get_balance`, etc.
3. Register in `live_trading/factory.py`.

## Environment Variables

See `backend_api_python/env.example` for the full list.  Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | **yes** | JWT signing key — must be changed from default |
| `ADMIN_USER` / `ADMIN_PASSWORD` | yes | Initial admin credentials |
| `TWELVE_DATA_API_KEY` | no | Twelve Data for forex/commodities |
| `ADANOS_API_KEY` | no | Optional Adanos Market Sentiment for US stock tickers |
| `OPENAI_API_KEY` or `OPENROUTER_API_KEY` | no | AI analysis features |
| `CACHE_ENABLED` | no | Set `true` to use Redis (auto-set in Docker) |

## Testing

```bash
cd backend_api_python
pip install pytest
pytest tests/ -v
```

## Troubleshooting

- **"apikey parameter is incorrect"** from Twelve Data — verify `TWELVE_DATA_API_KEY` in `.env`; Chinese stock data requires a paid plan.
- **Heatmap "暂无数据"** — usually caused by NaN in yfinance data; the global JSON encoder now sanitises all NaN/Inf to `null`.
- **Redis connection refused** — ensure `redis` service is running (`docker compose up -d redis`); set `CACHE_ENABLED=false` to fall back to in-memory cache.
