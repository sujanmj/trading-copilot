# Deploy Checklist — Trading Copilot

Production consistency + night-mode + Telegram dedupe release.

## Pre-deploy

- [ ] Railway volume mounted at `/app/data`
- [ ] `TZ=Asia/Kolkata` set on service
- [ ] `API_KEY`, Telegram, and AI keys configured
- [ ] Git branch `main` contains latest consistency commit

## Deploy steps

1. Push to `origin/main` (Railway auto-deploy) or trigger manual deploy
2. Watch build logs for Nixpacks Python 3.11 success
3. Confirm startup lines:
   - `Uvicorn running`
   - `TELEGRAM LISTENER` online
   - `master_scheduler` bound (unless `DISABLE_SCHEDULER=1`)

## Post-deploy verification (5 min)

```bash
curl https://YOUR_APP.railway.app/api/health
curl -H "X-API-Key: YOUR_KEY" https://YOUR_APP.railway.app/api/all | jq '.runtime.panels.lifecycle'
```

Telegram:

| Command | Expected |
|---------|----------|
| `/stats` | Wins/losses/pending match SQLite (not stale zeros) |
| `/outcomes` | Same counts as `/stats` |
| `/elite` | >72% gate or explicit none message |
| `/opps` | Max 10 items, WATCHLIST if below elite |
| `/brain` (overnight) | Night mode banner, **no** stale analyzer warning |
| `/global` | Single status message, global mood payload |

Run locally on Railway shell or dev machine:

```bash
python scripts/validate_consistency.py
```

## Expected logs

- `[STATS] stats_exporter` with non-zero wins when DB has resolved outcomes
- `[BRAIN] Night/idle mode — intel age Xh accepted` overnight
- No repeated `Sending global impact` within 3s debounce window

## Night-mode behavior

- Collectors show idle copy in `/status` and GUI OPS
- Lifecycle shows **IDLE** — "Lifecycle idle until next market session"
- `/brain` header: "Night mode — awaiting pre-market intelligence cycle"
- Watchdog stale threshold extended (5h default)

## EOD behavior (Mon–Fri ~15:45 IST)

1. `expire_stale_pending()` runs
2. Outcome evaluation updates SQLite
3. `export_stats()` writes `stats_data.json` from SQLite aggregates
4. Lifecycle → **COMPLETE**
5. Calibration snapshot syncs from same aggregate

## Calibration learning verification

- GUI **Calib** tab: evaluated count matches `/stats`
- After 30+ actionable outcomes, calibration message changes from "Awaiting sample size"
- `data/calibration_history.json` → `latest.wins` matches SQLite

## Elite filtering verification

- `/elite` empty → `/opps` shows WATCHLIST labels, not raw HIGH
- `data/high_conviction_alerts.json` timestamp fresh after EOD/meta-labeler

## Self-healing cooldown

- Max 4 recoveries/hour (`recovery_loop.py`)
- Max 3 EOD recoveries/day (`eod_recovery.py`)
- No duplicate orchestrator threads in logs

## Rollback

1. Railway → Deployments → redeploy previous successful deployment
2. Volume `/app/data` is preserved — SQLite and JSON exports remain
3. If stats export corrupt: run `/stats` on Telegram (triggers live SQLite refresh)
4. Emergency: `python -m backend.storage.stats_exporter` on shell with volume attached

## Failure signals

| Signal | Action |
|--------|--------|
| `/stats` Evaluated 0 but lifecycle shows wins | Re-run `/stats`; check DB path on volume |
| Stale warning overnight | Verify `market_hours.get_operational_status()` period |
| Duplicate Telegram status | Check debounce env `TELEGRAM_CMD_DEBOUNCE_SEC` |
| GUI ≠ Telegram counts | Confirm `/api/all` runtime overlay (live aggregate) |
