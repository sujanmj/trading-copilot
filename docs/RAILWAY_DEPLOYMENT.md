# Railway Deployment — Trading Copilot (Stage 46A)

Prepare-only guide for deploying AstraEdge on Railway. **Do not enable order execution.**

## Architecture

| Service | Start command | Purpose |
|---------|---------------|---------|
| `astraedge-web` | `python scripts/run_railway_web.py` | FastAPI backend, health endpoint, optional static GUI |
| `astraedge-telegram-worker` | `python scripts/run_railway_telegram_worker.py` | Telegram analysis bot commands (research only) |
| `astraedge-morning-brief` (cron) | `python scripts/run_railway_morning_brief.py` | 08:00 IST morning brief |
| `astraedge-market-close` (cron) | `python scripts/run_railway_market_close.py` | 16:30 IST close summary |
| `astraedge-overnight-brief` (cron) | `python scripts/run_railway_overnight_brief.py` | 06:30 IST overnight/global brief |

Cron schedules use **UTC** on Railway (Mon–Fri):

| Job | UTC cron | IST equivalent |
|-----|----------|----------------|
| Morning brief | `30 2 * * 1-5` | 08:00 IST |
| Market close | `0 11 * * 1-5` | 16:30 IST |
| Overnight brief | `0 1 * * 1-5` | 06:30 IST |

Each cron script runs **one job** and exits. They do not start uvicorn or long-running listeners.

## Volume / data path

Mount a persistent volume at **`/app/data`**.

Set:

```bash
RAILWAY_DATA_DIR=/app/data
```

New Railway scripts use `backend.storage.data_paths.get_data_path()`. Legacy modules may still read `backend.utils.config.DATA_DIR` (repo `data/` locally). Document any remaining legacy paths before migrating.

## Service start commands

### Procfile

```
web: TZ=Asia/Kolkata python scripts/run_railway_web.py
telegram: TZ=Asia/Kolkata python scripts/run_railway_telegram_worker.py
```

### railway.json (web default)

```json
"startCommand": "TZ=Asia/Kolkata python scripts/run_railway_web.py"
```

## Required environment variables

Railway injects some values automatically. Set the rest in the Railway dashboard — **do not commit `config/keys.env`**.

### Platform / runtime

| Variable | Web | Worker | Cron | Notes |
|----------|-----|--------|------|-------|
| `RAILWAY_ENVIRONMENT` | yes | yes | yes | Set by Railway |
| `PORT` | yes | optional | n/a | Railway sets for web |
| `RAILWAY_DATA_DIR` | yes | yes | yes | e.g. `/app/data` |
| `APP_MODE` | `railway` | `railway` | `railway` | |
| `LOCAL_DEV_MODE` | `0` | `0` | `0` | |
| `LOCAL_ONLY` | `0` | `0` | `0` | |
| `TZ` | `Asia/Kolkata` | `Asia/Kolkata` | `Asia/Kolkata` | |

### Telegram — worker service

| Variable | Value | Notes |
|----------|-------|-------|
| `DISABLE_TELEGRAM` | `0` | |
| `DISABLE_TELEGRAM_SENDS` | `0` | |
| `DISABLE_TELEGRAM_LISTENER` | `0` | Worker only |
| `TELEGRAM_COMMANDS_ENABLED` | `1` | Required |
| `TELEGRAM_TRADE_COMMANDS_ENABLED` | `0` | Must stay off |
| `DISABLE_TRADE_EXECUTION` | `1` | Must stay on |
| `TELEGRAM_BRIEF_SCHEDULER` | `0` or `1` | Optional IST scheduler in worker |
| `TELEGRAM_ALLOW_AI_SUMMARY` | `0` | |
| `TELEGRAM_ALLOW_CLAUDE` | `0` | |
| `TELEGRAM_BOT_TOKEN` | secret | Railway env only |
| `TELEGRAM_CHAT_ID` | secret | Railway env only |

### Telegram — web service

Web service **does not** start the Telegram listener unless `ENABLE_TELEGRAM_IN_WEB=1`. Default: listener disabled.

### AI / broker keys

Read from Railway env only (no `config/keys.env` on Railway):

- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY` / `GOOGLE_API_KEY_1` …
- `GEMINI_API_KEY`
- `GROQ_API_KEY` / pool keys
- `API_KEY` (HTTP API auth)
- Optional broker keys (`ANGEL_*`) — display/research only, **no order execution**

## Safety: no order execution

- `TRADE_EXECUTION_PERMANENTLY_DISABLED = True` in code
- `DISABLE_TRADE_EXECUTION=1` on all Railway services
- `TELEGRAM_TRADE_COMMANDS_ENABLED=0` on worker and cron jobs
- Telegram responses are research/shadow mode only

## Pre-deploy validation (local)

Run from repo root:

```bash
python scripts/validate_railway_env.py --local-check
python scripts/railway_smoke_local.py
python scripts/validate_railway_readiness_pack.py
python scripts/railway_preflight_audit.py
python scripts/final_local_90_gate.py
python scripts/live_system_smoke.py --frontend-mode web --frontend-base http://127.0.0.1:5173
python scripts/validate_market_memory.py
python scripts/validate_historical_market_memory.py
```

Success markers:

- `RAILWAY_ENV_VALIDATE_OK`
- `RAILWAY_SMOKE_LOCAL_OK`
- `RAILWAY_READINESS_PACK_OK` / `RAILWAY_STAGE_46A_READINESS_PACK`
- `RAILWAY_PREFLIGHT_AUDIT_OK`

## Post-deploy verification

1. `curl https://YOUR_APP.railway.app/api/health` → HTTP 200
2. Telegram worker logs: credentials present (boolean only), listener online
3. Trigger a cron job manually once; confirm single Telegram message and clean exit
4. Confirm `/app/data` receives DB and runtime JSON updates

## Rollback

1. In Railway, redeploy the previous successful deployment from **Deployments → Rollback**
2. If env regression: restore prior variable snapshot from Railway history
3. If bad cron release: disable cron services until fixed; web + worker can stay up
4. Re-run local validation pack before next deploy attempt

## GUI note

Electron GUI (`frontend/`) is **local only**. Railway web service exposes the FastAPI backend; use local Electron or a static web build pointed at the deployed API URL.
