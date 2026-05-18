"""
API Server v3 - Railway Ready with API Key Auth
=================================================
- Requires X-API-Key header for all /api/* endpoints
- Health check is open (for Railway monitoring)
- Production-ready CORS
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    from fastapi import FastAPI, HTTPException, Body, Header, Depends, Request
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("[ERROR] FastAPI not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / 'data'

try:
    from dotenv import load_dotenv
    env_path = BASE_DIR.parent / 'config' / 'keys.env'
    load_dotenv(env_path)
except ImportError:
    pass

sys.path.insert(0, str(BASE_DIR))

try:
    from ai_router import ask_ai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    print("[WARN] ai_router not available")

try:
    from postmortem import analyze_postmortem
    POSTMORTEM_AVAILABLE = True
except ImportError:
    POSTMORTEM_AVAILABLE = False

try:
    from history_exporter import build_custom_period
    CUSTOM_HISTORY_AVAILABLE = True
except ImportError:
    CUSTOM_HISTORY_AVAILABLE = False


# ============================================================
# AUTH CONFIG
# ============================================================
API_KEY = os.environ.get('API_KEY', '')

# If no API_KEY in env, generate a warning but allow access (dev mode)
if not API_KEY:
    print("[WARN] API_KEY not set. Running in OPEN mode (dev only)")
    print("[WARN] Set API_KEY env variable for production!")


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Dependency to verify API key in requests"""
    if not API_KEY:
        return True  # Dev mode - allow all
    
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Set X-API-Key header."
        )
    return True


# ============================================================
# APP SETUP
# ============================================================

app = FastAPI(title="Trading Copilot API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)


def load_json_file(filename: str) -> dict:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return {"error": f"File not found: {filename}", "data": None}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e), "data": None}


def file_age_seconds(filename: str) -> Optional[int]:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return None
    age = (datetime.now().timestamp() - filepath.stat().st_mtime)
    return int(age)


# ============================================================
# PUBLIC ENDPOINTS (no auth)
# ============================================================

@app.get("/")
def root():
    return {
        "service": "Trading Copilot API",
        "version": "3.0.0",
        "status": "running",
        "auth_required": bool(API_KEY)
    }


@app.get("/api/health")
def health():
    """Open endpoint for Railway healthcheck"""
    files = {
        "intelligence": "unified_intelligence.json",
        "scanner": "scanner_data.json",
        "govt": "govt_intelligence.json",
        "news": "news_feed.json",
        "reddit": "reddit_data.json",
        "markets": "global_markets.json",
        "india": "latest_market_data.json",
        "youtube": "youtube_feed.json",
        "inshorts": "inshorts_feed.json",
        "stats": "stats_data.json",
        "history": "history_data.json",
    }
    freshness = {}
    for key, filename in files.items():
        age = file_age_seconds(filename)
        if age is None:
            freshness[key] = "missing"
        elif age < 60:
            freshness[key] = f"{age}s ago"
        elif age < 3600:
            freshness[key] = f"{age // 60}m ago"
        else:
            freshness[key] = f"{age // 3600}h ago"
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "data_freshness": freshness,
        "ai_available": AI_AVAILABLE,
        "postmortem_available": POSTMORTEM_AVAILABLE,
        "auth_enabled": bool(API_KEY)
    }


# ============================================================
# AUTHENTICATED ENDPOINTS
# ============================================================

@app.get("/api/intelligence", dependencies=[Depends(verify_api_key)])
def get_intelligence(): return load_json_file("unified_intelligence.json")

@app.get("/api/scanner", dependencies=[Depends(verify_api_key)])
def get_scanner(): return load_json_file("scanner_data.json")

@app.get("/api/govt", dependencies=[Depends(verify_api_key)])
def get_govt(): return load_json_file("govt_intelligence.json")

@app.get("/api/news", dependencies=[Depends(verify_api_key)])
def get_news(): return load_json_file("news_feed.json")

@app.get("/api/reddit", dependencies=[Depends(verify_api_key)])
def get_reddit(): return load_json_file("reddit_data.json")

@app.get("/api/markets", dependencies=[Depends(verify_api_key)])
def get_markets(): return load_json_file("global_markets.json")

