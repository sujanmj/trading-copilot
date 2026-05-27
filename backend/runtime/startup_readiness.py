"""
Startup readiness lifecycle — validates subsystem health before announcing online.

Does NOT run pipelines, scanner, or synthesis. Read-only checks only.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

STARTUP_BOOTING = 'BOOTING'
STARTUP_INITIALIZING = 'INITIALIZING'
STARTUP_WARMING = 'WARMING_PIPELINES'
STARTUP_READY = 'READY'
STARTUP_DEGRADED = 'DEGRADED'

_STATE = STARTUP_BOOTING
_STARTED_AT = time.time()


def get_startup_state() -> str:
    return _STATE


def set_startup_state(state: str) -> None:
    global _STATE
    _STATE = state


def _check(name: str, ok: bool, detail: str = '') -> dict:
    return {'name': name, 'ok': ok, 'detail': detail}


def evaluate_startup_readiness() -> Tuple[str, List[dict], Dict[str, Any]]:
    """
    Centralized readiness validation (read-only).

    Returns (final_state, checks, summary).
    """
    from backend.utils.config import CURRENT_SNAPSHOT_FILE, DATA_DIR

    checks: List[dict] = []
    issues: List[str] = []

    # Scheduler heartbeat (file-based, no pipeline trigger)
    sched_ok = False
    sched_detail = 'unknown'
    try:
        from backend.runtime.runtime_state import build_runtime_state
        rs = build_runtime_state(force_refresh=False)
        sched = rs.get('scheduler') or {}
        sched_ok = sched.get('healthy') is True or sched.get('phase') not in (None, 'unknown', 'stale')
        sched_detail = str(sched.get('phase') or sched.get('display') or 'unknown')
        if not sched_ok and sched.get('phase') == 'RUNNING':
            sched_ok = True
    except Exception as exc:
        sched_detail = f'error: {exc}'
    checks.append(_check('scheduler', sched_ok, sched_detail))
    if not sched_ok:
        issues.append('scheduler')

    # Scanner health (from runtime state, not live scan)
    scanner_ok = False
    scanner_detail = 'unknown'
    try:
        from backend.runtime.runtime_state import build_runtime_state
        rs = build_runtime_state(force_refresh=False)
        scanner = rs.get('scanner_health') or {}
        scanner_ok = scanner.get('healthy') is True or bool(scanner.get('display'))
        scanner_detail = str(scanner.get('display') or scanner.get('status') or 'unknown')
        if scanner.get('stalled'):
            scanner_ok = False
            issues.append('scanner_stalled')
    except Exception as exc:
        scanner_detail = f'error: {exc}'
    checks.append(_check('scanner', scanner_ok, scanner_detail))
    if not scanner_ok:
        issues.append('scanner')

    # Snapshot committed
    snap_ok = CURRENT_SNAPSHOT_FILE.is_file()
    snap_detail = 'missing'
    snap_stale = False
    if snap_ok:
        try:
            age_min = (time.time() - CURRENT_SNAPSHOT_FILE.stat().st_mtime) / 60.0
            snap_detail = f'{age_min:.0f}m old'
            snap_stale = age_min > 15
            data = json.loads(CURRENT_SNAPSHOT_FILE.read_text(encoding='utf-8'))
            if not data.get('snapshot_id') and not data.get('generated_at'):
                snap_ok = False
                snap_detail = 'invalid snapshot file'
        except Exception as exc:
            snap_ok = False
            snap_detail = str(exc)
    checks.append(_check('snapshot', snap_ok, snap_detail))
    if not snap_ok:
        issues.append('snapshot')
    elif snap_stale:
        issues.append('stale_snapshot')

    # Exports readable
    export_files = (
        'unified_intelligence.json',
        'scanner_data.json',
        'stats_data.json',
    )
    exports_ok = 0
    export_issues: List[str] = []
    for fname in export_files:
        path = DATA_DIR / fname
        if path.is_file():
            try:
                json.loads(path.read_text(encoding='utf-8'))
                exports_ok += 1
            except Exception:
                export_issues.append(fname)
        else:
            export_issues.append(fname)
    exports_pass = exports_ok >= 1
    checks.append(_check('exports', exports_pass, f'{exports_ok}/{len(export_files)} readable'))
    if not exports_pass:
        issues.extend(export_issues or ['exports'])

    # API / GUI endpoint (local health — no external call required on Railway worker)
    api_ok = True
    api_detail = 'deferred on telegram worker'
    if os.environ.get('API_BASE_URL') or os.environ.get('RAILWAY_ENVIRONMENT'):
        api_ok = True
    checks.append(_check('api', api_ok, api_detail))

    # AI providers initialized (keys loaded, not invoked)
    ai_ok = False
    ai_detail = 'unknown'
    try:
        from backend.ai.provider_manager import get_provider_env_diagnostics
        diag = get_provider_env_diagnostics()
        ai_ok = (diag.get('gemini_loaded') or 0) > 0 or (diag.get('groq_loaded') or 0) > 0
        ai_detail = f"gemini={diag.get('gemini_loaded', 0)} groq={diag.get('groq_loaded', 0)} claude={'yes' if diag.get('claude_loaded') else 'no'}"
    except Exception as exc:
        ai_detail = f'error: {exc}'
    checks.append(_check('ai_providers', ai_ok, ai_detail))
    if not ai_ok:
        issues.append('ai_providers')

    # Job locks — no active deadlock flags
    locks_ok = True
    locks_detail = 'idle'
    try:
        from backend.runtime.global_job_locks import GLOBAL_JOB_LOCKS
        active = [k for k, v in GLOBAL_JOB_LOCKS.items() if v]
        locks_ok = len(active) == 0
        locks_detail = 'active: ' + ', '.join(active) if active else 'idle'
        if not locks_ok:
            issues.append('job_locks')
    except Exception as exc:
        locks_detail = str(exc)
    checks.append(_check('job_locks', locks_ok, locks_detail))

    degraded = bool(issues)
    final = STARTUP_DEGRADED if degraded else STARTUP_READY

    summary = {
        'state': final,
        'issues': list(dict.fromkeys(issues)),
        'checks_passed': sum(1 for c in checks if c['ok']),
        'checks_total': len(checks),
        'evaluated_at': datetime.now(timezone.utc).isoformat(),
        'uptime_sec': int(time.time() - _STARTED_AT),
    }
    return final, checks, summary


def format_startup_telegram_message(state: str, checks: List[dict], summary: Dict[str, Any]) -> str:
    """Build the final online announcement (sent once after readiness)."""
    if state == STARTUP_READY:
        header = '✅ <b>Trading Copilot FULLY OPERATIONAL</b>'
        sub = 'All startup checks passed. Command interface is ready.'
    else:
        header = '⚠️ <b>Trading Copilot started in DEGRADED MODE</b>'
        sub = 'Command interface is online; some subsystems are unavailable or stale.'

    lines = [header, sub, '']
    issues = summary.get('issues') or []
    if issues:
        lines.append('<b>Attention</b>')
        for issue in issues[:8]:
            lines.append(f'• {issue}')
        lines.append('')

    lines.append('<b>Startup checks</b>')
    for chk in checks:
        icon = '✓' if chk.get('ok') else '✗'
        detail = chk.get('detail') or ''
        lines.append(f"{icon} {chk.get('name')}: {detail}")

    lines.extend([
        '',
        'Type /help for commands.',
        '<i>/review — consolidated desk note (cache-only)</i>',
    ])
    return '\n'.join(lines)


def run_startup_sequence(on_log=None) -> tuple[str, list, dict]:
    """
    Run startup state transitions and return final state.
    on_log: optional callable(message) for console logging.
    """
    log = on_log or (lambda msg: None)

    set_startup_state(STARTUP_BOOTING)
    log('[STARTUP] BOOTING')
    time.sleep(0.1)

    set_startup_state(STARTUP_INITIALIZING)
    log('[STARTUP] INITIALIZING')
    try:
        from backend.ai.provider_manager import log_provider_startup_diagnostics
        log_provider_startup_diagnostics(force=True)
    except Exception as exc:
        log(f'[STARTUP] provider diagnostics: {exc}')

    set_startup_state(STARTUP_WARMING)
    log('[STARTUP] WARMING_PIPELINES (readiness validation)')
    final, checks, summary = evaluate_startup_readiness()
    set_startup_state(final)
    log(f'[STARTUP] {final} — {summary.get("checks_passed")}/{summary.get("checks_total")} checks')
    return final, checks, summary
