"""
Local dev runtime — deterministic single-process stabilization.

Set LOCAL_DEV_MODE=1 to bypass cloud singleton/recovery complexity.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from backend.utils.config import (
    API_HOST,
    API_PORT,
    CONFIG_DIR,
    DATA_DIR,
    IS_LOCAL_DEV,
    LOCAL_FORCE_EOD,
    PROJECT_ROOT,
    ensure_dirs,
    get_env,
    load_env,
)

_VALIDATION_STARTED = False
_VALIDATION_LOCK = threading.Lock()


def local_log(tag: str, message: str) -> None:
    print(f"[{tag}] {message}", flush=True)


def is_local_dev() -> bool:
    return IS_LOCAL_DEV or os.environ.get('LOCAL_DEV_MODE', '').strip() in ('1', 'true', 'yes')


def prepare_local_env() -> None:
    """Apply deterministic local defaults before backend boot."""
    os.environ.setdefault('LOCAL_DEV_MODE', '1')
    os.environ.setdefault('HOST', '127.0.0.1')
    os.environ.setdefault('PORT', '8080')
    os.environ.setdefault('API_BASE_URL', 'http://127.0.0.1:8080')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('TZ', 'Asia/Kolkata')
    load_env()
    ensure_dirs()
    local_log('LOCAL RUNTIME', f'data={DATA_DIR}')
    local_log('LOCAL RUNTIME', f'API http://127.0.0.1:{API_PORT}')


def free_port(port: int) -> None:
    """Terminate listeners on port to avoid duplicate local runtimes."""
    if sys.platform == 'win32':
        try:
            out = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            pids = set()
            needle = f':{port}'
            for line in (out.stdout or '').splitlines():
                if 'LISTENING' not in line or needle not in line:
                    continue
                parts = line.split()
                if parts:
                    pids.add(parts[-1])
            my_pid = str(os.getpid())
            for pid in pids:
                if pid == my_pid or pid == '0':
                    continue
                local_log('RESTART', f'freeing port {port} — terminating PID {pid}')
                subprocess.run(
                    ['taskkill', '/F', '/PID', pid],
                    capture_output=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
        except Exception as e:
            local_log('AUTOFIX', f'port cleanup warning: {e}')
    else:
        try:
            subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
        except Exception:
            pass


def _api_headers() -> Dict[str, str]:
    key = get_env('API_KEY')
    headers = {'Accept': 'application/json'}
    if key:
        headers['X-API-Key'] = key
    return headers


def fetch_json(path: str, timeout: int = 30) -> Dict[str, Any]:
    base = get_env('API_BASE_URL') or f'http://127.0.0.1:{API_PORT}'
    url = base.rstrip('/') + path
    req = urllib.request.Request(url, headers=_api_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def verify_api_endpoints() -> Dict[str, Any]:
    """Hit core API routes and summarize health."""
    results: Dict[str, Any] = {'ok': True, 'endpoints': {}}
    paths = [
        '/api/health',
        '/api/all',
        '/api/runtime/snapshot',
        '/api/debug/lifecycle',
        '/api/debug/providers',
    ]
    for path in paths:
        try:
            data = fetch_json(path)
            status = data.get('status', 'ok')
            results['endpoints'][path] = {'ok': True, 'status': status}
            local_log('API VERIFY', f'{path} -> {status}')
        except Exception as e:
            results['ok'] = False
            results['endpoints'][path] = {'ok': False, 'error': str(e)}
            local_log('API VERIFY', f'{path} FAILED: {e}')
    return results


def verify_gui_payload(snapshot: Optional[dict] = None) -> Dict[str, Any]:
    """Validate runtime snapshot panels used by the GUI."""
    if snapshot is None:
        try:
            snapshot = fetch_json('/api/runtime/snapshot')
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    panels = snapshot.get('panels') or {}
    data = snapshot.get('data') or {}
    checks = {
        'brain': bool(data.get('intelligence') and not (data.get('intelligence') or {}).get('error')),
        'calib': bool(data.get('stats') and not (data.get('stats') or {}).get('error')),
        'journal': bool(data.get('history') and not (data.get('history') or {}).get('error')),
        'lifecycle': (panels.get('lifecycle') or {}).get('pipeline_status') == 'COMPLETE',
        'ops': (panels.get('ops') or {}).get('status') in ('ready', 'collecting'),
    }
    ok = all(checks.values())
    for name, passed in checks.items():
        local_log('GUI VERIFY', f'{name}: {"OK" if passed else "EMPTY/STALE"}')
    return {'ok': ok, 'checks': checks, 'panels': panels}


def verify_lifecycle() -> Dict[str, Any]:
    try:
        payload = fetch_json('/api/debug/lifecycle')
        lc = payload.get('lifecycle') if isinstance(payload.get('lifecycle'), dict) else payload
        status = lc.get('pipeline_status') or lc.get('status')
        complete = status == 'COMPLETE' or lc.get('evaluation_cycle_complete')
        local_log('LIFECYCLE VERIFY', f'pipeline_status={status} complete={complete}')
        return {'ok': bool(complete), 'lifecycle': lc}
    except Exception as e:
        local_log('LIFECYCLE VERIFY', f'FAILED: {e}')
        return {'ok': False, 'error': str(e)}


def verify_opportunities(limit: int = 20) -> Dict[str, Any]:
    try:
        from backend.orchestration.opportunity_filter import rank_opportunities, DEFAULT_OPPS_LIMIT
        opps = rank_opportunities(limit=DEFAULT_OPPS_LIMIT)
        ok = len(opps) <= limit
        local_log('API VERIFY', f'/opps ranked count={len(opps)} (max {limit})')
        return {'ok': ok, 'count': len(opps), 'limit': limit}
    except Exception as e:
        local_log('API VERIFY', f'opps verify failed: {e}')
        return {'ok': False, 'error': str(e)}


def run_local_validation_loop(*, max_rounds: int = 30, interval: int = 20) -> None:
    """Background autonomous verify loop until stable or max rounds."""
    global _VALIDATION_STARTED
    with _VALIDATION_LOCK:
        if _VALIDATION_STARTED:
            return
        _VALIDATION_STARTED = True

    def _loop():
        time.sleep(12)
        for round_num in range(1, max_rounds + 1):
            local_log('LOCAL RUNTIME', f'validation round {round_num}/{max_rounds}')
            api = verify_api_endpoints()
            lc = verify_lifecycle()
            opps = verify_opportunities()
            snap = None
            try:
                snap = fetch_json('/api/runtime/snapshot')
            except Exception:
                pass
            gui = verify_gui_payload(snap)

            stable = api.get('ok') and gui.get('ok') and lc.get('ok') and opps.get('ok')
            if stable:
                local_log('LOCAL RUNTIME', 'ALL CHECKS PASSED — local runtime stable')
                local_log('LOCAL RUNTIME', 'Run npm start in VS Code now.')
                return

            if not lc.get('ok') and LOCAL_FORCE_EOD and round_num == 1:
                local_log('LOCAL EOD', 'lifecycle incomplete — EOD should be running from startup hook')

            time.sleep(interval)

        local_log('LOCAL RUNTIME', 'validation finished with warnings — inspect logs above')

    threading.Thread(target=_loop, daemon=True, name='LocalValidation').start()


def schedule_local_force_eod(delay_seconds: int = 25) -> None:
    if not LOCAL_FORCE_EOD:
        return

    def _run():
        time.sleep(delay_seconds)
        local_log('LOCAL EOD', 'LOCAL_FORCE_EOD=1 — running post-market lifecycle (force=True)')
        try:
            from backend.lifecycle.prediction_lifecycle_engine import run_end_of_day_cycle
            result = run_end_of_day_cycle(force=True)
            local_log('LOCAL EOD', f'complete status={result.get("status")}')
        except Exception as e:
            local_log('AUTOFIX', f'EOD failed: {e}')

    threading.Thread(target=_run, daemon=True, name='LocalForceEOD').start()
