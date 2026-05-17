# Trading Copilot 🚀

AI-powered Indian stock market intelligence system with real-time scanner, multi-source analysis, and Telegram alerts.

## 🎯 Features

- **8-Tier Intelligence:** Government, News, Markets, Reddit, Scanner, YouTube, Inshorts, Global
- **AI Multi-Routing:** Claude Sonnet/Haiku + Gemini for cost optimization
- **NSE 500 Scanner:** Real-time volume spikes, breakouts, sector rotation
- **Learning Engine:** SQLite-based prediction tracking with WIN/LOSS evaluation
- **Telegram Bot:** 24/7 alerts and remote commands (`/scan`, `/brief`, `/ask`)
- **Electron Dashboard:** 9-tab desktop GUI

## 🏗️ Architecture

LAPTOP (Electron GUI)
↓ reads
DATA FILES (JSON / SQLite)
↑ written by
BACKEND (Python modules)
↓ alerts
TELEGRAM (24/7)

## 📦 Modules

- `master_scheduler.py` — Orchestrates everything (5 strategic + 11 intraday runs/day)
- `master_analyzer.py` — Sonnet/Gemini-powered unified intelligence
- `stock_scanner.py` — NSE 500 real-time signal detection
- `govt_tracker.py` — PIB/SEBI/RBI/BSE with auto Hindi→English translation
- `reddit_tracker.py` — Retail sentiment from Indian stock subreddits
- `news_aggregator.py` — Multi-source news aggregation
- `outcome_tracker.py` — Evaluates predictions vs actual market moves
- `context_snapshot.py` — Captures forensic data for AI post-mortems
- `telegram_bot.py` + `telegram_listener.py` — Two-way Telegram interface

## 🚀 Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install Node dependencies
npm install

# 3. Configure API keys
# Create config/keys.env with:

ANTHROPIC_API_KEY=...
NEWS_API_KEY=...
ALPHA_VANTAGE_KEY=...
YOUTUBE_API_KEY=...
TWELVE_DATA_KEY=...
FINNHUB_KEY=...
MARKETAUX_KEY=...
POLYGON_KEY=...
GOOGLE_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# 4. Run scheduler (24/7 background)
python backend/master_scheduler.py

# 5. Run GUI (when needed)
npm run electron

📊 Daily Schedule
05:00 — Overnight brief (Sonnet)
08:00 — Outcome evaluation + Telegram report
08:45 — Pre-market brief (Sonnet)
09:30-15:00 — 11x intraday scans (every 30 min)
12:00 — Midday check (Gemini free)
15:35 — Post-close analysis (Haiku)
23:00 — US market check (Gemini free)

💰 Cost
AI: ~$10-12/month
	•	Railway hosting: ~$3-5/month (when deployed)

🔒 Security
API keys stored in config/keys.env (gitignored). Never commit secrets.
⚖️ Disclaimer
This is a personal research tool. Not financial advice. Past predictions don't guarantee future results.
---