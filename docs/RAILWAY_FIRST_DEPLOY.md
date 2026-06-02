# Railway First Deploy — Safe Launch Checklist (Stage 46B)

Prepare-only guide for the **first** Railway deployment of AstraEdge. **Do not enable order execution.**

See also: [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md) for architecture and Stage 46A readiness.

Marker: `RAILWAY_STAGE_46B_FIRST_DEPLOY_PACK`

---

## 1. Pre-push local checks

Run from repo root **before every push** that will trigger a Railway deploy:

```bash
python scripts\final_local_90_gate.py
python scripts\railway_preflight_audit.py
python scripts\validate_railway_env.py --local-check
python scripts\railway_smoke_local.py
python scripts\check_no_secrets_before_push.py
python scripts\validate_railway_first_deploy_pack.py
```

Success markers:

| Script | Expected output |
|--------|-----------------|
| `final_local_90_gate.py` | gate pass marker |
| `railway_preflight_audit.py` | `RAILWAY_PREFLIGHT_AUDIT_OK` |
| `validate_railway_env.py --local-check` | `RAILWAY_ENV_VALIDATE_OK` |
| `railway_smoke_local.py` | `RAILWAY_SMOKE_LOCAL_OK` |
| `check_no_secrets_before_push.py` | `NO_SECRETS_BEFORE_PUSH_OK` |
| `validate_railway_first_deploy_pack.py` | `RAILWAY_FIRST_DEPLOY_PACK_OK` |

Optional extended validation (recommended before first deploy):

```bash
python scripts\live_system_smoke.py --frontend-mode web --frontend-base http://127.0.0.1:5173
python scripts\validate_market_memory.py
python scripts\validate_historical_market_memory.py
```

---

## 2. Git push checklist

- [ ] Run `git status` — review every staged and unstaged file
- [ ] **Never commit** `config/keys.env` (must stay gitignored)
- [ ] **Never commit** `.venv/` or `venv/`
- [ ] **Never commit** recovery backups or zip archives unless intentionally added to `.gitignore` first
- [ ] **Never commit** `data/*.db` or runtime JSON under `data/`
- [ ] Push only code, docs, and scripts — no secrets, no local databases
- [ ] Run `python scripts\check_no_secrets_before_push.py` immediately before `git push`

```bash
git status
git diff --stat
python scripts\check_no_secrets_before_push.py
git push origin HEAD
```

---

## 3. Railway services to create

Create **five** services from the same repo. Cron schedules use **UTC** (Mon–Fri).

### Service 1 — Web API

| Field | Value |
|-------|-------|
| **Name** | `astraedge-web` |
| **Type** | Web |
| **Start command** | `TZ=Asia/Kolkata python scripts/run_railway_web.py` |

Exposes FastAPI at `/api/health` and debug JSON endpoints. Does **not** start the Telegram listener by default.

### Service 2 — Telegram worker

| Field | Value |
|-------|-------|
| **Name** | `astraedge-telegram-worker` |
| **Type** | Worker |
| **Start command** | `TZ=Asia/Kolkata python scripts/run_railway_telegram_worker.py` |

Handles Telegram bot commands (research/shadow mode only).

### Cron 1 — Morning brief

| Field | Value |
|-------|-------|
| **Name** | `astraedge-morning-brief` |
| **Schedule (UTC)** | `30 2 * * 1-5` |
| **IST equivalent** | 08:00 IST |
| **Command** | `TZ=Asia/Kolkata python scripts/run_railway_morning_brief.py` |

### Cron 2 — Market close

| Field | Value |
|-------|-------|
| **Name** | `astraedge-market-close` |
| **Schedule (UTC)** | `0 11 * * 1-5` |
| **IST equivalent** | 16:30 IST |
| **Command** | `TZ=Asia/Kolkata python scripts/run_railway_market_close.py` |

### Cron 3 — Overnight brief

| Field | Value |
|-------|-------|
| **Name** | `astraedge-overnight-brief` |
| **Schedule (UTC)** | `0 1 * * 1-5` |
| **IST equivalent** | 06:30 IST |
| **Command** | `TZ=Asia/Kolkata python scripts/run_railway_overnight_brief.py` |

Each cron runs **one job** and exits. They do not start uvicorn or long-running listeners.

---

## 4. Railway environment variables

Set in the Railway dashboard — **never commit secrets**. Use placeholders below; paste real values only in Railway.

### Platform / runtime (all services)

```bash
APP_MODE=railway
LOCAL_DEV_MODE=0
LOCAL_ONLY=0
RAILWAY_ENVIRONMENT=production
RAILWAY_DATA_DIR=/data
TZ=Asia/Kolkata
PORT=<Railway provided — web service only>
API_KEY=<your-http-api-key>
```

### Telegram — worker + cron services

```bash
DISABLE_TELEGRAM=0
DISABLE_TELEGRAM_SENDS=0
DISABLE_TELEGRAM_LISTENER=0
TELEGRAM_COMMANDS_ENABLED=1
TELEGRAM_TRADE_COMMANDS_ENABLED=0
DISABLE_TRADE_EXECUTION=1
TELEGRAM_BRIEF_SCHEDULER=1
TELEGRAM_ALLOW_AI_SUMMARY=0
TELEGRAM_ALLOW_CLAUDE=0
TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
TELEGRAM_CHAT_ID=<your-telegram-chat-id>
```

### Telegram — web service

