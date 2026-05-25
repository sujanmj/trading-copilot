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

import requests

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    from fastapi import FastAPI, HTTPException, Body, Header, Depends, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    import uvicorn
except ImportError:
    print("[ERROR] FastAPI not installed.")
    sys.exit(1)

from backend.utils.bootstrap import setup_project_path

setup_project_path()

from backend.utils.config import (
    IS_RAILWAY,
    PROJECT_ROOT,
    DATA_DIR,
    LOGS_DIR,
    API_HOST,
    API_PORT,
    DB_PATH,
    STALE_THRESHOLD_SECONDS,
    WATCHDOG_CHECK_INTERVAL,
    WATCHDOG_TRIGGER_COOLDOWN,
    get_env,
)
from backend.utils.local_logging import setup_logger
from backend.utils.process_lock import lock_status
from backend.utils.runner import popen_script, run_script_capture

backend_log = setup_logger('backend', 'backend.log')
watchdog_log = setup_logger('watchdog', 'watchdog.log')

TELEGRAM_BOT_TOKEN = get_env('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = get_env('TELEGRAM_CHAT_ID')

_watchdog_last_trigger = 0.0
_analyzer_running = False
_subprocess_restart_log_at: dict = {}

SCHEDULER_SCRIPT = 'master_scheduler.py'
SCHEDULER_SINGLETON_POLL_SECONDS = 120
SCHEDULER_CRASH_RESTART_SECONDS = 30
SUBPROCESS_WARN_COOLDOWN_SECONDS = 300

try:
    from backend.ai.ai_router import ask_ai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

try:
    from backend.analyzers.postmortem import analyze_postmortem
    POSTMORTEM_AVAILABLE = True
except ImportError:
    POSTMORTEM_AVAILABLE = False

try:
    from backend.storage.history_exporter import build_custom_period
    CUSTOM_HISTORY_AVAILABLE = True
except ImportError:
    CUSTOM_HISTORY_AVAILABLE = False


API_KEY = get_env('API_KEY')

if not API_KEY:
    print("[WARN] API_KEY not set. Running in OPEN mode (dev only)")
if IS_RAILWAY:
    print("[INFO] Railway deployment detected")


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not API_KEY:
        return True
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return True


# ============================================================
# BACKGROUND PROCESSES
# ============================================================

def _scheduler_singleton_active() -> bool:
    info = lock_status().get('master_scheduler') or {}
    return bool(info.get('alive'))


def _log_subprocess_event(label: str, message: str, *, force: bool = False):
    """Throttle repetitive subprocess restart warnings."""
    now = time.time()
    last = _subprocess_restart_log_at.get(label, 0.0)
    if force or (now - last) >= SUBPROCESS_WARN_COOLDOWN_SECONDS:
        print(message)
        _subprocess_restart_log_at[label] = now


def _wait_scheduler_singleton_health():
    """Poll singleton scheduler health instead of spawning duplicates."""
    polls = max(1, SCHEDULER_SINGLETON_POLL_SECONDS // 30)
    for _ in range(polls):
        time.sleep(30)
        if not _scheduler_singleton_active():
            print("[SCHEDULER CRASH DETECTED] Singleton lock lost — recovery launch")
            return
    print("[SCHEDULER HEALTHY] Singleton scheduler still active")
    _log_subprocess_event('Scheduler', "[WATCHDOG NO-RESTART] Scheduler singleton healthy")


def run_subprocess_loop(script_name, label):
    """Run a Python module as subprocess; restart only on real crashes."""
    print("=" * 60)
    print(f"[BACKGROUND] Starting {label}...")
    print("=" * 60)

    while True:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Launching {label}...")
            process = popen_script(
                script_name,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            process.wait()
            rc = process.returncode if process.returncode is not None else -1

            if script_name == SCHEDULER_SCRIPT:
                if rc == 0 and _scheduler_singleton_active():
                    print("[SCHEDULER SINGLETON ACTIVE] Primary scheduler already running")
                    _log_subprocess_event(
                        'Scheduler',
                        "[WATCHDOG NO-RESTART] Singleton guard — skip duplicate launch",
                        force=True,
                    )
                    _wait_scheduler_singleton_health()
                    continue

                if rc == 0:
                    print("[SCHEDULER CRASH DETECTED] Scheduler exited cleanly but lock is free")
                    _log_subprocess_event(
                        'Scheduler',
                        f"[SCHEDULER RECOVERY TRIGGERED] Unexpected clean exit — restart in "
                        f"{SCHEDULER_CRASH_RESTART_SECONDS}s",
                        force=True,
                    )
                    time.sleep(SCHEDULER_CRASH_RESTART_SECONDS)
                    continue

                _log_subprocess_event(
                    'Scheduler',
                    f"[SCHEDULER CRASH DETECTED] exit code {rc} — recovery in "
                    f"{SCHEDULER_CRASH_RESTART_SECONDS}s",
                    force=True,
                )
                print(f"[SCHEDULER RECOVERY TRIGGERED] Restarting scheduler in "
                      f"{SCHEDULER_CRASH_RESTART_SECONDS}s...")
                time.sleep(SCHEDULER_CRASH_RESTART_SECONDS)
                continue

            if rc == 0:
                _log_subprocess_event(label, f"[INFO] {label} exited cleanly — restart in 30s")
            else:
                _log_subprocess_event(
                    label,
                    f"[WARN] {label} exited with code {rc}, restarting in 30s...",
                    force=True,
                )
            time.sleep(30)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
            return
        except Exception as e:
            if script_name == SCHEDULER_SCRIPT:
                print(f"[SCHEDULER CRASH DETECTED] {label} launcher error: {e}")
                _log_subprocess_event(
                    'Scheduler',
                    f"[SCHEDULER RECOVERY TRIGGERED] Launcher error — restart in 60s",
                    force=True,
                )
            else:
                print(f"[ERROR] {label} crashed: {e}")
                print(f"[INFO] Restarting in 60s...")
            time.sleep(60)


def send_watchdog_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': f"🤖 WATCHDOG: {message}",
            'parse_mode': 'HTML',
        }, timeout=10)
    except Exception as e:
        print(f"[WATCHDOG] Telegram alert failed: {e}")


def _check_watchdog_emergency() -> tuple:
    """Emergency override — macro/govt/scanner/contradiction spikes only."""
    try:
        state = {}
        if (DATA_DIR / 'analysis_state.json').exists():
            with open(DATA_DIR / 'analysis_state.json', 'r', encoding='utf-8') as f:
                state = json.load(f) or {}

        disagree = float(state.get('disagreement_score') or 0)
        vol = float(state.get('volatility_index') or 0)
        if disagree >= 0.55:
            return True, f'contradiction_spike={disagree:.2f}'
        if vol >= 0.68:
            return True, f'volatility_spike={vol:.2f}'

        govt_path = DATA_DIR / 'govt_intelligence.json'
        if govt_path.exists():
            with open(govt_path, 'r', encoding='utf-8') as f:
                govt = json.load(f) or {}
            for item in (govt.get('high_impact_items') or [])[:5]:
                if float(item.get('impact_score') or 0) >= 8.5:
                    return True, 'govt_high_impact'

        scanner_path = DATA_DIR / 'scanner_data.json'
        if scanner_path.exists():
            with open(scanner_path, 'r', encoding='utf-8') as f:
                scanner = json.load(f) or {}
            for sig in (scanner.get('top_signals') or [])[:6]:
                if str(sig.get('strength', '')).upper() == 'ULTRA' and abs(float(sig.get('change_percent') or 0)) >= 5:
                    return True, f"scanner_ultra:{sig.get('ticker')}"
    except Exception as e:
        watchdog_log.debug('Emergency check failed: %s', e)
    return False, ''


def stale_data_watchdog():
    """Background loop: auto-run master_analyzer if intelligence file is stale."""
    global _watchdog_last_trigger, _analyzer_running

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)
        try:
            from backend.utils.market_hours import get_watchdog_config
            wd_cfg = get_watchdog_config()
            threshold = int(wd_cfg['stale_threshold_seconds'])
            mode = wd_cfg['mode']
            print(f"[WATCHDOG MODE] {mode} threshold={threshold}s")
            if wd_cfg.get('night_mode'):
                print(f"[NIGHT MODE STALE TOLERANCE] active — threshold {threshold // 3600}h")

            age = file_age_seconds('unified_intelligence.json')
            if not age:
                continue
            if age <= threshold:
                if wd_cfg.get('market_hours'):
                    print(f"[MARKET HOURS STALE CHECK] age={age}s ok (<{threshold}s)")
                continue

            emergency, emergency_reason = _check_watchdog_emergency()
            if wd_cfg.get('night_mode') and not emergency:
                print(f"[NIGHT MODE STALE TOLERANCE] stale {age}s — no emergency, skip refresh")
                continue

            now = time.time()
            if now - _watchdog_last_trigger < WATCHDOG_TRIGGER_COOLDOWN:
                continue
            if _analyzer_running:
                watchdog_log.info("Analyzer subprocess already active — skip")
                continue
            locks = lock_status()
            if locks.get('master_analyzer', {}).get('alive'):
                watchdog_log.info("Analyzer lock held — skip auto-refresh")
                continue

            _watchdog_last_trigger = now
            hours = age // 3600
            msg = f"Intelligence {hours}h stale ({mode})! Auto-recovering..."
            if emergency:
                msg += f" [EMERGENCY: {emergency_reason}]"
            print(f"[WATCHDOG] {msg}")
            watchdog_log.warning(msg)

            send_telegram = wd_cfg.get('market_hours') or emergency
            if send_telegram:
                send_watchdog_alert(
                    f"Market intelligence is <b>{hours}h stale</b> ({mode}). Auto-refresh triggered."
                    + (f" Emergency: {emergency_reason}" if emergency else '')
                )
            else:
                print("[WATCHDOG] After-hours stale refresh — Telegram alert suppressed")

            env = {'AI_USE_CASE': 'watchdog_refresh'}
            _analyzer_running = True

            def _run_analyzer():
                global _analyzer_running
                try:
                    popen_script('master_analyzer.py', extra_env=env).wait()
                finally:
                    _analyzer_running = False

            threading.Thread(target=_run_analyzer, daemon=True, name='WatchdogAnalyzer').start()
            watchdog_log.info("Auto-refresh triggered")
            print("[WATCHDOG] Auto-refresh triggered")
        except Exception as e:
            print(f"[WATCHDOG] Error: {e}")
            watchdog_log.error("Watchdog error: %s", e)


