# Trading Copilot 🚀

AI-powered Indian stock market intelligence system with real-time scanner, multi-source analysis, memory-augmented self-calibration, and 24/7 cloud-based Telegram alerts.

---

## 🎯 Features

- **8-Tier Intelligence**: Government, News, Markets, Reddit, Scanner, YouTube, Inshorts, Global
- **Memory-Augmented AI**: Self-calibrating analyzer that learns from past prediction accuracy via RAG
- **AI Multi-Routing**: Claude Sonnet/Haiku + Gemini for cost optimization
- **NSE 500 Scanner**: Real-time volume spikes, breakouts, sector rotation, correlation breaks
- **Learning Engine**: SQLite-based prediction tracking with WIN/LOSS evaluation by sector & confidence tier
- **Telegram Bot (24/7)**: Auto-pushed 6-message brain analysis after every strategic run + 18+ on-demand commands
- **Electron Dashboard**: 9-tab desktop GUI with persistent chat history and post-mortem analysis
- **Cloud Deployed**: Runs 24/7 on Railway.app (combined FastAPI + scheduler + listener architecture)
- **Post-Mortem AI**: On-demand AI explanation of why specific trades won or lost using forensic context snapshots

---

## 🏗️ Architecture

┌─────────────────────────────────────────────────────────────┐
│ RAILWAY.APP (24/7 Cloud) │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ backend/api/api_server.py (FastAPI - main process) │ │
│ │ ├── HTTP endpoints (X-API-Key auth) │ │
│ │ ├── Background thread → master_scheduler.py │ │
│ │ └── Background thread → telegram_listener.py │ │
│ └─────────────────────────────────────────────────────┘ │
│ │ │
│ ▼ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Persistent Volume (/app/data) │ │
│ │ ├── trading_history.db (SQLite) │ │
│ │ ├── unified_intelligence.json │ │
│ │ ├── history_data.json │ │
│ │ └── 11 source JSON files │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
│ │
▼ ▼
┌──────────────────┐ ┌──────────────────┐
│ TELEGRAM (24/7) │ │ ELECTRON GUI │
│ - Brain push │ │ - 9 tabs │
│ - ULTRA alerts │ │ - Reads API │
│ - 18+ commands │ │ - Local laptop │
└──────────────────┘ └──────────────────┘

## 📦 Backend Modules

### Orchestration
- `backend/api/api_server.py` — FastAPI server + scheduler/listener thread spawner (Railway entry point)
- `master_scheduler.py` v7.2 — Orchestrates 5 strategic + 11 intraday runs/day with auto brain push
- `telegram_listener.py` v3 — Polls Telegram for 18+ commands (brain, scan, ask, etc.)
- `telegram_brain_pusher.py` — Reads brain JSON and sends 6-message analysis to phone

### Intelligence
- `master_analyzer.py` v7 — Memory-augmented AI analyzer with self-calibration section
- `learning_engine.py` — Calculates win rates by sector/confidence/time-of-day for RAG injection
- `ai_router.py` v2 — Routes to Claude Sonnet/Haiku or Gemini based on use case (cloud-ready)
- `context_snapshot.py` — Captures forensic market state at prediction time
- `postmortem.py` — AI-powered failure analysis using context snapshots

### Data Collection
- `collector.py` — India market data (Nifty, Sensex, Bank Nifty, sectors, India VIX)
- `global_collector.py` — US/Asia/Europe indices, commodities, currencies
- `stock_scanner.py` — NSE 500 real-time signal detection (ULTRA/STRONG/MEDIUM)
- `news_aggregator.py` — Multi-source news (NewsAPI, MarketAux, Polygon, etc.)
- `inshorts_tracker.py` — Indian retail news source
- `youtube_tracker.py` — Financial YouTube channel sentiment
- `govt_tracker.py` v8 — PIB/SEBI/RBI/BSE with dual-engine Hindi→English translation
- `reddit_tracker.py` — Retail sentiment from Indian stock subreddits

### Persistence & Logging
- `prediction_logger.py` v2 — Parses AI markdown to SQL with yfinance fallback + dedup
- `outcome_tracker.py` — Evaluates predictions vs actual market moves at 8 AM daily
- `stats_exporter.py` — Calculates win rate, profit factor, sector accuracy
- `history_exporter.py` v2.2 — Exports SQLite to JSON with workweek-aware date ranges
- `alert_engine.py` — Telegram alerts for ULTRA signals, morning briefs, outcome reports

---

## 🚀 Setup

