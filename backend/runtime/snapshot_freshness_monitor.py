"""
Snapshot freshness monitor — collector heartbeats, SLA validation, stale invalidation.

When stale: intelligence degraded, confidence suppressed, elite outputs blocked, quality lowered.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
HEARTBEAT_FILE = DATA_DIR / 'collector_heartbeats.json'

DEFAULT_SLA_SECONDS = {
    'intelligence': 1800,
    'scanner': 2700,
    'markets': 2700,
    'india': 2700,
    'news': 3600,
    'stats': 7200,
    'history': 7200,
}


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _load_heartbeats() -> dict:
    if not HEARTBEAT_FILE.exists():
        return {'sources': {}, 'updated_at': None}
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'sources': {}, 'updated_at': None}
    except Exception:
        return {'sources': {}, 'updated_at': None}


def record_collector_heartbeat(source: str, *, status: str = 'ok', detail: Optional[str] = None) -> None:
    """Record collector refresh — called from pipeline/collectors when data lands."""
    state = _load_heartbeats()
    sources = state.setdefault('sources', {})
    sources[str(source)] = {
        'at': _now_iso(),
        'at_unix': time.time(),
        'status': status,
        'detail': detail,
    }
    state['updated_at'] = _now_iso()
    atomic_write_json(HEARTBEAT_FILE, state)


def _snapshot_sla_seconds() -> int:
    try:
        from backend.intelligence.active_snapshot import STALE_SNAPSHOT_MINUTES
        return int(STALE_SNAPSHOT_MINUTES) * 60
    except Exception:
        return 30 * 60


def _snapshot_age_minutes_direct() -> Optional[int]:
    """Age from active snapshot publish time — avoids circular snapshot_health calls."""
    from backend.intelligence.active_snapshot import get_active_snapshot_meta, snapshot_age_minutes
    age = snapshot_age_minutes()
    if age is not None:
        return age
    meta = get_active_snapshot_meta() or {}
    published = meta.get('published_at')
    if not published:
        return None
    try:
        from backend.runtime.freshness_engine import age_minutes as age_minutes_fn
        return age_minutes_fn(published)
    except Exception:
        return None


def _pipeline_stalled() -> bool:
    try:
        from backend.runtime.pipeline_stage_log import get_pipeline_stage_summary
        age = _snapshot_age_minutes_direct()
        after_hours = False
        try:
            from backend.utils.market_hours import get_operational_status
            after_hours = bool(get_operational_status().get('expect_quiet_collectors'))
        except Exception:
            pass
        pipeline = get_pipeline_stage_summary(
            snapshot_age_minutes=age,
            after_hours=after_hours,
        ) or {}
        return bool(pipeline.get('any_stalled'))
    except Exception:
        return False


def evaluate_snapshot_freshness() -> Dict[str, Any]:
    """Assess active snapshot + collector heartbeats against SLA."""
    from backend.intelligence.active_snapshot import get_active_snapshot_meta
    from backend.runtime.freshness_engine import (
        merge_freshness_payload,
        freshness_health_tier,
        is_snapshot_degraded,
        STALE_MIN_MINUTES,
        DEGRADED_MAX_MINUTES,
    )

    meta = get_active_snapshot_meta() or {}
    age_minutes = _snapshot_age_minutes_direct()
    tier = freshness_health_tier(age_minutes)
    pipeline_stalled = _pipeline_stalled()
    stale = tier == 'stale'
    degraded = is_snapshot_degraded(age_minutes, pipeline_stalled=pipeline_stalled)
    score = 100

    heartbeats = _load_heartbeats().get('sources') or {}
    now = time.time()
    collector_issues = []
    for source, sla in DEFAULT_SLA_SECONDS.items():
        hb = heartbeats.get(source) or {}
        ts = hb.get('at_unix')
        if ts is None:
            continue
        age = now - float(ts)
        if age > sla:
            collector_issues.append(f'{source}_heartbeat_stale:{int(age)}s')

    warnings: list = []
    if age_minutes is None:
        score -= 20
        warnings.append('Snapshot timestamp unreadable')
    elif stale:
        score = max(0, score - 40)
        warnings.append(f'Snapshot older than {STALE_MIN_MINUTES} minutes')
    elif tier == 'aging':
        score = max(0, score - 10)
    if degraded and not stale:
        score = max(0, score - 25)
        warnings.append(f'Snapshot older than {DEGRADED_MAX_MINUTES} minutes')
    if pipeline_stalled:
        score = max(0, score - 30)
        warnings.append('Pipeline stalled')
    if collector_issues:
        score = max(0, score - min(20, len(collector_issues) * 5))

    suppress_confidence = stale or degraded
    block_elite = stale or degraded
    quality_penalty = 0.35 if degraded else (0.15 if stale else (0.08 if tier == 'aging' else 0.0))

    result = {
        'fresh': tier == 'healthy',
        'stale': stale,
        'degraded': degraded,
        'health_tier': tier,
        'age_minutes': age_minutes,
        'stale_threshold_minutes': STALE_MIN_MINUTES,
        'degraded_threshold_minutes': DEGRADED_MAX_MINUTES,
        'pipeline_stalled': pipeline_stalled,
        'snapshot_version': meta.get('snapshot_version'),
        'active_snapshot_id': meta.get('active_snapshot_id'),
        'freshness_score': score,
        'suppress_confidence': suppress_confidence,
        'block_elite_outputs': block_elite,
        'quality_score_penalty': quality_penalty,
        'collector_issues': collector_issues,
        'sla_seconds': _snapshot_sla_seconds(),
        'warnings': warnings + collector_issues,
        'collectors_active': len(collector_issues) < len(DEFAULT_SLA_SECONDS),
    }
    return merge_freshness_payload(result, timestamp=meta.get('published_at'))


def apply_stale_degradation(intelligence: dict, freshness: Optional[dict] = None) -> dict:
    """Mark intelligence degraded when snapshot is stale."""
    intel = dict(intelligence or {})
    fresh = freshness or evaluate_snapshot_freshness()
    if fresh.get('stale'):
        intel['intelligence_status'] = 'degraded'
        intel['confidence_suppressed'] = True
        intel['elite_blocked'] = True
        mood = dict(intel.get('market_mood') or {})
        mood['confidence_note'] = 'Snapshot stale — confidence suppressed until refresh'
        intel['market_mood'] = mood
    elif fresh.get('degraded'):
        intel['intelligence_status'] = 'degraded'
    else:
        intel.setdefault('intelligence_status', 'ready')
    intel['snapshot_freshness'] = fresh
    return intel


def invalidate_if_stale() -> bool:
    """Return True when active snapshot exceeds SLA (auto-invalidation signal)."""
    fresh = evaluate_snapshot_freshness()
    return bool(fresh.get('stale'))
