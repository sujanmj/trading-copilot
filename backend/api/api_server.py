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
    from fastapi import FastAPI, HTTPException, Body, Header, Depends, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    import uvicorn
except ImportError:
    print("[ERROR] FastAPI not installed.")
    sys.exit(1)

from backend.utils.bootstrap import setup_project_path

setup_project_path()

from backend.config.local_safe_mode import apply_railway_telegram_defaults

apply_railway_telegram_defaults()

from backend.utils.config import (
    IS_RAILWAY,
    IS_LOCAL_DEV,
    LOCAL_ONLY,
    LOCAL_FORCE_EOD,
    DISABLE_TELEGRAM,
    DISABLE_TELEGRAM_LISTENER,
    DISABLE_TELEGRAM_SENDS,
    DISABLE_LEGACY_TELEGRAM_LISTENER,
    PROJECT_ROOT,
    DATA_DIR,
    LOGS_DIR,
    RUNTIME_SNAPSHOT_CACHE,
    CURRENT_SNAPSHOT_FILE,
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
_watchdog_last_refresh_at = 0.0
_watchdog_recovery_failures = 0
_watchdog_refresh_pending = False
_analyzer_running = False
_subprocess_restart_log_at: dict = {}

SCHEDULER_SCRIPT = 'master_scheduler.py'
SCHEDULER_SINGLETON_POLL_SECONDS = 120
SCHEDULER_CRASH_RESTART_SECONDS = 30
SCHEDULER_EXIT_SINGLETON = 75
SUBPROCESS_WARN_COOLDOWN_SECONDS = 300

_background_started = False
_background_lock = threading.Lock()
_orchestrator_recovery_started = False

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

_local_auth_bypass_logged = False


def _is_railway_deployed() -> bool:
    """True on Railway regardless of LOCAL_DEV_MODE — keeps production auth strict."""
    return bool(
        os.environ.get('RAILWAY_ENVIRONMENT')
        or os.environ.get('RAILWAY_PROJECT_ID')
        or os.environ.get('RAILWAY_SERVICE_NAME')
    )


def _is_local_client(request: Request) -> bool:
    if request.client is None:
        return False
    host = (request.client.host or '').strip().lower()
    return host in ('127.0.0.1', '::1', 'localhost')


def local_auth_bypass_enabled() -> bool:
    """LOCAL_DEV_MODE auth bypass is available (localhost requests only)."""
    return IS_LOCAL_DEV and not _is_railway_deployed()


def verify_api_key(request: Request, x_api_key: Optional[str] = Header(None)):
    global _local_auth_bypass_logged
    if not API_KEY:
        return True
    if local_auth_bypass_enabled() and _is_local_client(request):
        if not _local_auth_bypass_logged:
            print('[LOCAL AUTH] bypass active for localhost', flush=True)
            _local_auth_bypass_logged = True
        return True
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return True


# ============================================================
# BACKGROUND PROCESSES
# ============================================================

def _scheduler_singleton_active() -> bool:
    from backend.utils.process_lock import is_lock_holder_valid
    return is_lock_holder_valid('master_scheduler')


def _log_subprocess_event(label: str, message: str, *, force: bool = False):
    """Throttle repetitive subprocess restart warnings."""
    now = time.time()
    last = _subprocess_restart_log_at.get(label, 0.0)
    if force or (now - last) >= SUBPROCESS_WARN_COOLDOWN_SECONDS:
        print(message)
        _subprocess_restart_log_at[label] = now


def _wait_scheduler_singleton_health():
    """Poll singleton scheduler health; break early on recovery signal or stale lock."""
    polls = max(1, SCHEDULER_SINGLETON_POLL_SECONDS // 15)
    for _ in range(polls):
        if should_force_scheduler_retry():
            print("[ORCHESTRATOR] recovery signal — retry scheduler launch immediately", flush=True)
            return
        from backend.orchestration.recovery_loop import handle_scheduler_singleton_exit
        action = handle_scheduler_singleton_exit(SCHEDULER_EXIT_SINGLETON)
        if action == 'retry_immediate':
            print("[ORCHESTRATOR] stale singleton — retry scheduler launch immediately", flush=True)
            return
        if not _scheduler_singleton_active():
            print("[SCHEDULER CRASH DETECTED] Singleton lock lost — recovery launch")
            return
        time.sleep(15)
    if _scheduler_singleton_active():
        print("[SCHEDULER HEALTHY] Singleton scheduler still active")
        _log_subprocess_event('Scheduler', "[WATCHDOG NO-RESTART] Scheduler singleton healthy")
    else:
        print("[ORCHESTRATOR] singleton lost during wait — recovery launch", flush=True)


def should_force_scheduler_retry() -> bool:
    try:
        from backend.orchestration.recovery_loop import should_force_scheduler_retry as _retry
        return _retry()
    except Exception:
        return False


def orchestrator_recovery_loop():
    """Lightweight health verification — bounded recovery only (60s tick)."""
    time.sleep(15)  # allow scheduler subprocess to boot
    while True:
        try:
            from backend.orchestration.recovery_loop import run_orchestrator_health_tick
            run_orchestrator_health_tick()
        except Exception as e:
            print(f"[ORCHESTRATOR] health loop error: {e}", flush=True)
        time.sleep(60)


def start_orchestrator_recovery_thread():
    global _orchestrator_recovery_started
    if IS_LOCAL_DEV:
        print("[LOCAL RUNTIME] cloud orchestrator recovery loop disabled", flush=True)
        return
    if _orchestrator_recovery_started:
        return
    _orchestrator_recovery_started = True
    t = threading.Thread(
        target=orchestrator_recovery_loop,
        daemon=True,
        name='OrchestratorRecovery',
    )
    t.start()
    print("[ORCHESTRATOR] lightweight recovery loop started (60s, 15m cooldown)", flush=True)


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
                if rc == SCHEDULER_EXIT_SINGLETON:
                    from backend.orchestration.recovery_loop import (
                        handle_scheduler_singleton_exit,
                        scheduler_retry_backoff_seconds,
                    )
                    action = handle_scheduler_singleton_exit(rc)
                    if action == 'retry_immediate':
                        backoff = scheduler_retry_backoff_seconds()
                        print(
                            f"[ORCHESTRATOR] stale singleton — retry scheduler in {backoff}s",
                            flush=True,
                        )
                        time.sleep(backoff)
                        continue
                    if not _scheduler_singleton_active():
                        backoff = scheduler_retry_backoff_seconds()
                        print(
                            f"[ORCHESTRATOR] lock free after singleton exit — retry in {backoff}s",
                            flush=True,
                        )
                        time.sleep(backoff)
                        continue
                    print("[SCHEDULER SINGLETON SKIP] Duplicate launch blocked — primary holds lock")
                    _log_subprocess_event(
                        'Scheduler',
                        "[WATCHDOG NO-RESTART] Singleton guard exit — not a crash",
                        force=True,
                    )
                    _wait_scheduler_singleton_health()
                    continue

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
                    # Grace period — lock may release briefly during handoff
                    time.sleep(5)
                    if _scheduler_singleton_active():
                        print("[SCHEDULER HEALTHY] Clean exit but singleton re-acquired — no restart")
                        _wait_scheduler_singleton_health()
                        continue
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
                _log_subprocess_event(label, f"[INFO] {label} exited cleanly — idle wait (no storm restart)")
                time.sleep(120)
                continue
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
    """Legacy wrapper — routes through severity policy (prefer emit_operational_alert)."""
    from backend.utils.alert_routing import HIGH, emit_operational_alert
    from backend.utils.market_hours import get_market_period
    emit_operational_alert(
        'watchdog_legacy',
        HIGH,
        message,
        period=get_market_period(),
    )


def _check_watchdog_emergency() -> tuple:
    """Emergency override for night-mode refresh — logic unchanged, delegated to alert router."""
    try:
        state = {}
        if (DATA_DIR / 'analysis_state.json').exists():
            with open(DATA_DIR / 'analysis_state.json', 'r', encoding='utf-8') as f:
                state = json.load(f) or {}
        from backend.utils.alert_routing import emergency_requires_refresh
        return emergency_requires_refresh(state)
    except Exception as e:
        watchdog_log.debug('Emergency check failed: %s', e)
    return False, ''


def stale_data_watchdog():
    """Background loop: auto-run master_analyzer if intelligence file is stale."""
    global _watchdog_last_trigger, _analyzer_running, _watchdog_last_refresh_at, _watchdog_recovery_failures, _watchdog_refresh_pending

    if IS_LOCAL_DEV:
        from backend.utils.local_runtime import local_log
        local_log('LOCAL RUNTIME', 'cloud stale-data watchdog disabled')
        return

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)
        try:
            from backend.utils.market_hours import get_watchdog_config, get_market_period
            from backend.utils.alert_routing import (
                SILENT,
                HIGH,
                CRITICAL,
                classify_emergency_severity,
                emit_operational_alert,
                record_operational_event,
            )

            wd_cfg = get_watchdog_config()
            period = wd_cfg.get('period') or get_market_period()
            threshold = int(wd_cfg['stale_threshold_seconds'])
            mode = wd_cfg['mode']
            print(f"[WATCHDOG MODE] {mode} threshold={threshold}s")
            if wd_cfg.get('night_mode'):
                print(f"[NIGHT MODE STALE TOLERANCE] active — threshold {threshold // 3600}h")

            age = file_age_seconds('unified_intelligence.json')
            if not age:
                continue

            if age <= threshold:
                if _watchdog_recovery_failures:
                    record_operational_event(
                        'watchdog_recovery_ok',
                        SILENT,
                        f'Intelligence fresh again ({age}s)',
                        meta={'age_seconds': age},
                        telegram_decision='silent',
                    )
                _watchdog_recovery_failures = 0
                _watchdog_refresh_pending = False
                if wd_cfg.get('market_hours'):
                    print(f"[MARKET HOURS STALE CHECK] age={age}s ok (<{threshold}s)")
                continue

            # Track failed recovery once after a refresh completes but intelligence remains stale
            if _watchdog_refresh_pending and not _analyzer_running:
                _watchdog_recovery_failures += 1
                _watchdog_refresh_pending = False

            state = {}
            if (DATA_DIR / 'analysis_state.json').exists():
                with open(DATA_DIR / 'analysis_state.json', 'r', encoding='utf-8') as f:
                    state = json.load(f) or {}

            emergency, emergency_reason = _check_watchdog_emergency()
            if wd_cfg.get('night_mode') and not emergency:
                print(f"[NIGHT MODE STALE TOLERANCE] stale {age}s — no emergency, skip refresh")
                record_operational_event(
                    'watchdog_stale_skipped_night',
                    SILENT,
                    f'Stale {age}s skipped in {mode} (no emergency)',
                    meta={'age_seconds': age, 'mode': mode},
                    telegram_decision='silent',
                )
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
            _watchdog_last_refresh_at = now
            _watchdog_refresh_pending = True
            hours = age // 3600
            msg = f"Intelligence {hours}h stale ({mode})! Auto-recovering..."
            if emergency:
                msg += f" [EMERGENCY: {emergency_reason}]"
            print(f"[WATCHDOG] {msg}")
            watchdog_log.warning(msg)

            # Routine stale refresh → OPS only (SILENT for Telegram)
            record_operational_event(
                'watchdog_stale_refresh',
                SILENT,
                msg,
                meta={
                    'mode': mode,
                    'period': period,
                    'age_seconds': age,
                    'emergency': emergency,
                    'emergency_reason': emergency_reason or None,
                },
                telegram_decision='silent_routine_refresh',
            )

            # Unrecovered stale after repeated refresh attempts → HIGH (actionable)
            if _watchdog_recovery_failures >= 2:
                emit_operational_alert(
                    'watchdog_stale_unrecovered',
                    HIGH,
                    f"Intelligence still stale after {_watchdog_recovery_failures} recovery attempts "
                    f"({hours}h, {mode}). Manual check recommended.",
                    period=period,
                    meta={
                        'recovery_failures': _watchdog_recovery_failures,
                        'age_hours': hours,
                        'contradiction_score': state.get('disagreement_score'),
                    },
                )

            # Emergency context → severity-based Telegram (0.85+ contradiction, etc.)
            if emergency and emergency_reason:
                sev = classify_emergency_severity(emergency_reason, state)
                if sev in (CRITICAL, HIGH):
                    disagree = float(state.get('disagreement_score') or 0)
                    emit_operational_alert(
                        'watchdog_emergency',
                        sev,
                        f"Emergency during stale recovery ({mode}): {emergency_reason}. "
                        f"Auto-refresh in progress.",
                        period=period,
                        meta={
                            'emergency_reason': emergency_reason,
                            'contradiction_score': disagree,
                            'volatility': state.get('volatility_index'),
                            'age_hours': hours,
                        },
                    )
                else:
                    record_operational_event(
                        'watchdog_emergency_logged',
                        sev,
                        f'{emergency_reason} (refresh triggered, Telegram suppressed — below warn threshold)',
                        meta={'emergency_reason': emergency_reason, 'contradiction_score': state.get('disagreement_score')},
                        telegram_decision='below_telegram_threshold',
                    )

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
            print("[WATCHDOG] Auto-refresh triggered — Telegram suppressed (routine recovery)")
        except Exception as e:
            print(f"[WATCHDOG] Error: {e}")
            watchdog_log.error("Watchdog error: %s", e)
            try:
                from backend.utils.alert_routing import CRITICAL, emit_operational_alert
                from backend.utils.market_hours import get_market_period
                emit_operational_alert(
                    'watchdog_error',
                    CRITICAL,
                    f"Watchdog loop error: {str(e)[:200]}",
                    period=get_market_period(),
                )
            except Exception:
                pass


def _run_local_scheduler_loop():
    """In-process scheduler — no subprocess singleton complexity."""
    from backend.utils.local_runtime import local_log
    while True:
        try:
            local_log('LOCAL RUNTIME', 'starting in-process master scheduler')
            from backend.orchestration.master_scheduler import main as scheduler_main
            scheduler_main()
        except Exception as e:
            local_log('RESTART', f'scheduler exited: {e} — retry in 5s')
            time.sleep(5)


def _telegram_fully_disabled() -> bool:
    return DISABLE_TELEGRAM or DISABLE_TELEGRAM_LISTENER


def _legacy_telegram_listener_active() -> bool:
    """True when legacy telegram_listener.py subprocess would start."""
    if _telegram_fully_disabled():
        return False
    return not DISABLE_LEGACY_TELEGRAM_LISTENER


def _telegram_listener_disabled() -> bool:
    return _telegram_fully_disabled()


def _log_telegram_disabled(component: str = 'listener') -> None:
    if DISABLE_LEGACY_TELEGRAM_LISTENER and not (DISABLE_TELEGRAM or DISABLE_TELEGRAM_LISTENER):
        print('LEGACY_TELEGRAM_LISTENER_DISABLED', flush=True)
        return
    print(
        f'[TELEGRAM DISABLED] {component} not started '
        f'(DISABLE_TELEGRAM={int(DISABLE_TELEGRAM)} '
        f'DISABLE_TELEGRAM_LISTENER={int(DISABLE_TELEGRAM_LISTENER)} '
        f'DISABLE_LEGACY_TELEGRAM_LISTENER={int(DISABLE_LEGACY_TELEGRAM_LISTENER)} '
        f'DISABLE_TELEGRAM_SENDS={int(DISABLE_TELEGRAM_SENDS)})',
        flush=True,
    )


def _run_local_telegram_loop():
    from backend.utils.local_runtime import local_log
    while True:
        try:
            local_log('LOCAL RUNTIME', 'starting in-process telegram listener')
            from backend.orchestration.telegram_listener import listen_forever
            listen_forever()
        except Exception as e:
            local_log('RESTART', f'telegram listener exited: {e} — retry in 10s')
            time.sleep(10)


def start_local_background_processes():
    """Deterministic single-runtime local mode — in-process threads only."""
    from backend.utils.local_runtime import local_log, run_local_validation_loop, schedule_local_force_eod

    local_log('LOCAL RUNTIME', 'single-process mode — locks/recovery disabled')
    try:
        from backend.ai.provider_manager import log_provider_startup_diagnostics
        log_provider_startup_diagnostics(force=True)
    except Exception as e:
        local_log('AUTOFIX', f'provider diagnostics: {e}')

    if os.environ.get('DISABLE_SCHEDULER') != '1':
        threading.Thread(
            target=_run_local_scheduler_loop,
            daemon=True,
            name='LocalScheduler',
        ).start()
        local_log('LOCAL RUNTIME', 'scheduler thread started (in-process)')
    else:
        local_log('LOCAL RUNTIME', 'scheduler disabled via DISABLE_SCHEDULER=1')

    if _telegram_listener_disabled():
        _log_telegram_disabled('in-process listener')
    else:
        threading.Thread(
            target=_run_local_telegram_loop,
            daemon=True,
            name='LocalTelegram',
        ).start()
        local_log('LOCAL RUNTIME', 'telegram listener thread started (in-process)')

    schedule_local_force_eod(delay_seconds=25)
    run_local_validation_loop(max_rounds=40, interval=15)
    local_log('LOCAL RUNTIME', 'GUI hooks: set API_BASE_URL=http://127.0.0.1:8080 then npm start')


def start_background_processes():
    """Launch scheduler and telegram listener in daemon threads (once)."""
    global _background_started
    with _background_lock:
        if _background_started:
            backend_log.info("Background processes already started — skip duplicate startup")
            print("[INFO] Background processes already running — skip duplicate startup")
            return
        _background_started = True

    if IS_LOCAL_DEV:
        start_local_background_processes()
        return

    try:
        from backend.orchestration.recovery_loop import bootstrap_self_healing
        bootstrap_self_healing(os.getpid())
    except Exception as e:
        print(f"[ORCHESTRATOR] bootstrap failed: {e}", flush=True)

    start_orchestrator_recovery_thread()

    backend_log.info("Starting background processes (railway=%s)", IS_RAILWAY)
    try:
        from backend.ai.provider_manager import log_provider_startup_diagnostics
        log_provider_startup_diagnostics(force=True)
    except Exception as e:
        print(f"[AI PROVIDERS] WARN diagnostics failed: {e}")

    # Scheduler thread — PRIMARY runtime only
    if os.environ.get('DISABLE_SCHEDULER') != '1':
        try:
            from backend.utils.process_lock import clear_stale_lock
            if clear_stale_lock('master_scheduler'):
                print("[SCHEDULER] Cleared stale master_scheduler lock on startup", flush=True)
        except Exception as e:
            print(f"[SCHEDULER] Stale lock cleanup failed: {e}", flush=True)
        scheduler_thread = threading.Thread(
            target=run_subprocess_loop,
            args=('master_scheduler.py', 'Scheduler'),
            daemon=True,
            name='Scheduler',
        )
        scheduler_thread.start()
        print("[INFO] Scheduler thread started")
        backend_log.info("Scheduler thread started")
    else:
        try:
            from backend.orchestration.orchestrator_state import mark_api_only
            mark_api_only('DISABLE_SCHEDULER=1')
        except Exception:
            pass
        print("[ORCHESTRATOR] API_ONLY — scheduler disabled", flush=True)
    
    # Telegram — legacy subprocess or AstraEdge analysis bot (never both)
    if _telegram_listener_disabled():
        _log_telegram_disabled('subprocess listener')
    elif DISABLE_LEGACY_TELEGRAM_LISTENER:
        print('LEGACY_TELEGRAM_LISTENER_DISABLED', flush=True)
        try:
            from backend.telegram.telegram_analysis_bot import ensure_astraedge_telegram_started
            ensure_astraedge_telegram_started()
        except Exception as e:
            print(f'[ASTRAEDGE_TELEGRAM] start failed: {e}', flush=True)
    else:
        telegram_thread = threading.Thread(
            target=run_subprocess_loop,
            args=('telegram_listener.py', 'TelegramListener'),
            daemon=True,
            name='TelegramListener',
        )
        telegram_thread.start()
        print('[INFO] Telegram listener thread started')

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


def _local_browser_cors_origins() -> list[str]:
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ]


