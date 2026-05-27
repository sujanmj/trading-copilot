"""
Stall watchdog — scanner/snapshot/exports stale >30m → DEGRADED, warn, auto-recovery.

Invoked from stability_monitor tick and runtime_state build.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

IST = pytz.timezone('Asia/Kolkata')
_log = logging.getLogger(__name__)

STALL_THRESHOLD_MINUTES = 30
_RECOVERY_COOLDOWN_SEC = 900
_last_recovery_at: float = 0.0
_recovery_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def evaluate_stalls(*, threshold_minutes: int = STALL_THRESHOLD_MINUTES) -> Dict[str, Any]:
    """Aggregate stall signals from pipeline, snapshot, exports, scanner."""
    from backend.runtime.pipeline_stage_log import detect_stalled_stages, get_pipeline_stage_summary
    from backend.runtime.scanner_heartbeat_monitor import evaluate_scanner_health
    from backend.runtime.snapshot_freshness_monitor import evaluate_snapshot_freshness
    from backend.production.stability_monitor import detect_stale_exports

    issues = []
    root_causes = []

    fresh = evaluate_snapshot_freshness()
    snap_age = fresh.get('age_minutes')
    after_hours = False
    try:
        from backend.utils.market_hours import get_operational_status
        after_hours = bool(get_operational_status().get('expect_quiet_collectors'))
    except Exception:
        pass

    if fresh.get('stale') or (snap_age is not None and snap_age >= threshold_minutes):
        issues.append('snapshot_stale')
        root_causes.append(f'snapshot_age={snap_age}m')

    scanner = evaluate_scanner_health(stall_minutes=threshold_minutes)
    if scanner.get('stalled') and not scanner.get('expect_quiet') and not after_hours:
        issues.append('scanner_stalled')
        root_causes.append(scanner.get('display', 'scanner'))

    if not after_hours and (snap_age is None or snap_age >= threshold_minutes):
        for w in detect_stale_exports():
            issues.append(f'export:{w}')
            root_causes.append(w)

    pipeline = get_pipeline_stage_summary(
        snapshot_age_minutes=snap_age,
        after_hours=after_hours,
    )
    stage_probe = detect_stalled_stages(
        threshold_minutes=threshold_minutes,
        snapshot_age_minutes=snap_age,
        after_hours=after_hours,
    )
    for item in stage_probe.get('critical_overdue') or []:
        issues.append(f"stage:{item.get('stage')}")
        root_causes.append(f"{item.get('stage')}:{item.get('reason')}")

    degraded = bool(issues)
    return {
        'degraded': degraded,
        'issues': issues,
        'root_causes': root_causes,
        'threshold_minutes': threshold_minutes,
        'scanner': scanner,
        'snapshot_freshness': {
            'stale': fresh.get('stale'),
            'age_minutes': snap_age,
        },
        'pipeline': pipeline,
        'pipeline_stages': stage_probe,
        'checked_at': _now_iso(),
    }


def maybe_trigger_recovery(*, source: str = 'watchdog') -> Dict[str, Any]:
    """Auto-trigger refresh recovery when degraded (cooldown 15m)."""
    global _last_recovery_at
    report = evaluate_stalls()
    if not report.get('degraded'):
        return {'triggered': False, 'reason': 'healthy', 'report': report}

    now = time.time()
    with _recovery_lock:
        if now - _last_recovery_at < _RECOVERY_COOLDOWN_SEC:
            return {
                'triggered': False,
                'reason': 'recovery_cooldown',
                'report': report,
            }
        _last_recovery_at = now

    _log.warning(
        '[STALL WATCHDOG] degraded source=%s causes=%s',
        source,
        report.get('root_causes'),
    )
    try:
        from backend.runtime.pipeline_stage_log import pipeline_stage_log
        pipeline_stage_log(
            'cache',
            status='recovery',
            detail=';'.join(report.get('root_causes') or [])[:160],
            extra={'source': source},
        )
    except Exception:
        pass

    triggered = False
    detail = 'queued'

    def _recovery_work():
        try:
            from backend.utils.runner import run_script_capture
            run_script_capture('stock_scanner.py', timeout=300)
        except Exception as exc:
            _log.warning('[STALL WATCHDOG] scanner recovery failed: %s', exc)
        try:
            from backend.intelligence.canonical_rankings import align_intelligence
            from backend.utils.config import DATA_DIR
            import json
            intel_path = DATA_DIR / 'unified_intelligence.json'
            if intel_path.exists():
                raw = json.loads(intel_path.read_text(encoding='utf-8'))
                align_intelligence(
                    raw if isinstance(raw, dict) else {},
                    cycle_id=f'recovery_{int(time.time())}',
                )
        except Exception as exc:
            _log.warning('[STALL WATCHDOG] align recovery failed: %s', exc)
        try:
            from backend.storage.stats_exporter import export_stats
            from backend.storage.history_exporter import export_history
            export_stats()
            export_history()
        except Exception:
            pass
        try:
            from backend.runtime.runtime_state import build_runtime_state
            build_runtime_state(force_refresh=True)
        except Exception:
            pass

    threading.Thread(target=_recovery_work, daemon=True, name='stall_recovery').start()
    triggered = True
    detail = 'background_recovery'

    return {
        'triggered': triggered,
        'reason': 'degraded_recovery',
        'detail': detail,
        'report': report,
    }


def tick_stall_watchdog() -> Dict[str, Any]:
    """Lightweight tick — evaluate + optional recovery."""
    report = evaluate_stalls()
    out = {'report': report, 'recovery': None}
    if report.get('degraded'):
        out['recovery'] = maybe_trigger_recovery(source='tick')
    return out