def start_background_processes():
    """Launch scheduler and telegram listener in daemon threads"""
    backend_log.info("Starting background processes (railway=%s)", IS_RAILWAY)

    # Scheduler thread
    if os.environ.get('DISABLE_SCHEDULER') != '1':
        scheduler_thread = threading.Thread(
            target=run_subprocess_loop,
            args=('master_scheduler.py', 'Scheduler'),
            daemon=True,
            name='Scheduler',
        )
        scheduler_thread.start()
        print("[INFO] Scheduler thread started")
        backend_log.info("Scheduler thread started")
    
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

    watchdog_thread = threading.Thread(
        target=stale_data_watchdog,
        daemon=True,
        name='Watchdog',
    )
    watchdog_thread.start()
    print("[INFO] Watchdog thread started")


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
    backend_log.info("API server startup — host=%s port=%s railway=%s", API_HOST, API_PORT, IS_RAILWAY)
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


def _safe_debug_response(endpoint: str, builder, cycle_id: Optional[str] = None):
    """Never raise from debug endpoints — return degraded payload on failure."""
    try:
        if cycle_id is not None:
            payload = builder(cycle_id)
        else:
            payload = builder()
        if not isinstance(payload, dict):
            payload = {'status': 'ok', 'data': payload}
        elif 'status' not in payload:
            payload['status'] = 'ok'
        return sanitize_json_value(payload)
    except Exception as e:
        backend_log.warning("Debug endpoint %s degraded: %s", endpoint, e)
        fallback = {
            'status': 'degraded',
            'reason': str(e),
            'endpoint': endpoint,
        }
        if 'delta' in endpoint:
            fallback['deltas'] = []
        return sanitize_json_value(fallback)


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
        "railway": IS_RAILWAY,
        "auth_required": bool(API_KEY),
    }