def _cors_allow_origins() -> list[str]:
    origins = list(_local_browser_cors_origins())
    extra = os.environ.get('ALLOWED_ORIGINS', '').strip()
    if extra:
        for part in extra.split(','):
            part = part.strip()
            if part and part not in origins:
                origins.append(part)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
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


def load_tv_intelligence() -> dict:
    """Load cached TV intelligence (Stage 21B); fallback to legacy youtube_feed.json."""
    try:
        from backend.collectors.tv_intelligence_collector import load_cached_tv_intelligence

        return sanitize_json_value(load_cached_tv_intelligence())
    except Exception as e:
        return {'ok': False, 'error': str(e), 'videos': [], 'summary': {}}


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
        "auth_required": bool(API_KEY) and not local_auth_bypass_enabled(),
        "local_auth_bypass": local_auth_bypass_enabled(),
    }


@app.get("/api/config")
def api_config():
    """Public deployment info for GUI bootstrap."""
    return {
        "railway": IS_RAILWAY,
        "local_dev": IS_LOCAL_DEV,
        "auth_required": bool(API_KEY) and not local_auth_bypass_enabled(),
        "local_auth_bypass": local_auth_bypass_enabled(),
        "data_dir": str(DATA_DIR),
        "db_path": str(DB_PATH),
    }


