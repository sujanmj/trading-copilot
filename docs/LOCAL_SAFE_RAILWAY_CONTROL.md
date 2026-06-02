# Local Safe Mode & Railway Control Plane (Stage 46C)

Marker: `LOCAL_STAGE_46C_SAFE_RAILWAY_CONTROL`

## Overview

Railway is the **live control plane** for Telegram listener, scheduled briefs, and production API traffic.

Your **local laptop is safe by default**: Telegram listener/sends and trade execution are disabled unless you explicitly opt in.

The desktop/browser GUI can target either:

- **Local API** — `http://127.0.0.1:8080` (default)
- **Railway API** — from `VITE_API_BASE_URL` or `localStorage` key `ASTRAEDGE_API_BASE_URL`

Railway URLs are **never hardcoded** in committed source.

## Local safe defaults

When `APP_MODE` is not `railway` and `RAILWAY_ENVIRONMENT` is unset, `apply_local_safe_mode_defaults()` sets:

| Variable | Default |
|----------|---------|
| `DISABLE_TELEGRAM` | `1` |
| `DISABLE_TELEGRAM_SENDS` | `1` |
| `DISABLE_TELEGRAM_LISTENER` | `1` |
| `TELEGRAM_COMMANDS_ENABLED` | `0` |
| `TELEGRAM_BRIEF_SCHEDULER` | `0` |
| `TELEGRAM_TRADE_COMMANDS_ENABLED` | `0` |
| `DISABLE_TRADE_EXECUTION` | `1` |

Railway runners (`APP_MODE=railway` or `RAILWAY_ENVIRONMENT` set) **do not** receive these forced defaults.

## Telegram on local laptop

### Listener / analysis bot

`scripts/run_telegram_analysis_bot.py` refuses to start locally unless:

```bash
set ALLOW_LOCAL_TELEGRAM=1
python scripts/run_telegram_analysis_bot.py
```

Without it, the script prints:

```
LOCAL_TELEGRAM_DISABLED_RAILWAY_IS_LIVE
```

### Outbound sends (briefs, alerts)

Local scripts dry-run Telegram sends unless:

```bash
set ALLOW_LOCAL_TELEGRAM_SENDS=1
```

Dry-run prints:

```
LOCAL_TELEGRAM_SENDS_DRY_RUN
```

Example placeholder in GUI: paste your Railway service URL from the Railway dashboard (not stored in git).

### ⚠️ Never run two listeners

Do **not** run the local Telegram listener while Railway worker is active — both would poll the same bot token.

## Desktop GUI → Railway API

1. Open **OPS** drawer → **Developer / Ops — API target**
2. Enter your Railway service URL (from Railway dashboard)
3. Click **Save Railway API URL** (stored in `localStorage` as `ASTRAEDGE_API_BASE_URL`)
4. Click **Set API Railway**

Header badge shows **API: RAILWAY** with tooltip showing the active base URL.

### Switch back to local

Click **Set API Local** — GUI returns to `http://127.0.0.1:8080`.

### Environment override (Vite web mode)

```bash
set VITE_API_BASE_URL=https://your-service.up.railway.app
npm run web
```

Priority when target is Railway: `VITE_API_BASE_URL` → `ASTRAEDGE_API_BASE_URL` → fallback local.

## CORS

Railway API allows browser origins:

- `http://127.0.0.1:5173`
- `http://localhost:5173`

Additional origins via `ALLOWED_ORIGINS` (comma-separated).

## Validation

```bash
python scripts/test_local_safe_railway_mode.py
python scripts/validate_local_safe_railway_mode.py
python scripts/test_frontend_api_target.py
python scripts/validate_frontend_api_target.py
```

Expected markers:

- `LOCAL_SAFE_RAILWAY_MODE_TEST_OK`
- `LOCAL_SAFE_RAILWAY_MODE_OK`
- `FRONTEND_API_TARGET_TEST_OK`
- `FRONTEND_API_TARGET_OK`

## Helper module

`backend/config/local_safe_mode.py` — call `apply_local_safe_mode_defaults()` at the top of local runners before importing `backend.utils.config`.
