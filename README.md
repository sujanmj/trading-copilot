# AstraEdge Trading Copilot

AstraEdge Trading Copilot is an Indian market intelligence and paper-trading research copilot.

It combines:
- trusted news refresh
- feed verification
- macro shock sentinel
- scanner/gainer freshness guard
- opening rally radar
- tradecards
- catalyst radar
- chart-pattern context
- screener/long-term memory
- Telegram command workflows

**Current mode:** paper/research only  
**Current Telegram build:** AstraEdge 52H  
**Primary workflow:** Telegram command interface + Railway backend + optional local dashboard

---

## Latest Build: AstraEdge 52H

### Unified News Source Aggregator

AstraEdge 52H introduces a unified news provider registry.

- `/news refresh` refreshes all enabled trusted news providers together
- `/news refresh SYMBOL` checks all enabled providers for one ticker/company
- `/news sources` shows provider health/freshness
- `/refresh status` shows news/scanner/macro/source freshness
- provider failures return `NEWS_REFRESH_PARTIAL` (not full refresh failure)
- Mint RSS / LiveMint is included as one provider inside the unified collector

No Mint-specific refresh command is documented or required.

---

## Current News Providers

Enabled/provider slots in the current setup:

- ET Markets
- NDTV Profit
- Mint RSS / LiveMint
- BSE Corporate Announcements
- RBI Press Releases
- SEBI Press Releases
- Investing.com India
- Business Standard RSS (may show HTTP403/stale depending on source availability)
- MCX (may show HTTP403/stale depending on source availability)
- NSE / PIB (may show missing until feed stability improves)

---

## Core Telegram Commands

### Health / QA
- `/health`
- `/clock`
- `/status`
- `/qa`
- `/qa smoke`
- `/qa full`
- `/qa last`
- `/qa explain`

### News
- `/news`
- `/news refresh`
- `/news refresh SYMBOL`
- `/news sources`

### Refresh
- `/refresh`
- `/refresh quick`
- `/refresh scanner`
- `/refresh market`
- `/refresh status`
- `/refresh full`

### My Feed
- `/feed <market news text>`
- `/feed verify FEED_ID`
- `/feed remove FEED_ID`
- `/feed restore FEED_ID`
- `/myfeed today`
- `/myfeed list`
- `/myfeed scan`

### Macro
- `/macro`
- `/macro today`
- `/macro explain`

### Opening / Tradecards
- `/radar`
- `/gainers`
- `/tradecards`
- `/tradecard`
- `/tradecard today`
- `/tradecard explain`
- `/tradecard journal`
- `/tradecard outcome`

### Catalysts
- `/catalyst SYMBOL`
- `/catalysts`
- `/catalysts today`
- `/catalysts explain SYMBOL`

### Patterns
- `/patterns`
- `/pattern`
- `/pattern SYMBOL`
- `/candles SYMBOL`

### Screener / Long-Term
- `/screener status`
- `/screener latest`
- `/screener import longterm`
- `/longterm`
- `/longterm explain SYMBOL`

---

## Architecture

```text
Telegram
  -> FastAPI backend (Railway)
    -> command router
      -> unified news provider registry
      -> my feed + feed verification
      -> macro shock sentinel
      -> market/source freshness guard
      -> opening rally radar
      -> tradecards
      -> catalyst + chart pattern context
      -> screener + long-term memory
      -> storage layer
         -> /app/data (persistent volume)
```

---

## Repository Layout

- `backend/` — Python backend services, collectors, Telegram logic, analysis/routing
- `scripts/` — phase/regression test scripts and local validation helpers
- `frontend/` — optional local Electron dashboard
- `data/` — runtime/generated JSON/SQLite artifacts (do not commit)
- `test/` — additional test utilities
- `tests-gui/` — GUI-facing tests
- `docs/` — documentation and notes
- `reports/` — generated reports and analysis artifacts

---

## Setup (Windows PowerShell)

```powershell
git clone <your-repo-url>
cd trading-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python run_local.py
```

Fill `.env` with only required local keys. Do not commit secrets.

---

## Railway Deployment

Railway deploys the **Python backend only**.  
Runtime persistence uses the mounted `/app/data` volume.

The local dashboard in `frontend/` is optional and not deployed on Railway.

---

## Focused Test Commands

```powershell
.\.venv\Scripts\python.exe scripts\test_unified_news_sources_4b18j.py
.\.venv\Scripts\python.exe scripts\test_market_freshness_guard_4b18i.py
.\.venv\Scripts\python.exe scripts\test_feed_remove_4b18h.py
.\.venv\Scripts\python.exe scripts\test_feed_ticker_resolver_4b18g.py
.\.venv\Scripts\python.exe scripts\test_macro_emergency_persistence_4b18f.py
.\.venv\Scripts\python.exe scripts\test_live_confirmation_guard_4b18d.py
```

---

## Data Hygiene

Do not commit generated runtime data files.

```powershell
git restore --staged data
git restore data
Remove-Item data\qa_last_result.json,data\qa_runs.jsonl,data\intraday_candles.jsonl,data\screener_imports.jsonl,data\screener_stock_memory.jsonl,data\tradecard_memory.jsonl,data\actual_learning_candidates.jsonl,data\alert_event_log.jsonl,data\top_gainers_cache.json,data\top_gainers_cache.jsonl,feed_remove_fail.txt -ErrorAction SilentlyContinue
Remove-Item data\imports -Recurse -Force -ErrorAction SilentlyContinue
```

---

## Safety / Disclaimer

- Research and paper-trading intelligence only
- Not financial advice
- No live trade execution
- No paywall bypass
- No full copyrighted article storage
- Unverified feed items are not treated as confirmed catalysts

All outputs require manual validation before any real-world decision.

---

## Roadmap

Practical next improvements:

- stabilize NSE/PIB providers
- replace or disable persistent HTTP403 providers
- add GitHub Actions CI
- split large Telegram/radar/feed modules
- add `SECURITY.md` and `LICENSE`
- improve provider confidence scoring
- improve outcome learning