@app.get("/api/health")
def health():
    return _build_health_payload()


@app.get("/api/debug/build-info")
def api_debug_build_info():
    """Deployment build identity — handler selection and data root."""
    from backend.config.local_safe_mode import is_railway_mode
    from backend.storage.data_paths import data_preserved, get_data_root
    from backend.telegram.telegram_analysis_bot import is_astraedge_telegram_started

    app_mode = os.environ.get('APP_MODE', '').strip().lower()
    if not app_mode:
        app_mode = 'railway' if is_railway_mode() else 'local'
    data_root = get_data_root()
    return sanitize_json_value({
        'app': 'AstraEdge',
        'stage': '47F',
        'decision_bootstrap': 'enabled',
        'report_bootstrap': 'enabled',
        'telegram_handler': 'astraedge_analysis_bot',
        'legacy_telegram_listener': _legacy_telegram_listener_active(),
        'astraedge_telegram_started': is_astraedge_telegram_started(),
        'app_mode': app_mode,
        'data_root': str(data_root).replace('\\', '/'),
        'data_preserved': data_preserved(),
    })


def _load_explanations_light() -> dict:
    from backend.utils.config import ANALYSIS_EXPLANATIONS_FILE
    path = ANALYSIS_EXPLANATIONS_FILE
    if not path.exists():
        return {"status": "degraded", "reason": "file_missing", "latest": None, "quality_history": []}
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


def _panel_state_from_source(
    key: str,
    source_status: dict,
    *,
    ready: bool = True,
    waiting_message: str = '',
    collecting_message: str = '',
    operational: Optional[dict] = None,
) -> dict:
    src = source_status.get(key) or {}
    status_name = src.get('status') or 'missing'
    stale = status_name == 'stale'
    age = src.get('age_seconds')
    op = operational or {}

    if status_name == 'idle':
        return {
            'status': 'idle',
            'stale': False,
            'message': src.get('idle_message') or op.get('display_message') or 'Collectors idle — market closed.',
            'age_seconds': age,
            'operational_mode': op.get('operational_mode'),
        }
    if status_name == 'missing' or not ready:
        return {
            'status': 'waiting',
            'stale': True,
            'message': waiting_message or f'Waiting for {key} data.',
            'age_seconds': age,
        }
    if collecting_message:
        return {
            'status': 'collecting',
            'stale': stale,
            'message': collecting_message,
            'age_seconds': age,
        }
    if stale and op.get('expect_quiet_collectors'):
        return {
            'status': 'idle',
            'stale': False,
            'message': src.get('idle_message') or op.get('display_message'),
            'age_seconds': age,
            'operational_mode': op.get('operational_mode'),
        }
    return {
        'status': 'stale' if stale else 'ready',
        'stale': stale,
        'message': f'{key} data is stale — watchdog may refresh.' if stale else None,
        'age_seconds': age,
    }


def _collectors_recently_active(source_status: dict, operational: dict) -> bool:
    """True when scanner/news/reddit or market feeds refreshed within watchdog cadence."""
    cadence_keys = ('scanner', 'news', 'reddit', 'youtube', 'inshorts', 'markets', 'india')
    threshold = int(operational.get('watchdog_stale_threshold_seconds') or STALE_THRESHOLD_SECONDS)
    for key in cadence_keys:
        src = source_status.get(key) or {}
        if src.get('status') not in ('ok', 'idle'):
            continue
        age = src.get('age_seconds')
        if age is not None and age <= threshold:
            return True
    return False