@app.get("/api/config")
def api_config():
    """Public deployment info for GUI bootstrap."""
    return {
        "railway": IS_RAILWAY,
        "auth_required": bool(API_KEY),
        "data_dir": str(DATA_DIR),
        "db_path": str(DB_PATH),
    }


@app.get("/api/health")
def health():
    from backend.utils.market_hours import get_watchdog_config
    wd_cfg = get_watchdog_config()
    dynamic_stale_threshold = int(wd_cfg.get('stale_threshold_seconds') or STALE_THRESHOLD_SECONDS)

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
    source_status = {}
    for key, filename in files.items():
        age = file_age_seconds(filename)
        filepath = DATA_DIR / filename
        if age is None:
            freshness[key] = "missing"
            source_status[key] = {"file": filename, "status": "missing", "age_seconds": None}
        elif age < 60:
            freshness[key] = f"{age}s ago"
            source_status[key] = {"file": filename, "status": "ok", "age_seconds": age}
        elif age < 3600:
            freshness[key] = f"{age // 60}m ago"
            source_status[key] = {"file": filename, "status": "ok", "age_seconds": age}
        else:
            freshness[key] = f"{age // 3600}h ago"
            stale = age > dynamic_stale_threshold
            source_status[key] = {
                "file": filename,
                "status": "stale" if stale else "ok",
                "age_seconds": age,
                "exists": filepath.exists(),
            }

    try:
        from backend.ai.ai_router import check_keys_status
        keys = check_keys_status()
    except Exception:
        keys = {}

    try:
        from backend.ai.ai_budget_manager import budget_status as ai_budget_status
        ai_budget = ai_budget_status()
    except Exception:
        ai_budget = {}

    try:
        from backend.ai.pipeline_observability import get_observability_summary
        pipeline_obs = get_observability_summary()
    except Exception:
        pipeline_obs = {}

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "railway": IS_RAILWAY,
        "db_path": str(DB_PATH),
        "data_freshness": freshness,
        "source_status": source_status,
        "running_jobs": lock_status(),
        "ai_status": {
            "router_available": AI_AVAILABLE,
            "anthropic_configured": keys.get('anthropic', False),
            "google_configured": keys.get('google', False),
        },
        "ai_budget": ai_budget,
        "ai_available": AI_AVAILABLE,
        "postmortem_available": POSTMORTEM_AVAILABLE,
        "auth_enabled": bool(API_KEY),
        "background_processes": ["scheduler", "telegram_listener", "watchdog"],
        "logs_dir": str(LOGS_DIR),
        "market_regime": pipeline_obs.get("market_regime"),
        "compression_mode": pipeline_obs.get("compression_mode"),
        "ai_budget_remaining": pipeline_obs.get("ai_budget_remaining"),
        "last_quality_score": pipeline_obs.get("last_quality_score"),
        "last_claude_reason": pipeline_obs.get("last_claude_reason"),
        "delta_trigger_reason": pipeline_obs.get("delta_trigger_reason"),
        "watchdog_mode": pipeline_obs.get("watchdog_mode"),
        "watchdog_stale_threshold_seconds": pipeline_obs.get("watchdog_stale_threshold_seconds"),
        "pipeline_observability": pipeline_obs,
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
        popen_script(
            'master_analyzer.py',
            extra_env={'AI_USE_CASE': 'manual_refresh'},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"success": True, "message": "Refresh triggered in background"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _run_backend_script(script_name: str, timeout: int, extra_env: Optional[dict] = None):
    """Run a backend script synchronously and return captured output."""
    result = run_script_capture(script_name, timeout=timeout, extra_env=extra_env)
    if result.get('error', '').startswith('Unknown script'):
        raise HTTPException(status_code=404, detail=f"{script_name} not found")
    return result


@app.post("/api/debug/force-collect", dependencies=[Depends(verify_api_key)])
def force_collect():
    """Run collector.py synchronously (debug)."""
    return _run_backend_script('collector.py', timeout=120)


@app.post("/api/debug/force-analyze", dependencies=[Depends(verify_api_key)])
def force_analyze():
    """Run master_analyzer.py synchronously (debug)."""
    env_backup = os.environ.get('AI_USE_CASE')
    os.environ['AI_USE_CASE'] = 'manual_refresh'
    try:
        return _run_backend_script('master_analyzer.py', timeout=180, extra_env={'AI_USE_CASE': 'manual_refresh'})
    finally:
        if env_backup is None:
            os.environ.pop('AI_USE_CASE', None)
        else:
            os.environ['AI_USE_CASE'] = env_backup


@app.get("/api/debug/find-db", dependencies=[Depends(verify_api_key)])
def find_db_files():
    """Find .db files under project (local) or filesystem (cloud)."""
    try:
        from backend.storage.db_finder import find_all_db_files
        start = '/' if IS_RAILWAY else str(PROJECT_ROOT)
        databases = find_all_db_files(start)
        return {"databases": databases, "count": len(databases), "railway": IS_RAILWAY}
    except Exception as e:
        return {"error": str(e), "databases": []}


@app.post("/api/debug/dedup-smart", dependencies=[Depends(verify_api_key)])
def dedup_smart():
    """Find DB with predictions and deduplicate rows."""
    try:
        from backend.storage.db_finder import find_predictions_db, run_predictions_dedup

        db_path, count = find_predictions_db()
        if not db_path:
            return {"error": "No database with predictions table found"}
        if count == 0:
            return {"error": "Predictions table exists but is empty", "db_path": db_path, "before": 0, "after": 0, "removed": 0}

        before, after, removed = run_predictions_dedup(db_path)
        return {"db_path": db_path, "before": before, "after": after, "removed": removed}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/debug/db-info", dependencies=[Depends(verify_api_key)])
def db_info():
    """Show database info and table counts."""
    try:
        import sqlite3
        from backend.storage.db_finder import resolve_db_path

        db_path = resolve_db_path()
        if not Path(db_path).exists():
            return {"error": "DB not found", "searched": [str(DB_PATH)]}

        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in c.fetchall()]
        counts = {}
        for t in tables:
            c.execute(f"SELECT COUNT(*) FROM {t}")
            counts[t] = c.fetchone()[0]
        conn.close()
        return {"db_path": db_path, "tables": tables, "counts": counts, "railway": IS_RAILWAY}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/debug/dedup", dependencies=[Depends(verify_api_key)])