Web does **not** need the listener unless `ENABLE_TELEGRAM_IN_WEB=1`. Default: listener disabled on web.

```bash
DISABLE_TELEGRAM=1
DISABLE_TELEGRAM_LISTENER=1
DISABLE_TELEGRAM_SENDS=1
DISABLE_TRADE_EXECUTION=1
TELEGRAM_TRADE_COMMANDS_ENABLED=0
```

### AI provider keys (Railway env only — no `config/keys.env`)

```bash
ANTHROPIC_API_KEY=<your-anthropic-key>
GOOGLE_API_KEY_1=<your-google-key-1>
GOOGLE_API_KEY_2=<your-google-key-2>
GOOGLE_API_KEY_3=<your-google-key-3>
GROQ_API_KEY_1=<your-groq-key-1>
GROQ_API_KEY_2=<your-groq-key-2>
GROQ_API_KEY_3=<your-groq-key-3>
```

Optional aliases if your setup uses them: `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`.

### Broker keys (display/research only — no order execution)

```bash
ANGEL_API_KEY=<your-angel-api-key>
ANGEL_CLIENT_ID=<your-angel-client-id>
ANGEL_PIN=<your-angel-pin>
ANGEL_TOTP_SECRET=<your-angel-totp-secret>
```

### Safety invariants (must stay on)

- `DISABLE_TRADE_EXECUTION=1` on **all** services
- `TELEGRAM_TRADE_COMMANDS_ENABLED=0` on worker and crons
- `TRADE_EXECUTION_PERMANENTLY_DISABLED = True` in code (do not change)

---

## 5. Volume mount — `/data`

Mount a **persistent Railway volume** at:

```
/data
```

Set `RAILWAY_DATA_DIR=/data` on every service (web, worker, crons).

**What persists there:**

- SQLite prediction DB and journal files
- Runtime JSON snapshots and report packs
- Cached analytics outputs written by `backend.storage.data_paths.get_data_path()`

**Local vs Railway:**

- **Local dev** uses repo `data/` when `RAILWAY_DATA_DIR` is unset
- **Railway** uses `/data` on the mounted volume
- Do not copy `config/keys.env` to Railway — inject keys via dashboard env vars only

After first deploy, confirm the web service can write under `/data` (check logs for data-path errors).

---

## 6. Post-deploy checks

### 6.1 Health endpoint

```bash
curl -s https://YOUR-RAILWAY-APP.up.railway.app/api/health
```

Expect HTTP 200 and JSON with `"status": "ok"` or `"degraded"` (not HTML, not 500).

### 6.2 Automated smoke (required)

```bash
python scripts\railway_post_deploy_smoke.py --base-url https://YOUR-RAILWAY-APP.up.railway.app
```

Optional if `API_KEY` is set on Railway:

```bash
python scripts\railway_post_deploy_smoke.py --base-url https://YOUR-RAILWAY-APP.up.railway.app --api-key %API_KEY%
```

Success marker: `RAILWAY_POST_DEPLOY_SMOKE_OK`

Endpoints checked:

- `GET /api/health`
- `GET /api/debug/final-confidence`
- `GET /api/debug/daily-report-pack`
- `GET /api/debug/stock-decision?mode=today`
- `GET /api/debug/stock-decision?mode=tomorrow`
- `GET /api/debug/aihub-tab/brain`
- `GET /api/debug/aihub-tab/scan`
- `GET /api/debug/aihub-tab/market`

All must return JSON (not HTML) and must not return HTTP 500.

### 6.3 Telegram worker (manual)

In Telegram, send these commands to the bot (research mode only):

| Command | Expected |
|---------|----------|
| `/help` | Command list |
| `/status` | Runtime status summary |
| `/action plan` | Action plan text |
| `/aihub brain full` | AI Hub brain payload |
| `/today` | Today confluence summary |
| `/tomorrow` | Tomorrow watchlist summary |
| `/why reliance` | Ticker explanation |

Check Railway worker logs: credentials present (boolean only), listener online, no secret values printed.

### 6.4 Cron smoke (optional first day)

Manually trigger each cron once from Railway dashboard. Confirm:

- Single Telegram message per job
- Process exits cleanly (no restart loop)

---

## 7. Rollback steps

If the first deploy misbehaves, roll back in this order:

1. **Disable Telegram worker** — stop `astraedge-telegram-worker` in Railway (prevents bad commands/alerts)
2. **Disable cron jobs** — pause `astraedge-morning-brief`, `astraedge-market-close`, `astraedge-overnight-brief`
3. **Keep web only** — leave `astraedge-web` running if the API is healthy; otherwise disable it too
4. **Revert deploy** — Railway **Deployments → Rollback** to the previous successful build, or redeploy last known-good Git commit
5. **Restore env** — if env regression, restore prior variable snapshot from Railway history
6. **Local backup** — repo `recovery/` contains checkpoint backups; local `data/` is unchanged by Railway rollback
7. **Re-validate locally** before next deploy attempt:

```bash
python scripts\check_no_secrets_before_push.py
python scripts\validate_railway_first_deploy_pack.py
python scripts\railway_preflight_audit.py
python scripts\final_local_90_gate.py
```

---

## Quick reference

| Item | Value |
|------|-------|
| Health URL | `https://YOUR-APP.up.railway.app/api/health` |
| Data volume | `/data` → `RAILWAY_DATA_DIR=/data` |
| Order execution | **Permanently disabled** |
| GUI | Local Electron only — not deployed to Railway |