def _build_runtime_snapshot() -> dict:
    """Single synchronized payload for all frontend intelligence surfaces."""
    from backend.utils.market_hours import get_operational_status
    generated_at = datetime.now().isoformat()
    operational = get_operational_status()
    health_payload = _build_health_payload()
    source_status = health_payload.get('source_status') or {}

    data = {
        'intelligence': load_json_file('unified_intelligence.json'),
        'scanner': load_json_file('scanner_data.json'),
        'govt': load_json_file('govt_intelligence.json'),
        'news': load_json_file('news_feed.json'),
        'reddit': load_json_file('reddit_data.json'),
        'markets': load_json_file('global_markets.json'),
        'india': load_json_file('latest_market_data.json'),
        'youtube': load_tv_intelligence(),
        'inshorts': load_json_file('inshorts_feed.json'),
        'stats': load_json_file('stats_data.json'),
        'history': load_json_file('history_data.json'),
        'active_predictions': load_json_file('active_predictions.json'),
        'prediction_history': load_json_file('prediction_history.json'),
        'lifecycle_state': load_json_file('lifecycle_state.json'),
    }
    overnight_impact = {}
    overnight_timeline = {}
    india_next_open = {}
    try:
        from backend.intelligence.global_intelligence_engine import (
            get_overnight_global_impact,
            get_overnight_timeline,
        )
        from backend.intelligence.india_next_open_engine import build_india_next_open_report
        overnight_impact = get_overnight_global_impact()
        overnight_timeline = get_overnight_timeline()
        if (DATA_DIR / 'india_next_open.json').exists():
            india_next_open = load_json_file('india_next_open.json')
        elif overnight_impact.get('india_next_open'):
            india_next_open = overnight_impact['india_next_open']
    except Exception:
        pass
    active_snapshot_meta = {}
    snapshot_health_payload = {}
    stability_payload = {}
    try:
        from backend.intelligence.active_snapshot import (
            get_active_snapshot_meta,
            get_canonical_intelligence,
            snapshot_health,
        )
        from backend.production.stability_monitor import run_stability_probe
        data['intelligence'] = get_canonical_intelligence()
        active_snapshot_meta = get_active_snapshot_meta()
        snapshot_health_payload = snapshot_health()
        stability_payload = run_stability_probe()
    except Exception:
        pass

    stats = data.get('stats') or {}
    history = data.get('history') or {}
    intelligence = data.get('intelligence') or {}
    try:
        from backend.lifecycle.unified_metrics import get_unified_snapshot
        live_agg = get_unified_snapshot()
        stats = dict(stats)
        from backend.metrics.canonical_metrics import build_canonical_metrics
        for bucket in ('metrics_all_time', 'metrics_weekly', 'metrics_daily'):
            raw_m = live_agg.get(bucket) or stats.get(bucket) or {}
            stats[bucket] = build_canonical_metrics(raw_m)
        stats['metrics_all_time'] = stats.get('metrics_all_time') or {}
        stats['metrics_weekly'] = stats.get('metrics_weekly') or {}
        stats['metrics_daily'] = stats.get('metrics_daily') or {}
        stats['db_stats'] = live_agg.get('db_stats') or stats.get('db_stats') or {}
        stats['predictions'] = live_agg.get('predictions') or stats.get('predictions') or {}
        stats['metric_sections'] = live_agg.get('metric_sections') or {}
        if live_agg.get('calibration'):
            stats['lifecycle_calibration'] = live_agg['calibration']
        data['stats'] = stats
        data['overnight_impact'] = overnight_impact
        data['india_next_open'] = india_next_open
        data['overnight_timeline'] = overnight_timeline
        try:
            from backend.intelligence.market_close_intelligence import build_market_close_report
            mclose_path = DATA_DIR / 'market_close_intelligence.json'
            if mclose_path.exists():
                data['market_close_intelligence'] = load_json_file('market_close_intelligence.json')
            else:
                data['market_close_intelligence'] = build_market_close_report(persist=False)
        except Exception:
            data['market_close_intelligence'] = {}
    except Exception:
        pass
    db_stats = stats.get('db_stats') or {}
    metrics = stats.get('metrics_all_time') or {}
    journal = history.get('intelligence_journal') or {}
    journal_entries = journal.get('entries') or []

    intel_ok = bool(intelligence) and not intelligence.get('error')
    stats_ok = bool(stats) and not stats.get('error')
    history_ok = bool(history) and not history.get('error')
    market_ok = (
        (source_status.get('markets') or {}).get('status') not in (None, 'missing')
        or (source_status.get('india') or {}).get('status') not in (None, 'missing')
    )

    evaluated = int(metrics.get('evaluated') or metrics.get('total_evaluated') or 0)

    lifecycle_panel = {
        'status': 'waiting',
        'pipeline_status': 'STALE',
        'stale': True,
        'message': 'Post-market evaluation cycle has not completed today.',
        'calibration_message': 'Awaiting evaluated prediction sample size.',
    }
    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_lifecycle_status
        lc = get_lifecycle_status()
        lifecycle_panel = {
            'status': 'ready' if lc.get('evaluation_cycle_complete') else ('idle' if lc.get('pipeline_status') == 'IDLE' else 'waiting'),
            'pipeline_status': lc.get('pipeline_status', 'STALE'),
            'stale': lc.get('pipeline_status') in (None, 'STALE', 'FAILED') and not (
                operational.get('expect_quiet_collectors') and lc.get('pipeline_status') == 'IDLE'
            ),
            'message': lc.get('message'),
            'calibration_message': lc.get('calibration_message'),
            'active_predictions': lc.get('active_predictions'),
            'archived_predictions': lc.get('archived_predictions'),
            'unresolved_predictions': lc.get('unresolved_predictions'),
            'last_eod_cycle_at': lc.get('last_eod_cycle_at'),
            'last_successful_eod': lc.get('last_successful_eod'),
            'last_stats_export': lc.get('last_stats_export'),
            'last_history_export': lc.get('last_history_export'),
            'last_calibration_export': lc.get('last_calibration_export'),
            'recovery_reason': lc.get('recovery_reason'),
            'exports_fresh': lc.get('exports_fresh'),
            'calibration_fresh': lc.get('calibration_fresh'),
            'review_fresh': lc.get('review_fresh'),
            'review_age_minutes': lc.get('review_age_minutes'),
        }
    except Exception:
        pass

    calibration_panel = _panel_state_from_source(
        'stats',
        source_status,
        ready=stats_ok,
        waiting_message='Awaiting evaluated prediction sample size.',
    )
    cal_phase = 'LEARNING'
    try:
        from backend.calibration.calibration_state import build_calibration_display
        cal_phase = build_calibration_display(metrics).get('phase', 'LEARNING')
    except Exception:
        pass
    if stats_ok and evaluated == 0:
        lc_msg = lifecycle_panel.get('calibration_message') or 'Awaiting evaluated prediction sample size.'
        calibration_panel = {
            'status': 'collecting',
            'stale': calibration_panel.get('stale', False),
            'message': lc_msg,
            'age_seconds': calibration_panel.get('age_seconds'),
            'phase': cal_phase,
        }
    else:
        calibration_panel['phase'] = cal_phase

    journal_panel = {
        'status': 'waiting',
        'stale': False,
        'message': 'Waiting for post-market review generation.',
        'entry_count': len(journal_entries),
        'latest': journal.get('latest'),
        'age_seconds': (source_status.get('history') or {}).get('age_seconds'),
    }
    if lifecycle_panel.get('status') == 'ready':
        journal_panel['message'] = None
        if journal_entries:
            journal_panel['status'] = 'ready'
        elif history_ok:
            journal_panel['status'] = 'collecting'
            journal_panel['message'] = 'Review generated — journal indexing in progress.'
    if journal_entries:
        journal_panel['status'] = 'ready'
        journal_panel['message'] = None
    elif not history_ok:
        journal_panel['stale'] = True

    any_stale = any(
        (source_status.get(k) or {}).get('status') == 'stale'
        for k in ('intelligence', 'markets', 'india', 'stats', 'history')
    ) and not operational.get('expect_quiet_collectors')

    ai_runtime = {}
    try:
        from backend.analytics.provider_analytics import get_ai_runtime_stats_payload
        ai_runtime = get_ai_runtime_stats_payload()
    except Exception:
        ai_runtime = {'status': 'degraded'}

    orchestrator_panel = {
        'status': 'waiting',
        'stale': True,
        'message': 'Orchestrator heartbeat pending…',
        'mode': 'RECOVERING',
    }
    try:
        from backend.orchestration.orchestrator_state import get_orchestrator_health_payload
        from backend.orchestration.recovery_loop import verify_gui_sync
        if IS_LOCAL_DEV:
            from backend.lifecycle.prediction_lifecycle_engine import get_lifecycle_status
            lc = get_lifecycle_status()
            healthy = lc.get('pipeline_status') == 'COMPLETE'
            orchestrator_panel = {
                'status': 'ready' if healthy else 'collecting',
                'stale': not healthy,
                'message': None if healthy else lc.get('message'),
                'mode': 'LOCAL',
                'gui_sync_validated': healthy,
            }
        else:
            orch = get_orchestrator_health_payload()
            gui = verify_gui_sync()
            healthy = bool(orch.get('runtime_healthy'))
            orchestrator_panel = {
                'status': 'ready' if healthy else 'stale',
                'stale': not healthy,
                'message': None if healthy else f"Recovery: {', '.join(orch.get('issues') or ['orchestrator stale'])[:120]}",
                'mode': orch.get('orchestrator_mode'),
                'last_scheduler_tick': orch.get('last_scheduler_tick'),
                'tick_age_seconds': orch.get('tick_age_seconds'),
                'recovery_attempts_today': orch.get('recovery_attempts_today'),
                'gui_sync_validated': gui.get('validated'),
            }
            if gui.get('validated'):
                backend_log.debug('GUI sync validated')
    except Exception as e:
        orchestrator_panel['message'] = str(e)[:120]

    collectors_active = _collectors_recently_active(source_status, operational)
    orchestrator_alive = not orchestrator_panel.get('stale', False)
    gui_sync_ok = bool(orchestrator_panel.get('gui_sync_validated'))
    export_stale = any_stale
    collectors_lag_refresh = (
        export_stale
        and (collectors_active or orchestrator_alive)
        and not operational.get('expect_quiet_collectors')
    )
    runtime_stale = (
        export_stale
        and not collectors_active
        and not orchestrator_alive
        and not operational.get('expect_quiet_collectors')
    )
    if gui_sync_ok and orchestrator_alive and evaluated > 0:
        runtime_stale = False
        calibration_panel['stale'] = False
        calibration_panel['status'] = 'ready'
        calibration_panel['message'] = None
        lifecycle_panel['stale'] = False

    if collectors_lag_refresh:
        runtime_message = 'Live collectors active — export refreshing'
    elif runtime_stale:
        runtime_message = orchestrator_panel.get('message') or 'Snapshot stale — no collector updates detected'
    elif operational.get('expect_quiet_collectors') and not any_stale:
        runtime_message = operational.get('display_message')
    else:
        runtime_message = None

    panels = {
        'runtime': {
            'status': operational.get('operational_mode') if operational.get('expect_quiet_collectors') and not any_stale else ('ready' if not runtime_stale else 'stale'),
            'stale': runtime_stale,
            'collectors_active': collectors_active,
            'export_lag': collectors_lag_refresh,
            'message': runtime_message,
            'generated_at': generated_at,
            'display_status': operational.get('display_status'),
            'operational_mode': operational.get('operational_mode'),
            'lifecycle_state': operational.get('lifecycle_state'),
            'active_snapshot_id': active_snapshot_meta.get('active_snapshot_id'),
            'snapshot_version': active_snapshot_meta.get('snapshot_version'),
            'snapshot_freshness_minutes': snapshot_health_payload.get('age_minutes'),
            'publish_latency_ms': None,
            'cache_state': 'canonical' if active_snapshot_meta.get('active_snapshot_id') else 'raw',
            'ai_mode': (ai_runtime or {}).get('mode') or (ai_runtime or {}).get('status'),
        },
        'brain': _panel_state_from_source(
            'intelligence',
            source_status,
            ready=intel_ok,
            waiting_message='Waiting for intelligence cycle.',
            operational=operational,
        ),
        'market': _panel_state_from_source(
            'markets',
            source_status,
            ready=market_ok,
            waiting_message='Waiting for market feed refresh.',
            operational=operational,
        ),
        'calibration': calibration_panel,
        'journal': journal_panel,
        'lifecycle': lifecycle_panel,
        'orchestrator': orchestrator_panel,
        'ops': {
            'status': operational.get('operational_mode') if operational.get('expect_quiet_collectors') and not any_stale else 'ready',
            'stale': any_stale,
            'message': operational.get('display_message') if operational.get('expect_quiet_collectors') and not any_stale else None,
            'display_status': operational.get('display_status'),
            'degraded_mode': (health_payload.get('provider_analytics') or {}).get('degraded_mode'),
        },
    }

    payload = sanitize_json_value({
        'status': 'ok',
        'generated_at': generated_at,
        'active_snapshot_id': active_snapshot_meta.get('active_snapshot_id'),
        'snapshot_cycle_id': active_snapshot_meta.get('cycle_id'),
        'snapshot_version': active_snapshot_meta.get('snapshot_version'),
        'snapshot_published_at': active_snapshot_meta.get('published_at'),
        'snapshot_health': snapshot_health_payload,
        'stability': stability_payload,
        'operational': operational,
        'panels': panels,
        'freshness': health_payload.get('data_freshness') or {},
        'source_status': source_status,
        'data': data,
        'ops': {
            'health': health_payload,
            'provider_analytics': health_payload.get('provider_analytics') or {},
            'provider_ops': health_payload.get('provider_ops') or {},
            'operational_alerts': health_payload.get('operational_alerts') or {},
            'pipeline_observability': health_payload.get('pipeline_observability') or {},
        },
        'explanations': _load_explanations_light(),
        'calibration_summary': {
            'predictions': metrics.get('prediction_total', db_stats.get('total_predictions', 0)),
            'evaluated': evaluated,
            'pending': metrics.get('pending', 0),
            'wins': metrics.get('wins', 0),
            'losses': metrics.get('losses', 0),
            'win_rate': metrics.get('win_rate'),
            'win_rate_display': metrics.get('win_rate_display'),
            'statistically_confident': metrics.get('statistically_confident'),
            'calibration_phase': cal_phase,
            'ai_runtime': ai_runtime,
            'dashboard_status': (stats.get('calibration_dashboard') or {}).get('status'),
            'metric_sections': (metrics.get('sections') or stats.get('metric_sections') or {}),
            'live_session': ((metrics.get('sections') or {}).get('live_session') or {}),
            'historical_calibration': ((metrics.get('sections') or {}).get('historical_calibration') or {}),
            'archived': ((metrics.get('sections') or {}).get('archived') or {}),
        },
        'journal_summary': {
            'entry_count': len(journal_entries),
            'latest': journal.get('latest'),
            'status': journal_panel['status'],
            'message': journal_panel.get('message'),
        },
        'lifecycle_summary': lifecycle_panel,
        'orchestrator_summary': orchestrator_panel,
        'freshness_state': {
            'export_stale': export_stale,
            'collectors_active': collectors_active,
            'orchestrator_alive': orchestrator_alive,
            'partial_lag': collectors_lag_refresh,
        },
        'overnight_impact': overnight_impact,
        'overnight_timeline': overnight_timeline,
        'india_next_open': india_next_open,
    })
    try:
        from backend.runtime.runtime_state import apply_to_snapshot_payload
        payload = apply_to_snapshot_payload(payload)
    except Exception:
        pass
    try:
        from backend.runtime.market_snapshot_engine import get_current_market_snapshot
        ms = get_current_market_snapshot()
        payload['market_snapshot'] = ms.to_dict()
        payload['snapshot_id'] = ms.snapshot_id
        payload['primary_state'] = (ms.runtime_state or {}).get('primary_state')
        payload['blockers'] = ms.blockers
        payload['pipeline_health'] = ms.pipeline_health
    except Exception:
        pass
    return payload