### Local Development

# 1. Clone repository
git clone https://github.com/yourusername/trading-copilot.git
cd trading-copilot

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install GUI dependencies (local Electron only — not used on Railway)
cd frontend
npm install
cd ..

# 4. Configure API keys in config/keys.env:
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
NEWS_API_KEY=...
ALPHA_VANTAGE_KEY=...
YOUTUBE_API_KEY=...
TWELVE_DATA_KEY=...
FINNHUB_KEY=...
MARKETAUX_KEY=...
POLYGON_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
API_KEY=your-custom-railway-auth-key   # for FastAPI X-API-Key

# 5a. Run scheduler locally (24/7 background)
python backend/master_scheduler.py

# 5b. Run GUI when needed
cd frontend && npm start

Cloud Deployment (Railway.app)

# 1. Push to GitHub (private repo recommended)
git add .
git commit -m "Initial deploy"
git push origin main

# 2. On railway.app:
#    - New Project → Deploy from GitHub
#    - Select repo
#    - Add persistent volume mounted at /app/data
#    - Set all environment variables from keys.env
#    - Start command (Procfile): uvicorn backend.api.api_server:app --host 0.0.0.0 --port $PORT

# 3. Set billing limit to $15/month for safety

# 4. Verify deployment:
curl -H "X-API-Key: your-key" https://your-app.railway.app/api/all


📊 Daily Schedule
Strategic Runs (Full pipeline + Brain push to Telegram)
￼
Intraday Scanner (Mon-Fri, every 30 min)
09:30, 10:00, 10:30, 11:00, 11:30, 12:30, 13:00, 13:30, 14:00, 14:30, 15:00
Lightweight scan + ULTRA signal alerts
	•	No brain push (avoids spam) — use /brain on Telegram for on-demand

📱 Telegram Commands
🧠 Brain Analysis
￼
📊 Pipelines
￼
📈 Info
￼
🔧 Control
￼

🧠 Memory-Augmented AI (Self-Calibration)
Unlike static LLMs, Trading Copilot's analyzer learns from its own track record via RAG:
After each prediction is evaluated (8 AM daily), learning_engine.py calculates:
Win rate by sector (e.g., "Pharma: 72% accurate")
Win rate by confidence tier (e.g., "HIGH conf: 65% vs MEDIUM: 48%")
Failure patterns (e.g., "IT picks fail when US sells off")
Before each new analysis, this performance summary is injected into the AI prompt as a "SELF-CALIBRATION" section.
The AI then adjusts confidence levels based on its own historical accuracy — e.g., downgrading IT picks during US selloffs.
	4	The /calibration Telegram command shows the current memory state.

Note: Self-calibration becomes meaningful after 10-20 evaluated predictions (1 week of trading days).


🔬 Post-Mortem Analysis
Click the "🔬 Generate AI Post-Mortem" button on any evaluated prediction in the GUI to:
Send the original prediction + actual outcome + context snapshot to Sonnet
Get a forensic explanation of why the trade won or lost
	3	Identify which signals were misleading vs accurate
Also available via Telegram: /postmortem RELIANCE (if implemented in your build)

💾 Database Schema (SQLite)
data/trading_history.db contains:
predictions — Every AI recommendation with entry/target/stop
signals — Scanner ULTRA/STRONG/MEDIUM signals
outcomes — WIN/LOSS evaluation with actual price movements
context_snapshots — Forensic market state at prediction time
	•	accuracy_metrics — Aggregated win rates by sector/confidence/time

💰 Cost Breakdown
￼

Set a Railway billing limit of $15/month for safety.


🔒 Security
All API keys stored in config/keys.env (gitignored)
Railway environment variables override local .env (using load_dotenv(override=False))
FastAPI endpoints protected via X-API-Key header authentication
Telegram listener restricts commands to single whitelisted Chat ID
	•	Private GitHub repo recommended
.gitignore excludes:

config/keys.env
data/*.db
data/*.json
data/_telegram_*
node_modules/
__pycache__/
*.pyc


📁 File Structure

trading-copilot/
├── backend/
│   ├── api/api_server.py          # FastAPI + thread spawner (Railway entry)
│   ├── master_scheduler.py        # v7.2 - Orchestrator with brain push
│   ├── master_analyzer.py         # v7 - Memory-augmented AI
│   ├── learning_engine.py         # RAG calibration logic
│   ├── ai_router.py               # v2 - Multi-model routing
│   ├── prediction_logger.py       # v2 - SQL with yfinance fallback
│   ├── outcome_tracker.py         # WIN/LOSS evaluator
│   ├── context_snapshot.py        # Forensic snapshots
│   ├── postmortem.py              # AI failure analysis
│   ├── telegram_listener.py       # v3 - 18+ commands
│   ├── telegram_brain_pusher.py   # 6-message brain formatter
│   ├── alert_engine.py            # Telegram alerts
│   ├── stock_scanner.py           # NSE 500 scanner
│   ├── collector.py               # India markets
│   ├── global_collector.py        # Global markets
│   ├── news_aggregator.py         # Multi-source news
│   ├── inshorts_tracker.py        # Inshorts feed
│   ├── youtube_tracker.py         # YouTube sentiment
│   ├── govt_tracker.py            # v8 - PIB/SEBI/RBI/BSE
│   ├── reddit_tracker.py          # Reddit sentiment
│   ├── stats_exporter.py          # Accuracy metrics
│   └── history_exporter.py        # v2.2 - GUI history JSON
├── config/
│   └── keys.env                   # API keys (gitignored)
├── data/                          # All JSON + SQLite (gitignored)
├── frontend/                      # Electron desktop GUI (local only)
│   ├── main.js
│   ├── index.html
│   ├── package.json
│   └── components/
├── requirements.txt
├── nixpacks.toml                  # Python-only Railway build (no npm)
├── Procfile                       # Railway start command
├── railway.json                   # Railway deploy config
├── .railwayignore                 # Exclude frontend from deploy upload
├── .gitignore
└── README.md


🛠️ Manual Console Commands (Scheduler)
When master_scheduler.py runs locally with TTY, you can type:
￼

📈 Performance Tracking
After ~3 months of evaluated predictions, expect:
Sector accuracy heatmap — which sectors the AI predicts best
Confidence calibration — does HIGH actually outperform MEDIUM?
Time-of-day patterns — are pre-market predictions better than midday?
	•	Signal combo analysis — which scanner+news combinations are most predictive

True ML layer (XGBoost/RandomForest) recommended only after 500-1000 evaluated predictions (~3 months).


⚖️ Disclaimer
This is a personal research tool. Not financial advice. Past predictions don't guarantee future results. Always do your own research and consult a SEBI-registered financial advisor before making investment decisions.
The author is not liable for any trading losses incurred from following AI predictions generated by this system.

📝 Version History
v7.2 (Current) — Telegram brain pusher (6-message auto-push) + 8 new on-demand brain commands
v7.1 — History exporter integrated into all strategic runs
v7.0 — Memory-Augmented AI with SELF-CALIBRATION via learning_engine
v6.0 — Railway cloud deployment with combined API/Scheduler architecture
v5.0 — Post-mortem analysis + context snapshots
v4.0 — SQLite persistence + outcome evaluation
v3.0 — Multi-AI routing (Claude + Gemini)
v2.0 — NSE 500 scanner + sector rotation
	•	v1.0 — Initial 8-tier intelligence engine

🤝 Contributing
This is a personal project, but suggestions welcome via GitHub issues.

📧 Contact
For questions about the architecture or implementation, open a GitHub issue.

## 📋 Key Updates from Your Original

| Section | What Changed |
|---------|--------------|
| **Features** | Added Memory-Augmented AI, Cloud deployment, Post-Mortem, 6-msg brain push |
| **Architecture** | Replaced text diagram with Railway-aware diagram showing combined service |
| **Modules** | Reorganized into 4 logical groups, added new files (`api_server`, `learning_engine`, `telegram_brain_pusher`, etc.) |
| **Setup** | Added Railway deployment section + X-API-Key auth |
| **Daily Schedule** | Added "Brain Push" column to make it visual |
| **Telegram Commands** | New section listing all 18+ commands |
| **Memory-Augmented AI** | New section explaining self-calibration |
| **Post-Mortem** | New section explaining failure analysis |
| **Database Schema** | New section listing SQLite tables |
| **Cost Breakdown** | Itemized table instead of single line |
| **Security** | Added Railway-specific notes + .gitignore example |
| **File Structure** | Full tree of backend modules |
| **Manual Console Commands** | Table of scheduler hotkeys including new `B` for brain push |
| **Version History** | Added v7.2 entry + earlier milestones |

---

## 🚀 Deploy

```powershell
cd C:\Users\sujan\trading-copilot
# Replace README.md with above content
git add README.md
git commit -m "Update README to reflect v7.2 + Railway + Memory-Augmented AI"
git push origin main