def dedup_predictions():
    """Remove duplicate predictions."""
    try:
        from backend.storage.db_finder import resolve_db_path, run_predictions_dedup

        db_path = resolve_db_path()
        if not Path(db_path).exists():
            return {"error": "DB not found", "path": db_path}

        before, after, removed = run_predictions_dedup(db_path)
        return {"success": True, "db_path": db_path, "before": before, "after": after, "removed": removed}
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug/pipeline", dependencies=[Depends(verify_api_key)])
def debug_pipeline_viewer():
    """Serve HTML pipeline observability viewer."""
    viewer = PROJECT_ROOT / 'debug_pipeline_viewer.html'
    if not viewer.exists():
        raise HTTPException(status_code=404, detail="debug_pipeline_viewer.html not found")
    return FileResponse(viewer, media_type='text/html')


@app.get("/api/debug/snapshots", dependencies=[Depends(verify_api_key)])
def debug_snapshots_list():
    from backend.ai.pipeline_observability import list_snapshots
    return list_snapshots()


@app.get("/api/debug/preservation", dependencies=[Depends(verify_api_key)])
def api_debug_preservation(cycle_id: Optional[str] = Query(None)):
    from backend.ai.pipeline_observability import debug_preservation as get_preservation_debug
    return _safe_debug_response('preservation', get_preservation_debug, cycle_id)