@app.get("/api/runtime/audit", dependencies=[Depends(verify_api_key)])
def api_runtime_audit(limit: int = Query(50, ge=1, le=200)):
    from backend.debug.runtime_audit import get_audit_report
    return get_audit_report(limit=limit)


@app.get("/api/runtime/debug", dependencies=[Depends(verify_api_key)])
def api_runtime_debug():
    """Lightweight debug payload for GUI debug overlay."""
    from backend.runtime.runtime_state import build_runtime_state
    from backend.logs.alert_suppression import suppression_summary
    from backend.orchestration.alert_deduplication import get_dedup_summary
    from backend.orchestration.alert_filters import get_telegram_alert_obs_summary

    state = build_runtime_state(force_refresh=True)
    fresh = state.get('snapshot_freshness') or {}
    lc = state.get('lifecycle') or {}
    sched = state.get('scheduler') or {}
    intel = state.get('intelligence_status') or {}
    alert = state.get('alert_eligibility') or {}

    return {
        'generated_at': state.get('generated_at'),
        'lifecycle_state': lc.get('lifecycle_state'),
        'lifecycle_display': lc.get('lifecycle_display'),
        'after_hours_mode': (state.get('session') or {}).get('after_hours_mode'),
        'freshness': {
            'age_minutes': fresh.get('age_minutes'),
            'age_display': fresh.get('age_display'),
            'health_tier': fresh.get('health_tier'),
            'stale': fresh.get('stale'),
        },
        'scheduler_phase': sched.get('phase'),
        'pipeline_status': sched.get('pipeline_status'),
        'ai_status': (state.get('ai_state') or {}).get('status'),
        'intelligence_status': intel.get('status'),
        'alert_eligible': alert.get('eligible'),
        'alert_block_reasons': alert.get('block_reasons') or [],
        'suppression': suppression_summary(limit=30),
        'dedupe': get_dedup_summary(),
        'telegram_obs': get_telegram_alert_obs_summary(),
        'consistency': state.get('consistency'),
        'scanner_health': state.get('scanner_health'),
        'pipeline': state.get('pipeline'),
        'stall_watchdog': state.get('stall_watchdog'),
    }