@app.get("/api/india", dependencies=[Depends(verify_api_key)])
def get_india(): return load_json_file("latest_market_data.json")

@app.get("/api/youtube", dependencies=[Depends(verify_api_key)])
def get_youtube(): return load_json_file("youtube_feed.json")

@app.get("/api/inshorts", dependencies=[Depends(verify_api_key)])
def get_inshorts(): return load_json_file("inshorts_feed.json")

@app.get("/api/stats", dependencies=[Depends(verify_api_key)])
def get_stats(): return load_json_file("stats_data.json")

@app.get("/api/history", dependencies=[Depends(verify_api_key)])
def get_history(): return load_json_file("history_data.json")


@app.get("/api/all", dependencies=[Depends(verify_api_key)])
def get_all():
    return {
        "intelligence": load_json_file("unified_intelligence.json"),
        "scanner": load_json_file("scanner_data.json"),
        "govt": load_json_file("govt_intelligence.json"),
        "news": load_json_file("news_feed.json"),
        "reddit": load_json_file("reddit_data.json"),
        "markets": load_json_file("global_markets.json"),
        "india": load_json_file("latest_market_data.json"),
        "youtube": load_json_file("youtube_feed.json"),
        "inshorts": load_json_file("inshorts_feed.json"),
        "stats": load_json_file("stats_data.json"),
        "history": load_json_file("history_data.json"),
        "fetched_at": datetime.now().isoformat()
    }


@app.post("/api/ask", dependencies=[Depends(verify_api_key)])
def ask_question(payload: dict = Body(...)):
    if not AI_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI router not available")
    question = payload.get("question", "").strip()
    use_case = payload.get("use_case", "ask_basic")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    intel = load_json_file("unified_intelligence.json")
    context = ""
    if intel.get("analysis"):
        context = "Latest intelligence:\n" + intel["analysis"][:2000]
    prompt = f"""You are an Indian stock market expert.

Context:
{context}

Question: {question}

Answer in 4-6 lines for Indian retail investor."""
    try:
        result = ask_ai(prompt, use_case=use_case, max_tokens=600)
        if result.get('success'):
            return {
                "success": True,
                "response": result.get('text', ''),
                "model": result.get('model', ''),
                "provider": result.get('provider', ''),
                "cost": result.get('estimated_cost', 0)
            }
        else:
            return {"success": False, "error": result.get('error', 'Unknown error')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/postmortem", dependencies=[Depends(verify_api_key)])
def postmortem(payload: dict = Body(...)):
    if not POSTMORTEM_AVAILABLE:
        raise HTTPException(status_code=503, detail="Post-mortem module not available")
    prediction_id = payload.get("prediction_id")
    if not prediction_id:
        raise HTTPException(status_code=400, detail="prediction_id is required")
    try:
        result = analyze_postmortem(int(prediction_id))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/history/custom", dependencies=[Depends(verify_api_key)])
def get_custom_history(payload: dict = Body(...)):
    if not CUSTOM_HISTORY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Custom history not available")
    start_date = payload.get('start_date')
    end_date = payload.get('end_date')
    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="start_date and end_date required")
    try:
        result = build_custom_period(start_date, end_date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/refresh", dependencies=[Depends(verify_api_key)])
def trigger_refresh():
    try:
        script_path = BASE_DIR / 'master_analyzer.py'
        if not script_path.exists():
            raise HTTPException(status_code=404, detail="master_analyzer.py not found")
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        env['AI_USE_CASE'] = 'manual_refresh'
        subprocess.Popen(
            [sys.executable, str(script_path)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return {"success": True, "message": "Refresh triggered in background"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    host = os.environ.get('HOST', '0.0.0.0')
    print("=" * 60)
    print("TRADING COPILOT API SERVER v3")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"AI: {'Available' if AI_AVAILABLE else 'NOT available'}")
    print(f"Post-Mortem: {'Available' if POSTMORTEM_AVAILABLE else 'NOT available'}")
    print(f"Custom History: {'Available' if CUSTOM_HISTORY_AVAILABLE else 'NOT available'}")
    print(f"Auth: {'X-API-Key required' if API_KEY else 'OPEN MODE (dev only)'}")
    print(f"Docs: http://localhost:{port}/docs")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port, log_level="info")