@app.get("/api/debug/compression", dependencies=[Depends(verify_api_key)])
def api_debug_compression(cycle_id: Optional[str] = Query(None)):
    from backend.ai.pipeline_observability import debug_compression as get_compression_debug
    return _safe_debug_response('compression', get_compression_debug, cycle_id)


@app.get("/api/debug/ai-routing", dependencies=[Depends(verify_api_key)])
def api_debug_ai_routing(cycle_id: Optional[str] = Query(None)):
    from backend.ai.pipeline_observability import debug_ai_routing as get_routing_debug
    return _safe_debug_response('ai-routing', get_routing_debug, cycle_id)


@app.get("/api/debug/delta-analysis", dependencies=[Depends(verify_api_key)])
def api_debug_delta_analysis(cycle_id: Optional[str] = Query(None)):
    from backend.ai.pipeline_observability import debug_delta_analysis as get_delta_debug
    return _safe_debug_response('delta-analysis', get_delta_debug, cycle_id)


@app.get("/api/debug/quality", dependencies=[Depends(verify_api_key)])
def api_debug_quality(cycle_id: Optional[str] = Query(None)):
    from backend.ai.pipeline_observability import debug_quality as get_quality_debug
    return _safe_debug_response('quality', get_quality_debug, cycle_id)


