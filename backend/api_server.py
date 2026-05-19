"""
API Server v5 - API + Scheduler + Telegram Listener
Three things in one container:
1. FastAPI HTTP server
2. master_scheduler (background)  
3. telegram_listener (background)
"""

import os
import sys
import json
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    from fastapi import FastAPI, HTTPException, Body, Header, Depends
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("[ERROR] FastAPI not installed.")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / 'data'

try:
    from dotenv import load_dotenv
    env_path = BASE_DIR.parent / 'config' / 'keys.env'
    if env_path.exists():
        load_dotenv(env_path, override=False)
except ImportError:
    pass

sys.path.insert(0, str(BASE_DIR))

try:
    from ai_router import ask_ai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

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


API_KEY = os.environ.get('API_KEY', '')

if not API_KEY:
    print("[WARN] API_KEY not set. Running in OPEN mode (dev only)")


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not API_KEY:
        return True
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return True


# ============================================================
# BACKGROUND PROCESSES
# ============================================================

def run_subprocess_loop(script_name, label):
    """Run a Python script as subprocess, auto-restart if crashes"""
    print("=" * 60)
    print(f"[BACKGROUND] Starting {label}...")
    print("=" * 60)
    
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        print(f"[ERROR] {script_name} not found at {script_path}")
        return
    
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    
    while True:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Launching {label}...")
            
            process = subprocess.Popen(
                [sys.executable, str(script_path)],
                env=env,
                stdout=sys.stdout,
                stderr=sys.stderr,
                bufsize=1,
                cwd=str(BASE_DIR.parent)
            )
            
            process.wait()
            
            print(f"[WARN] {label} exited with code {process.returncode}, restarting in 30s...")
            time.sleep(30)
        
        except Exception as e:
            print(f"[ERROR] {label} crashed: {e}")
            print(f"[INFO] Restarting in 60s...")
            time.sleep(60)


def start_background_processes():
    """Launch scheduler and telegram listener in daemon threads"""
    
    # Scheduler thread
    if os.environ.get('DISABLE_SCHEDULER') != '1':
        scheduler_thread = threading.Thread(
            target=run_subprocess_loop, 
            args=('master_scheduler.py', 'Scheduler'),
            daemon=True, 
            name='Scheduler'
        )
        scheduler_thread.start()
        print(f"[INFO] Scheduler thread started")
    
    # Telegram listener thread
    if os.environ.get('DISABLE_TELEGRAM_LISTENER') != '1':
        telegram_thread = threading.Thread(
            target=run_subprocess_loop, 
            args=('telegram_listener.py', 'TelegramListener'),
            daemon=True, 
            name='TelegramListener'
        )
        telegram_thread.start()
        print(f"[INFO] Telegram listener thread started")


# ============================================================
# APP SETUP
# ============================================================

app = FastAPI(title="Trading Copilot API + Scheduler + Telegram", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)


@app.on_event("startup")
def startup_event():
    start_background_processes()


import math

def sanitize_json_value(obj):
    """Replace NaN/Infinity with None (JSON compliant)"""
    if isinstance(obj, dict):
        return {k: sanitize_json_value(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json_value(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def load_json_file(filename: str) -> dict:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return {"error": f"File not found: {filename}","data": None}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Sanitize NaN/Infinity that yfinance sometimes produces
            return sanitize_json_value(data)
    except Exception as e:
        return {"error": str(e), "data": None}


def file_age_seconds(filename: str) -> Optional[int]:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return None
    age = (datetime.now().timestamp() - filepath.stat().st_mtime)
    return int(age)


@app.get("/")
def root():
    return {
        "service": "Trading Copilot API + Scheduler + Telegram",
        "version": "5.0.0",
        "status": "running",
        "auth_required": bool(API_KEY)
    }


@app.get("/api/health")
def health():
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
        "auth_enabled": bool(API_KEY),
        "background_processes": ["scheduler", "telegram_listener"]
    }


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
            stderr=subprocess.DEVNULL,
            cwd=str(BASE_DIR.parent)
        )
        return {"success": True, "message": "Refresh triggered in background"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    host = os.environ.get('HOST', '0.0.0.0')
    print("=" * 60)
    print("TRADING COPILOT API SERVER + SCHEDULER + TELEGRAM v5")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"AI: {'Available' if AI_AVAILABLE else 'NOT available'}")
    print(f"Auth: {'X-API-Key required' if API_KEY else 'OPEN MODE'}")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port, log_level="info")