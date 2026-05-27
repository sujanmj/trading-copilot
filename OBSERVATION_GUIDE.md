# Observation Guide — 2-Week Calibration Phase

How to monitor Trading Copilot during observational learning without overreacting or breaking production stability.

## Daily monitoring (5 minutes)

| Check | Healthy | Investigate |
|-------|---------|-------------|
| `/status` | 🌙 idle overnight, ✅ during session | ❌ stale during market hours |
| `/stats` vs `/outcomes` | Same wins/losses/pending | Mismatch >24h |
| Lifecycle | COMPLETE after EOD; IDLE overnight | STALE during market session |
| `/elite` vs `/opps` | Consistent labels (HIGH vs WATCHLIST) | Raw HIGH in opps while elite empty |
| Pending count | Gradual decay after EOD | Monotonic growth >7 days |

## What to monitor weekly

1. **Win rate (actionable)** — wins / (wins + losses + neutral + partials)
2. **Calibration health** — GUI Calib tab after 30+ samples
3. **Elite pass rate** — how many setups exceed 72% meta-labeler gate
4. **False positives in panic regime** — WATCHLIST items that still alert
5. **Self-healing events** — OPS recovery lines (should be rare)

## Healthy behavior

- Pending predictions expire or decay confidence after TTL
- Night mode: no stale analyzer warnings
- Telegram commands debounced — no duplicate "Sending..." within 3s
- Stats refresh on `/stats` and `/outcomes` from SQLite live
- EOD pipeline completes once per session without recursive reruns

## Unhealthy behavior (act within 24h)

- Evaluated count stuck at 0 while wins visible in lifecycle notes
- `/brain` blocked overnight with stale error (not night banner)
- Duplicate brain pushes from double recovery loops
- Pending >150 with no EOD expiry progress for 3+ days
- Win rate swings >30 points day-over-day without regime change

## Expected calibration evolution (2 weeks)

| Week | Expected |
|------|----------|
| Week 1 | Sample size grows; calibration dashboard populates; elite gate may reject most setups |
| Week 2 | Confidence buckets stabilize; adaptive thresholds drift slowly; win rate variance narrows |

**Do not** change architecture, orchestration, or infrastructure during observation.

**Do** adjust env thresholds only with evidence:

- `TELEGRAM_OPPS_LIMIT` (default 10)
- `EXPIRE_AFTER_DAYS` (default 7)
- `UNRESOLVED_EXPIRE_DAYS` (default 5)
- Elite threshold (code: 0.72 in meta_labeler)

## Win-rate stabilization

Early phase win rates are noisy (small sample). Expect:

- Actionable win rate 40–70% with <20 samples — normal variance
- Stabilization after ~30 evaluated actionable outcomes
- EXPIRED/INVALIDATED excluded from win-rate denominator by design

## Regime adaptation signals (working correctly)

- Panic regime: fewer elite setups; more WATCHLIST labels
- Contradiction pressure high: opps rank lower; stronger penalties in logs
- Macro uncertainty: bullish opps downgraded or filtered
- Calibration dashboard shows different performance by day-type

## What NOT to overreact to

- Zero elite setups for several sessions (guardrails working)
- High pending count mid-week (resolves at EOD expiry)
- Idle collectors overnight (by design)
- Single-day loss streak with <10 samples
- `/ask` refusing generic ticker picks (retrieval-first behavior)

## When retraining/adaptation should occur

- After 30+ actionable evaluated outcomes (automatic adaptive calibration)
- After full 2-week observation with documented false-positive patterns
- Never mid-session during market hours unless critical production bug

## Verification commands

```
/status
/stats
/outcomes
/elite
/opps
/brain   (test overnight vs market hours)
```

Local validation:

```bash
python scripts/validate_consistency.py
```

## Escalation path

1. Check `DEPLOY_CHECKLIST.md` rollback section
2. Review Railway logs for EOD stage failures
3. OPS panel → lifecycle + reliability sections
4. Only then consider threshold tuning — not architecture changes