@app.post("/api/runtime/invalidate-cache", dependencies=[Depends(verify_api_key)])
def api_runtime_invalidate_cache(payload: dict = Body(default={})):
    """Bust GUI RuntimeManager cache after manual /refresh or recovery."""
    from backend.utils.config import DATA_DIR
    reason = str((payload or {}).get('reason') or 'api_invalidate')
    flag = DATA_DIR / '_runtime_cache_invalidate.flag'
    try:
        import json
        from datetime import datetime
        flag.write_text(
            json.dumps({'at': datetime.now().isoformat(), 'reason': reason}),
            encoding='utf-8',
        )
        return {'success': True, 'reason': reason}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_health_payload() -> dict:
    from backend.utils.market_hours import (
        classify_source_freshness,
        get_operational_status,
        get_watchdog_config,
        source_idle_message,
    )
    wd_cfg = get_watchdog_config()
    operational = get_operational_status()
    dynamic_stale_threshold = int(wd_cfg.get('stale_threshold_seconds') or STALE_THRESHOLD_SECONDS)
    period = str(operational.get('period') or 'market')

    files = {}
    try:
        from backend.runtime.feed_registry import HEALTH_FEED_FILES
        files = dict(HEALTH_FEED_FILES)
    except Exception:
        files = {
            "intelligence": "unified_intelligence.json",
            "scanner": "scanner_data.json",
            "govt": "govt_intelligence.json",
            "news": "news_feed.json",
            "reddit": "reddit_data.json",
            "markets": "global_markets.json",
            "india": "latest_market_data.json",
            "youtube": "tv_intelligence.json",
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
            status_name, _unhealthy = classify_source_freshness(age, dynamic_stale_threshold, period)
            source_status[key] = {
                "file": filename,
                "status": status_name,
                "age_seconds": age,
                "exists": filepath.exists(),
                "idle_message": source_idle_message(key, period) if status_name == 'idle' else None,
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

    try:
        from backend.utils.alert_routing import get_operational_alert_summary
        operational_alerts = get_operational_alert_summary(limit=15)
    except Exception:
        operational_alerts = {}

    try:
        from backend.ai.provider_manager import get_provider_ops_summary
        provider_ops = get_provider_ops_summary()
    except Exception:
        provider_ops = {}

    try:
        from backend.analytics.provider_analytics import get_runtime_ops_summary
        provider_analytics = get_runtime_ops_summary()
    except Exception:
        provider_analytics = {}

    try:
        from backend.orchestration.orchestrator_state import get_orchestrator_health_payload
        if IS_LOCAL_DEV:
            orchestrator = {
                'orchestrator_mode': 'LOCAL',
                'runtime_healthy': True,
                'local_dev': True,
                'components': {'scheduler': {'status': 'healthy'}, 'lifecycle': {}, 'exports': {}, 'gui_sync': {'validated': True}},
            }
        else:
            orchestrator = get_orchestrator_health_payload()
    except Exception as e:
        orchestrator = {'status': 'degraded', 'error': str(e)}

    return {
        "status": "ok" if orchestrator.get('runtime_healthy', True) else "degraded",
        "timestamp": datetime.now().isoformat(),
        "railway": IS_RAILWAY,
        "operational": operational,
        "db_path": str(DB_PATH),
        "data_freshness": freshness,
        "source_status": source_status,
        "running_jobs": lock_status(),
        "orchestrator": orchestrator,
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
        "operational_alerts": operational_alerts,
        "provider_ops": provider_ops,
        "provider_analytics": provider_analytics,
    }


def _wrap_runtime_snapshot_for_frontend(
    payload: dict,
    *,
    cache_path: Optional[Path] = None,
) -> dict:
    from backend.runtime.snapshot_contract import wrap_runtime_snapshot_for_frontend
    return wrap_runtime_snapshot_for_frontend(payload, cache_path=cache_path)


def _runtime_snapshot_warming_up_response() -> dict:
    """503 payload when data/cache/runtime_snapshot.json is not yet available."""
    ts = datetime.now().isoformat()
    return {
        'ok': False,
        'snapshot_id': 'warming_up',
        'generated_at': ts,
        'intelligence': {},
        'action_plan': '',
        'status': 'warming_up',
        'freshness': {'age_hours': None, 'stale': True, 'source': 'runtime_snapshot'},
        'data': {},
        'exports': {},
    }


@app.get("/api/runtime/snapshot", dependencies=[Depends(verify_api_key)])
def api_market_snapshot():
    """Canonical GUI snapshot — fast cache read, then live build fallback."""
    if not RUNTIME_SNAPSHOT_CACHE.is_file():
        return JSONResponse(
            status_code=503,
            content=_runtime_snapshot_warming_up_response(),
        )

    try:
        cached = _load_runtime_snapshot_cache()
        if cached:
            wrapped = _wrap_runtime_snapshot_for_frontend(
                cached,
                cache_path=RUNTIME_SNAPSHOT_CACHE,
            )
            return sanitize_json_value(wrapped)
    except Exception as exc:
        backend_log.warning('runtime snapshot cache read failed: %s', exc)

    from backend.runtime.global_job_locks import DEFAULT_TIMEOUT_SEC, run_with_timeout

    try:
        payload = run_with_timeout(
            _build_gui_snapshot,
            job='aggregation',
            timeout=DEFAULT_TIMEOUT_SEC,
            owner='api_runtime_snapshot',
        )
        _write_runtime_snapshot_cache(payload)
        wrapped = _wrap_runtime_snapshot_for_frontend(
            payload,
            cache_path=RUNTIME_SNAPSHOT_CACHE,
        )
        return sanitize_json_value(wrapped)
    except TimeoutError as exc:
        payload = _build_gui_snapshot_cached_fallback(str(exc))
        _write_runtime_snapshot_cache(payload)
        wrapped = _wrap_runtime_snapshot_for_frontend(
            payload,
            cache_path=RUNTIME_SNAPSHOT_CACHE,
        )
        return sanitize_json_value(wrapped)
    except Exception as exc:
        backend_log.error('runtime snapshot build failed: %s', exc)
        return JSONResponse(
            status_code=503,
            content={
                **_runtime_snapshot_warming_up_response(),
                'message': 'snapshot unavailable',
                'error': str(exc)[:200],
            },
        )


def _boot_runtime_snapshot_payload() -> dict:
    """Minimum GUI-shaped snapshot for cold start."""
    ts = datetime.now().isoformat()
    intel = {
        'summary': 'Boot snapshot',
        'executive_summary': 'Boot snapshot',
        'market_mood': {'global_mood': 'NEUTRAL', 'india_outlook': 'NEUTRAL', 'retail_mood': 'NEUTRAL'},
    }
    return {
        'snapshot_id': 'boot_snapshot',
        'generated_at': ts,
        'status': 'warming_up',
        'runtime_state': 'warming_up',
        'action_plan': '',
        'intelligence': intel,
        'market_snapshot': {
            'executive_summary': 'Boot snapshot',
            'action_plan': '',
            'sector_rotation': {'bullish': [], 'bearish': []},
            'top_opportunities': [],
            'risk_list': [],
            'runtime_state': 'warming_up',
            'intelligence': intel,
        },
        'exports': {
            'intelligence': intel,
        },
        'data': {
            'intelligence': intel,
        },
        'panels': {},
    }


def _load_runtime_snapshot_cache() -> Optional[dict]:
    """Read latest cached GUI snapshot JSON."""
    if not RUNTIME_SNAPSHOT_CACHE.is_file():
        return None
    payload = json.loads(RUNTIME_SNAPSHOT_CACHE.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        return None
    return payload


def _write_runtime_snapshot_cache(payload: dict) -> None:
    """Persist GUI snapshot payload for fast API reads."""
    if not isinstance(payload, dict):
        return
    try:
        RUNTIME_SNAPSHOT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_SNAPSHOT_CACHE.write_text(
            json.dumps(payload, indent=2, default=str) + '\n',
            encoding='utf-8',
        )
    except Exception as exc:
        backend_log.warning('runtime snapshot cache write failed: %s', exc)


def ensure_runtime_snapshot_cache() -> Path:
    """Create or refresh data/cache/runtime_snapshot.json for GUI hydration."""
    if RUNTIME_SNAPSHOT_CACHE.is_file():
        try:
            existing = _load_runtime_snapshot_cache()
            if existing and (existing.get('snapshot_id') or existing.get('generated_at')):
                return RUNTIME_SNAPSHOT_CACHE
        except Exception:
            pass

    payload = None
    try:
        payload = _build_gui_snapshot_cached_fallback('cache_seed')
    except Exception as exc:
        backend_log.warning('runtime snapshot cache seed fallback failed: %s', exc)

    if not payload or not isinstance(payload, dict):
        payload = _boot_runtime_snapshot_payload()
    elif CURRENT_SNAPSHOT_FILE.is_file():
        try:
            committed = json.loads(CURRENT_SNAPSHOT_FILE.read_text(encoding='utf-8'))
            if isinstance(committed, dict):
                payload.setdefault('snapshot_id', committed.get('snapshot_id'))
                payload.setdefault('generated_at', committed.get('generated_at'))
                ms = committed if committed.get('market_session') else committed
                if isinstance(ms, dict):
                    payload['market_snapshot'] = payload.get('market_snapshot') or ms
        except Exception:
            pass

    _write_runtime_snapshot_cache(payload)
    return RUNTIME_SNAPSHOT_CACHE


@app.get("/api/runtime_snapshot", dependencies=[Depends(verify_api_key)])
def api_runtime_snapshot():
    """Legacy alias — same payload as /api/runtime/snapshot."""
    return api_market_snapshot()


def _build_gui_snapshot_cached_fallback(reason: str = '') -> dict:
    """Return degraded cached snapshot so the GUI always receives a response."""
    warning = f'api_build_timeout: {reason[:120]}' if reason else 'api_build_timeout'
    cached = None
    try:
        from backend.runtime.global_job_locks import load_committed_snapshot_dict
        cached = load_committed_snapshot_dict()
    except Exception:
        pass

    try:
        payload = _build_runtime_snapshot()
    except Exception:
        payload = {
            'data': {},
            'panels': {},
            'generated_at': datetime.now().isoformat(),
        }

    ms_raw = cached or {}
    ms_dict = ms_raw.get('market_snapshot') if isinstance(ms_raw.get('market_snapshot'), dict) else ms_raw
    payload['market_snapshot'] = ms_dict or {}
    payload['snapshot_id'] = payload.get('snapshot_id') or ms_raw.get('snapshot_id')
    payload['status'] = 'degraded'
    warnings = list(payload.get('validation_warnings') or [])
    warnings.extend([warning, 'stale_cache_response'])
    payload['validation_warnings'] = warnings
    payload['exports'] = dict(payload.get('data') or {})
    payload.setdefault('generated_at', ms_raw.get('generated_at') or datetime.now().isoformat())
    return payload


def _build_gui_snapshot() -> dict:
    """Single synchronized payload for GUI/Telegram — built from MarketSnapshot."""
    from backend.runtime.market_snapshot_engine import (
        build_degraded_snapshot,
        get_current_market_snapshot,
        validate_market_snapshot,
    )

    try:
        ms = get_current_market_snapshot()
        ok, issues = validate_market_snapshot(ms)
        if not ok:
            ms = build_degraded_snapshot(issues)
    except Exception as exc:
        issues = [f'snapshot_build_error: {exc}']
        try:
            ms = build_degraded_snapshot(issues)
        except Exception:
            return {
                'status': 'degraded',
                'validation_warnings': issues,
                'generated_at': datetime.now().isoformat(),
                'data': {},
                'exports': {},
                'panels': {},
                'market_snapshot': {},
            }

    payload = _build_runtime_snapshot()
    ms_dict = ms.to_dict()
    payload['market_snapshot'] = ms_dict
    payload['snapshot_id'] = ms.snapshot_id
    payload['primary_state'] = (ms.runtime_state or {}).get('primary_state')
    payload['blockers'] = ms.blockers
    payload['pipeline_health'] = ms.pipeline_health
    payload['action_plan'] = ms.action_plan or (ms.intelligence or {}).get('action_plan') or ''
    payload['exports'] = dict(payload.get('data') or {})
    ms_metrics = ms.metrics or {}
    sections = ms_metrics.get('sections') or {}
    payload['calibration_summary'] = {
        'evaluated': ms_metrics.get('evaluated'),
        'pending': ms_metrics.get('pending'),
        'wins': ms_metrics.get('wins'),
        'losses': ms_metrics.get('losses'),
        'partials': ms_metrics.get('partials'),
        'resolved': ms_metrics.get('resolved'),
        'expired': ms_metrics.get('expired'),
        'neutralized': ms_metrics.get('neutralized'),
        'win_rate': ms_metrics.get('win_rate'),
        'win_rate_display': ms_metrics.get('win_rate_display'),
        'statistically_confident': ms_metrics.get('statistically_confident'),
        'source': ms_metrics.get('source'),
        'metric_sections': sections,
        'live_session': sections.get('live_session') or {},
        'historical_calibration': sections.get('historical_calibration') or {},
        'archived': sections.get('archived') or {},
    }
    ok, issues = validate_market_snapshot(ms)
    payload['status'] = 'ok' if ok and not (ms.freshness or {}).get('degraded') else 'degraded'
    payload['validation_warnings'] = issues
    if not payload.get('action_plan'):
        payload.setdefault('validation_warnings', []).append('missing action_plan')
    return payload


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
def get_youtube():
    return load_tv_intelligence()


@app.get("/api/debug/tv-intelligence", dependencies=[Depends(verify_api_key)])
def get_debug_tv_intelligence():
    return load_tv_intelligence()

@app.get("/api/inshorts", dependencies=[Depends(verify_api_key)])
def get_inshorts(): return load_json_file("inshorts_feed.json")

@app.get("/api/stats", dependencies=[Depends(verify_api_key)])
def get_stats(): return load_json_file("stats_data.json")

@app.get("/api/history", dependencies=[Depends(verify_api_key)])
def get_history(): return load_json_file("history_data.json")


@app.get("/api/theme-baskets", dependencies=[Depends(verify_api_key)])
def api_theme_baskets_list():
    from backend.analytics.theme_baskets import list_all_baskets, load_theme_baskets

    data = load_theme_baskets()
    return sanitize_json_value({
        'ok': True,
        'stage': data.get('stage', '47E'),
        'generated_at': data.get('generated_at'),
        'cache_refreshed_at': data.get('cache_refreshed_at'),
        'baskets': list_all_baskets(),
        'count': len(list_all_baskets()),
    })


@app.get("/api/theme-baskets/{theme_id}", dependencies=[Depends(verify_api_key)])
def api_theme_basket_detail(theme_id: str):
    from backend.analytics.theme_baskets import get_basket_by_id, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    basket = get_basket_by_id(theme_id)
    if not basket:
        raise HTTPException(status_code=404, detail=f"Theme not found: {theme_id}")
    return sanitize_json_value({'ok': True, 'theme_id': resolved, 'basket': basket})


@app.get("/api/theme-baskets/{theme_id}/news", dependencies=[Depends(verify_api_key)])
def api_theme_basket_news(theme_id: str):
    from backend.analytics.theme_baskets import get_basket_by_id, get_theme_catalysts, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    if not get_basket_by_id(theme_id):
        raise HTTPException(status_code=404, detail=f"Theme not found: {theme_id}")
    catalysts = get_theme_catalysts(theme_id, limit=12)
    return sanitize_json_value({
        'ok': True,
        'theme_id': resolved,
        'catalysts': catalysts,
        'count': len(catalysts),
    })


@app.get("/api/theme-baskets/{theme_id}/scan", dependencies=[Depends(verify_api_key)])
def api_theme_basket_scan(theme_id: str):
    from backend.analytics.theme_baskets import get_basket_by_id, rank_theme_stocks, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    if not get_basket_by_id(theme_id):
        raise HTTPException(status_code=404, detail=f"Theme not found: {theme_id}")
    ranked = rank_theme_stocks(theme_id, limit=12)
    return sanitize_json_value({
        'ok': True,
        'theme_id': resolved,
        'stocks': ranked,
        'count': len(ranked),
    })


@app.post("/api/theme-baskets/{theme_id}/add", dependencies=[Depends(verify_api_key)])
def api_theme_basket_add(theme_id: str, payload: dict = Body(default={})):
    from backend.analytics.theme_baskets import add_stock_to_basket

    ticker = str(payload.get('ticker') or '').strip()
    bucket = str(payload.get('bucket') or payload.get('type') or 'direct').strip()
    result = add_stock_to_basket(theme_id, ticker, bucket)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error', 'add failed'))
    return sanitize_json_value(result)


@app.post("/api/theme-baskets/{theme_id}/remove", dependencies=[Depends(verify_api_key)])
def api_theme_basket_remove(theme_id: str, payload: dict = Body(default={})):
    from backend.analytics.theme_baskets import remove_stock_from_basket

    ticker = str(payload.get('ticker') or '').strip()
    result = remove_stock_from_basket(theme_id, ticker)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error', 'remove failed'))
    return sanitize_json_value(result)


@app.post("/api/theme-baskets/refresh", dependencies=[Depends(verify_api_key)])
def api_theme_baskets_refresh():
    from backend.analytics.theme_baskets import refresh_theme_catalyst_cache

    result = refresh_theme_catalyst_cache(persist=True)
    return sanitize_json_value(result)


@app.get("/api/all", dependencies=[Depends(verify_api_key)])
def get_all():
    snap = _build_runtime_snapshot()
    data = snap.get('data') or {}
    return {
        **data,
        "fetched_at": snap.get('generated_at'),
        "runtime": {
            "generated_at": snap.get('generated_at'),
            "panels": snap.get('panels'),
        },
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
    try:
        from backend.ai.ask_context_builder import build_ask_prompt
        prompt = build_ask_prompt(question)
    except Exception:
        context = ""
        if intel.get("analysis"):
            context = "Latest intelligence:\n" + intel["analysis"][:2000]
        prompt = f"""You are an Indian stock market expert.

Context:
{context}

Question: {question}

Answer in 4-6 lines for Indian retail investor."""
    try:
        result = ask_ai(prompt, use_case=use_case, max_tokens=600, channel='api')
        if result.get('success'):
            return {
                "success": True,
                "response": result.get('text', ''),
                "model": result.get('model', ''),
                "provider": result.get('provider', ''),
                "cost": result.get('estimated_cost', 0)
            }
        else:
            friendly = result.get('user_message') or ''
            return {
                "success": False,
                "error": result.get('error', 'Unknown error'),
                "user_message": friendly or (
                    "⚠ AI enrichment temporarily unavailable. "
                    "Core intelligence systems remain operational."
                ),
            }
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

@app.get("/api/debug/market-memory", dependencies=[Depends(verify_api_key)])
def api_debug_market_memory():
    """Read-only visibility into canonical_market_memory.db."""
    try:
        from backend.storage.market_memory_db import get_connection, get_market_memory_stats

        stats = get_market_memory_stats()
        latest_predictions: list[dict] = []
        latest_context: list[dict] = []

        if stats.get('db_exists'):
            conn = get_connection()
            try:
                pred_rows = conn.execute(
                    """
                    SELECT prediction_id, ticker, timestamp, source, direction, confidence
                    FROM predictions
                    ORDER BY timestamp DESC
                    LIMIT 5
                    """
                ).fetchall()
                latest_predictions = [
                    {
                        'prediction_id': row['prediction_id'],
                        'ticker': row['ticker'],
                        'timestamp': row['timestamp'],
                        'source': row['source'],
                        'direction': row['direction'],
                        'confidence': row['confidence'],
                    }
                    for row in pred_rows
                ]

                ctx_rows = conn.execute(
                    """
                    SELECT context_id, timestamp, market_regime, vix, crude
                    FROM market_context_snapshots
                    ORDER BY timestamp DESC
                    LIMIT 5
                    """
                ).fetchall()
                latest_context = [
                    {
                        'context_id': row['context_id'],
                        'timestamp': row['timestamp'],
                        'market_regime': row['market_regime'],
                        'vix': row['vix'],
                        'crude': row['crude'],
                    }
                    for row in ctx_rows
                ]
            finally:
                conn.close()

        return sanitize_json_value({
            'ok': True,
            'stats': stats,
            'latest_predictions': latest_predictions,
            'latest_context': latest_context,
        })
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get("/api/debug/market-memory/learning", dependencies=[Depends(verify_api_key)])
def api_debug_market_memory_learning(
    limit_days: int | None = Query(None),
):
    """Read-only learning summary from canonical_market_memory.db."""
    try:
        from backend.analytics.market_memory_learning import get_learning_summary

        summary = get_learning_summary(limit_days=limit_days)
        return sanitize_json_value(summary)
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get("/api/debug/market-memory/advisor", dependencies=[Depends(verify_api_key)])
def api_debug_market_memory_advisor(
    ticker: str = Query(...),
    signal_type: str | None = Query(None),
    confidence_label: str | None = Query(None),
    horizon: str | None = Query(None),
):
    """Read-only shadow learning advisor for a prediction candidate."""
    try:
        from backend.analytics.market_memory_advisor import advise_prediction

        candidate: dict = {'ticker': ticker}
        if signal_type:
            candidate['signal_type'] = signal_type
        if confidence_label:
            candidate['confidence_label'] = confidence_label
        if horizon:
            candidate['prediction_horizon'] = horizon

        advice = advise_prediction(candidate)
        return sanitize_json_value({'ok': True, **advice})
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get("/api/debug/market-memory/advisor-batch", dependencies=[Depends(verify_api_key)])
def api_debug_market_memory_advisor_batch(
    limit: int = Query(50),
    advice: str | None = Query(None),
    ticker: str | None = Query(None),
):
    """Read-only batch shadow advisor report for unresolved predictions."""
    try:
        from backend.analytics.market_memory_advisor import get_advisor_batch_report

        report = get_advisor_batch_report(
            limit=limit,
            advice=advice,
            ticker=ticker,
        )
        return sanitize_json_value(report)
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get("/api/debug/market-memory/dashboard", dependencies=[Depends(verify_api_key)])
def api_debug_market_memory_dashboard(
    limit: int = Query(50),
    price_file: str | None = Query(None),
):
    """Unified read-only market memory dashboard payload."""
    try:
        from backend.analytics.market_memory_dashboard import get_market_memory_dashboard

        dashboard = get_market_memory_dashboard(
            limit=limit,
            price_file=price_file,
        )
        return sanitize_json_value(dashboard)
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get("/api/debug/historical-learning", dependencies=[Depends(verify_api_key)])
def api_debug_historical_learning(
    ticker: str | None = Query(None),
):
    """Read-only historical learning summary from historical_market_memory.db."""
    try:
        from backend.analytics.historical_learning_engine import (
            compare_live_memory_vs_historical,
            get_historical_learning_summary,
            get_historical_ticker_performance,
        )

        if ticker:
            payload = get_historical_ticker_performance(ticker)
            return sanitize_json_value(payload)

        summary = get_historical_learning_summary()
        comparison = compare_live_memory_vs_historical()
        return sanitize_json_value({
            'ok': True,
            'stats': summary.get('stats'),
            'overall': summary.get('overall'),
            'top_tickers': summary.get('top_tickers'),
            'bottom_tickers': summary.get('bottom_tickers'),
            'source_performance': summary.get('source_performance'),
            'sample_prices': summary.get('sample_prices'),
            'price_row_count': summary.get('price_row_count'),
            'historical_ticker_count': summary.get('historical_ticker_count'),
            'universe_ticker_count': summary.get('universe_ticker_count'),
            'import_report': summary.get('import_report'),
            'replay_report': summary.get('replay_report'),
            'import_progress': summary.get('import_progress'),
            'quality_anomalies': summary.get('quality_anomalies'),
            'quality_audit': summary.get('quality_audit'),
            'simulation': summary.get('simulation'),
            'comparison': comparison,
        })
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get("/api/debug/broker-consensus", dependencies=[Depends(verify_api_key)])
def api_debug_broker_consensus(
    ticker: str = Query(...),
    timeframe: str | None = Query(None),
):
    """Read-only broker/source consensus for a ticker from canonical_market_memory.db."""
    normalized_ticker = str(ticker).strip().upper()
    try:
        from backend.analytics.broker_consensus_engine import get_consensus_for_ticker

        consensus = get_consensus_for_ticker(normalized_ticker, timeframe=timeframe)
        return sanitize_json_value({
            'ok': True,
            'ticker': normalized_ticker,
            'timeframe': timeframe,
            'consensus': consensus,
        })
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/broker-intelligence", dependencies=[Depends(verify_api_key)])
def api_debug_broker_intelligence(
    ticker: str | None = Query(None),
    source: str | None = Query(None),
):
    """Read-only broker prediction intelligence (external evidence, not our predictions)."""
    try:
        from backend.analytics.broker_prediction_intelligence import (
            get_broker_intelligence_dashboard,
            get_source_intelligence,
            get_ticker_intelligence,
        )

        if ticker:
            payload = get_ticker_intelligence(ticker)
        elif source:
            payload = get_source_intelligence(source)
        else:
            payload = get_broker_intelligence_dashboard()
        return sanitize_json_value(payload)
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/broker-intelligence/source", dependencies=[Depends(verify_api_key)])
def api_debug_broker_intelligence_source(
    source: str = Query(...),
):
    """Read-only broker intelligence for a single external source."""
    try:
        from backend.analytics.broker_prediction_intelligence import get_source_intelligence

        payload = get_source_intelligence(source)
        return sanitize_json_value(payload)
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/our-vs-broker", dependencies=[Depends(verify_api_key)])
def api_debug_our_vs_broker(
    ticker: str | None = Query(None),
    limit: int = Query(200),
):
    """Read-only comparison of our predictions vs broker picks."""
    try:
        from backend.analytics.broker_prediction_intelligence import (
            compare_our_predictions_vs_brokers,
        )

        report = compare_our_predictions_vs_brokers(ticker=ticker, limit=limit)
        return sanitize_json_value(report)
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/broker-app-collector", dependencies=[Depends(verify_api_key)])
def api_debug_broker_app_collector():
    """Read-only latest broker/app collector cache."""
    try:
        from backend.collectors.broker_app_collector import get_broker_app_collector_dashboard

        return sanitize_json_value(get_broker_app_collector_dashboard())
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/external-source-coverage", dependencies=[Depends(verify_api_key)])
def api_debug_external_source_coverage():
    """Read-only external source coverage from broker/app collector cache."""
    try:
        from backend.collectors.broker_app_collector import get_external_source_coverage

        return sanitize_json_value(get_external_source_coverage())
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE — cached JSON only, no live scoring.


@app.get("/api/debug/final-confidence", dependencies=[Depends(verify_api_key)])
def api_debug_final_confidence(
    ticker: str | None = Query(None),
    limit: int = Query(50),
):
    """Read-only final confidence from cached report (shadow scoring only)."""
    from backend.analytics.final_confidence_report_loader import (
        load_cached_final_confidence_report,
        load_cached_final_confidence_ticker_breakdown,
    )

    try:
        if ticker:
            return sanitize_json_value(load_cached_final_confidence_ticker_breakdown(ticker, limit=max(limit, 500)))
        return sanitize_json_value(load_cached_final_confidence_report(limit=limit))
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/final-confidence/report", dependencies=[Depends(verify_api_key)])
def api_debug_final_confidence_report(
    limit: int = Query(50),
):
    """Read-only final confidence dashboard report from cached JSON."""
    from backend.analytics.final_confidence_report_loader import load_cached_final_confidence_report

    try:
        return sanitize_json_value(load_cached_final_confidence_report(limit=limit))
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/confidence-calibration", dependencies=[Depends(verify_api_key)])
def api_debug_confidence_calibration():
    """Read-only confidence calibration dashboard (analysis only, no trade execution)."""
    try:
        from backend.analytics.confidence_calibration_engine import get_calibration_dashboard

        return sanitize_json_value(get_calibration_dashboard())
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/tomorrow-watchlist", dependencies=[Depends(verify_api_key)])
def api_debug_tomorrow_watchlist(
    limit: int = Query(25),
):
    """Read-only tomorrow watchlist from final confidence (shadow only, no trade execution)."""
    try:
        from backend.analytics.tomorrow_watchlist_report import get_top_watchlist_dashboard

        return sanitize_json_value(get_top_watchlist_dashboard(limit=limit))
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE — cached confluence only, no trade execution.


@app.get("/api/debug/stock-decision", dependencies=[Depends(verify_api_key)])
def api_debug_stock_decision(
    mode: str = Query('today'),
):
    """Read-only stock confluence decision from cached reports (shadow only)."""
    try:
        from backend.analytics.stock_decision_engine import build_stock_decision

        return sanitize_json_value(build_stock_decision(mode=mode))
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/daily-report-pack", dependencies=[Depends(verify_api_key)])
def api_debug_daily_report_pack(
    limit: int = Query(25),
):
    """Read-only daily report pack (shadow analysis only, no trade execution)."""
    try:
        from backend.analytics.daily_report_pack import get_latest_daily_report_pack

        return sanitize_json_value(get_latest_daily_report_pack())
    except Exception as e:
        return {'ok': False, 'error': str(e)}


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


@app.get("/api/debug/providers", dependencies=[Depends(verify_api_key)])
def api_debug_providers():
    from backend.ai.provider_manager import get_provider_ops_summary, get_provider_debug_registry
    from backend.analytics.provider_analytics import get_runtime_ops_summary
    return sanitize_json_value({
        **get_provider_ops_summary(),
        'debug_registry': get_provider_debug_registry(),
        'runtime_analytics': get_runtime_ops_summary(),
    })


@app.get("/api/debug/provider-analytics", dependencies=[Depends(verify_api_key)])
def api_debug_provider_analytics():
    from backend.analytics.provider_analytics import get_runtime_ops_summary, get_ai_runtime_stats_payload
    return sanitize_json_value({
        'ops': get_runtime_ops_summary(),
        'stats': get_ai_runtime_stats_payload(),
    })


@app.get("/api/active-predictions", dependencies=[Depends(verify_api_key)])
def api_active_predictions():
    from backend.lifecycle.prediction_lifecycle_engine import get_active_predictions_payload
    return sanitize_json_value(get_active_predictions_payload())


@app.get("/api/debug/lifecycle", dependencies=[Depends(verify_api_key)])
def api_debug_lifecycle():
    from backend.lifecycle.prediction_lifecycle_engine import get_lifecycle_ops_payload, get_ml_core_status
    return sanitize_json_value({
        'lifecycle': get_lifecycle_ops_payload(),
        'ml_core': get_ml_core_status(),
    })


@app.get("/api/debug/adaptive-calibration", dependencies=[Depends(verify_api_key)])
def api_debug_adaptive_calibration():
    from backend.adaptive.adaptive_calibration_engine import (
        get_adaptive_dashboard_payload,
        get_adaptive_ops_payload,
        load_adaptive_state,
    )
    return sanitize_json_value({
        'dashboard': get_adaptive_dashboard_payload(),
        'ops': get_adaptive_ops_payload(),
        'state': load_adaptive_state(),
    })


@app.post("/api/adaptive/reset", dependencies=[Depends(verify_api_key)])
def api_adaptive_reset():
    from backend.adaptive.adaptive_calibration_engine import reset_adaptive_baseline
    state = reset_adaptive_baseline(reason='operator_api_reset')
    return sanitize_json_value({'status': 'ok', 'message': 'Adaptive baseline restored.', 'state': state})


@app.get("/api/debug/reliability", dependencies=[Depends(verify_api_key)])
def api_debug_reliability():
    from backend.metrics.execution_metrics import get_reliability_debug
    return _safe_debug_response('reliability', get_reliability_debug)


@app.get("/api/debug/calibration", dependencies=[Depends(verify_api_key)])
def api_debug_calibration():
    from backend.analytics.signal_outcomes import get_ops_calibration_payload
    return _safe_debug_response('calibration', get_ops_calibration_payload)


@app.get("/api/debug/source-feed", dependencies=[Depends(verify_api_key)])
def api_debug_source_feed(source: str = 'ET', limit: int = 100):
    """Cached internal source feed for GUI Source Feed Viewer (Stage 44G)."""
    try:
        from backend.analytics.source_feed_viewer import get_source_feed

        return sanitize_json_value(get_source_feed(source=source, limit=limit))
    except Exception as e:
        return {'ok': False, 'error': str(e), 'source': source, 'items': []}


@app.get("/api/debug/source-freshness", dependencies=[Depends(verify_api_key)])
def api_debug_source_freshness():
    """Read-only source freshness / health report for GUI and CLI."""
    try:
        from backend.analytics.source_freshness import get_source_freshness_report

        return sanitize_json_value(get_source_freshness_report())
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/market-router", dependencies=[Depends(verify_api_key)])
def api_debug_market_router():
    """Read-only India/USA session router for GUI and CLI."""
    try:
        from backend.analytics.market_calendar_router import get_market_router_payload

        return sanitize_json_value(get_market_router_payload())
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/aihub-tab-freshness", dependencies=[Depends(verify_api_key)])
def api_debug_aihub_tab_freshness():
    """Per-tab AI Hub freshness from real local source files."""
    try:
        from backend.analytics.aihub_tab_freshness import get_aihub_tab_freshness_report

        return sanitize_json_value(get_aihub_tab_freshness_report())
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get("/api/debug/aihub-tab/{tab}", dependencies=[Depends(verify_api_key)])
def api_debug_aihub_tab(tab: str, refresh: int = Query(0), force: int = Query(0)):
    """Aggregated AI Hub tab payload (Stage 44AQ) — one response per tab."""
    try:
        from backend.analytics.aihub_tab_payloads import build_aihub_tab_payload

        return sanitize_json_value(
            build_aihub_tab_payload(tab, force_refresh=bool(force or refresh)),
        )
    except Exception as e:
        return sanitize_json_value({
            'ok': False,
            'tab': tab,
            'error': str(e),
            'items': [],
            'summary': {},
            'warnings': ['api_error'],
        })


@app.post("/api/debug/refresh-local-intelligence", dependencies=[Depends(verify_api_key)])
def api_debug_refresh_local_intelligence(payload: dict = Body(default={})):
    """Run safe local collector refresh (no Telegram, no outcomes). Local-only."""
    if not (LOCAL_ONLY or IS_LOCAL_DEV):
        return sanitize_json_value({
            'ok': False,
            'error': 'refresh-local-intelligence is local-only (set LOCAL_ONLY=1 or LOCAL_DEV_MODE=1)',
            'scope': (payload or {}).get('scope'),
            'runtime': 'skipped',
            'news': 'skipped',
            'prices': 'skipped',
            'memory': 'skipped',
            'warnings': ['local_only_required'],
        })
    body = payload or {}
    scope = body.get('scope')
    try:
        if scope is not None:
            from scripts.refresh_local_intelligence import run_refresh_scoped

            dry_run = bool(body.get('dry_run', False))
            result = run_refresh_scoped(str(scope), dry_run=dry_run)
            if isinstance(result, dict):
                result.setdefault('dry_run', dry_run)
            return sanitize_json_value(result)
        from scripts.refresh_local_intelligence import run_refresh

        dry_run = bool(body.get('dry_run', False))
        results = run_refresh(
            dry_run=dry_run,
            news=bool(body.get('news')),
            global_markets=bool(body.get('global')),
            prices=bool(body.get('prices')),
            memory=bool(body.get('memory')),
            run_all=bool(body.get('all', True)),
        )
        return sanitize_json_value({
            'ok': True,
            'scope': 'all' if body.get('all', True) else 'legacy',
            'dry_run': dry_run,
            'runtime': results.get('global', 'skipped'),
            'news': results.get('news', 'skipped'),
            'prices': results.get('prices', 'skipped'),
            'memory': results.get('memory', 'skipped'),
            'results': results,
            'warnings': [],
        })
    except Exception as e:
        return {'ok': False, 'error': str(e), 'scope': scope}


@app.get("/api/daily-review", dependencies=[Depends(verify_api_key)])
def api_daily_review(
    date: Optional[str] = Query(None),
    rebuild: bool = Query(False),
):
    from backend.analytics.daily_review_engine import get_daily_review
    review = get_daily_review(date, rebuild=rebuild)
    return sanitize_json_value(review)


@app.get("/api/calibration", dependencies=[Depends(verify_api_key)])
def api_calibration():
    from backend.analytics.regime_analytics import build_calibration_dashboard
    return sanitize_json_value(build_calibration_dashboard())


@app.get("/api/journal", dependencies=[Depends(verify_api_key)])
def api_journal(limit: int = Query(21, ge=1, le=60)):
    from backend.analytics.daily_journal_engine import build_intelligence_journal
    return sanitize_json_value(build_intelligence_journal(limit=limit, persist_index=False))


@app.api_route('/api/{full_path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def api_not_found(full_path: str):
    """JSON 404 for unknown API routes — avoids HTML responses to GUI clients."""
    return JSONResponse(
        status_code=404,
        content={
            'ok': False,
            'error': 'not_found',
            'path': f'/api/{full_path}',
        },
    )


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
    try:
        from backend.ai.provider_manager import log_provider_startup_diagnostics
        log_provider_startup_diagnostics(force=True)
    except Exception as e:
        print(f"[AI PROVIDERS] WARN diagnostics failed: {e}")
    print("=" * 60)
    backend_log.info("Uvicorn starting host=%s port=%s railway=%s", host, port, IS_RAILWAY)
    try:
        cache_path = ensure_runtime_snapshot_cache()
        print(f"Runtime snapshot cache: {cache_path}")
    except Exception as exc:
        print(f"[WARN] runtime snapshot cache init failed: {exc}")
    try:
        from backend.orchestration.recovery_loop import enforce_single_worker_mode
        enforce_single_worker_mode()
    except Exception:
        pass
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()