@app.get("/api/debug/telegram-alerts", dependencies=[Depends(verify_api_key)])
def api_debug_telegram_alerts():
    from backend.orchestration.alert_scheduler import get_scheduler_status
    return get_scheduler_status()


@app.get("/api/debug/explanations", dependencies=[Depends(verify_api_key)])
def api_debug_explanations():
    from backend.utils.config import ANALYSIS_EXPLANATIONS_FILE
    path = ANALYSIS_EXPLANATIONS_FILE
    if not path.exists():
        return sanitize_json_value({"status": "degraded", "reason": "file_missing", "latest": None, "quality_history": []})
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {"latest": None, "quality_history": []}
        data.setdefault('status', 'ok')
        return sanitize_json_value(data)
    except Exception as e:
        return sanitize_json_value({
            "status": "degraded",
            "reason": str(e),
            "latest": None,
            "quality_history": [],
        })


@app.get("/api/debug/reliability", dependencies=[Depends(verify_api_key)])
def api_debug_reliability():
    from backend.metrics.execution_metrics import get_reliability_debug
    return _safe_debug_response('reliability', get_reliability_debug)


def main():
    port = API_PORT
    host = API_HOST
    print("=" * 60)
    print("TRADING COPILOT API SERVER + SCHEDULER + TELEGRAM v5")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"Railway: {'yes' if IS_RAILWAY else 'no'}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"DB:   {DB_PATH}")
    print(f"AI: {'Available' if AI_AVAILABLE else 'NOT available'}")
    print(f"Auth: {'X-API-Key required' if API_KEY else 'OPEN MODE'}")
    print("=" * 60)
    backend_log.info("Uvicorn starting host=%s port=%s railway=%s", host, port, IS_RAILWAY)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()