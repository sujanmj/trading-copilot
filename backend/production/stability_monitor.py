"""Production stability probes — snapshot integrity, memory, stale exports."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pytz

from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
_log = logging.getLogger(__name__)


def _memory_pressure() -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            'percent': vm.percent,
            'pressure': vm.percent >= 90,
        }
    except Exception:
        return {'percent': None, 'pressure': False}


def validate_snapshot_schema(payload: dict) -> Tuple[bool, List[str]]:
    issues = []
    if not isinstance(payload, dict):
        return False, ['snapshot not dict']
    for key in ('active_snapshot_id', 'published_at', 'snapshot_version'):
        if not payload.get(key):
            issues.append(f'missing {key}')
    return (len(issues) == 0, issues)


def sanitize_ai_response(text: str) -> str:
    if not text:
        return ''
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(text))
    cleaned = cleaned.replace('```', '').strip()
    return cleaned[:12000]


def detect_stale_exports() -> List[str]:
    warnings = []
    now = datetime.now(IST)
    checks = {
        'stats_data.json': 720,
        'history_data.json': 720,
        'active_snapshot.json': 45,
    }
    for name, max_min in checks.items():
        path = DATA_DIR / name
        if not path.exists():
            warnings.append(f'{name} missing')
            continue
        age_min = (now.timestamp() - path.stat().st_mtime) / 60
        if age_min > max_min:
            warnings.append(f'{name} stale {int(age_min)}m')
    return warnings


def run_stability_probe() -> Dict[str, Any]:
    from backend.intelligence.active_snapshot import load_active_snapshot, snapshot_health
    from backend.history.history_engine import get_history_heartbeat

    snap = load_active_snapshot()
    schema_ok, schema_issues = validate_snapshot_schema(snap) if snap else (False, ['no snapshot'])
    health = snapshot_health()
    history_hb = get_history_heartbeat()
    stale_exports = detect_stale_exports()
    mem = _memory_pressure()

    score = int(health.get('score') or 0)
    if not schema_ok:
        score = max(0, score - 20)
    if stale_exports:
        score = max(0, score - min(30, len(stale_exports) * 5))
    if history_hb.get('status') == 'failed':
        score = max(0, score - 15)
    if mem.get('pressure'):
        score = max(0, score - 10)

    if schema_issues or stale_exports or history_hb.get('status') == 'failed':
        _log.warning('[STABILITY] issues schema=%s exports=%s history=%s', schema_issues, stale_exports, history_hb.get('status'))

    return {
        'score': score,
        'snapshot_health': health,
        'schema_ok': schema_ok,
        'schema_issues': schema_issues,
        'history_heartbeat': history_hb,
        'stale_exports': stale_exports,
        'memory': mem,
        'checked_at': datetime.now(IST).isoformat(),
    }


def tick_async_watchdog() -> dict:
    """Lightweight watchdog tick — drain retry queue + pending cleanup."""
    results = {'stability': run_stability_probe()}
    try:
        from backend.runtime.stall_watchdog import tick_stall_watchdog
        results['stall_watchdog'] = tick_stall_watchdog()
    except Exception as exc:
        results['stall_watchdog'] = {'error': str(exc)}
    try:
        from backend.lifecycle.pending_cleanup_daemon import tick_pending_cleanup
        results['pending_cleanup'] = tick_pending_cleanup()
    except Exception as exc:
        results['pending_cleanup'] = {'error': str(exc)}
    try:
        from backend.orchestration.retry_queue import drain_retry_queue

        def _history(_payload):
            from backend.history.history_engine import run_history_export
            return run_history_export()

        def _stats(_payload):
            from backend.storage.stats_exporter import export_stats
            return export_stats()

        results['retries'] = drain_retry_queue({
            'history_export': _history,
            'stats_export': _stats,
        })
    except Exception as exc:
        results['retries'] = {'error': str(exc)}
    return results
