"""
Active snapshot engine — single frozen intelligence view per pipeline cycle.

All Telegram commands and GUI runtime reads use ACTIVE_SNAPSHOT_ID when available.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
ACTIVE_SNAPSHOT_FILE = DATA_DIR / 'active_snapshot.json'
STALE_SNAPSHOT_MINUTES = int(__import__('os').environ.get('SNAPSHOT_STALE_MINUTES', '30'))

_log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _load_json(path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if data is not None else default
    except Exception:
        return default


def publish_active_snapshot(
    intel: dict,
    *,
    cycle_id: Optional[str] = None,
    source: str = 'pipeline',
) -> dict:
    """Freeze canonical fields after full pipeline completion."""
    from backend.intelligence.sector_consistency import stabilize_sector_rotation

    intel = intel if isinstance(intel, dict) else {}
    snapshot_id = f"snap_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}"
    sectors = stabilize_sector_rotation(intel)
    ts = intel.get('timestamp') or intel.get('generation_time') or _now_iso()

    payload = {
        'active_snapshot_id': snapshot_id,
        'snapshot_id': snapshot_id,
        'cycle_id': cycle_id or intel.get('cycle_id'),
        'published_at': _now_iso(),
        'intelligence_timestamp': ts,
        'source': source,
        'sector_rotation': sectors,
        'market_mood': intel.get('market_mood') or {},
        'executive_summary': intel.get('executive_summary') or intel.get('analysis'),
        'action_plan': intel.get('action_plan'),
        'top_opportunities': intel.get('top_opportunities') or intel.get('opportunities') or [],
        'canonical_opportunity_feed': intel.get('canonical_opportunity_feed') or {},
    }
    try:
        from backend.utils.config import ANALYSIS_STATE_FILE
        if ANALYSIS_STATE_FILE.exists():
            state = _load_json(ANALYSIS_STATE_FILE)
            payload['primary_regime'] = state.get('last_regime')
    except Exception:
        pass

    atomic_write_json(ACTIVE_SNAPSHOT_FILE, payload)
    _log.info('[SNAPSHOT] published %s cycle=%s source=%s', snapshot_id, cycle_id, source)
    return payload


def load_active_snapshot() -> dict:
    return _load_json(ACTIVE_SNAPSHOT_FILE, {})


def get_active_snapshot_meta() -> dict:
    snap = load_active_snapshot()
    if not snap:
        return {'active_snapshot_id': None, 'published_at': None, 'cycle_id': None}
    return {
        'active_snapshot_id': snap.get('active_snapshot_id') or snap.get('snapshot_id'),
        'snapshot_id': snap.get('snapshot_id'),
        'published_at': snap.get('published_at'),
        'cycle_id': snap.get('cycle_id'),
        'intelligence_timestamp': snap.get('intelligence_timestamp'),
        'source': snap.get('source'),
    }


def snapshot_age_minutes() -> Optional[int]:
    snap = load_active_snapshot()
    published = snap.get('published_at')
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(str(published).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        age = datetime.now(IST) - dt.astimezone(IST)
        return max(0, int(age.total_seconds() / 60))
    except Exception:
        return None


def snapshot_health() -> dict:
    age = snapshot_age_minutes()
    snap = load_active_snapshot()
    score = 100
    warnings = []
    if not snap:
        return {'score': 0, 'stale': True, 'warnings': ['No active snapshot published'], 'age_minutes': None}
    if age is None:
        score -= 20
        warnings.append('Snapshot timestamp unreadable')
    elif age > STALE_SNAPSHOT_MINUTES:
        score -= min(50, age - STALE_SNAPSHOT_MINUTES)
        warnings.append(f'Snapshot older than {STALE_SNAPSHOT_MINUTES} minutes')
    if not snap.get('sector_rotation'):
        score -= 10
        warnings.append('Sector rotation missing from snapshot')
    return {
        'score': max(0, score),
        'stale': bool(age is not None and age > STALE_SNAPSHOT_MINUTES),
        'warnings': warnings,
        'age_minutes': age,
        'active_snapshot_id': snap.get('active_snapshot_id'),
    }


def snapshot_header() -> str:
    snap = load_active_snapshot()
    published = snap.get('published_at') or snap.get('intelligence_timestamp')
    if not published:
        return ''
    try:
        dt = datetime.fromisoformat(str(published).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        label = dt.astimezone(IST).strftime('%H:%M')
    except Exception:
        label = str(published)[11:16]
    health = snapshot_health()
    stale = ' ⚠️' if health.get('stale') else ''
    return f"<i>Snapshot: {label}{stale}</i>\n\n"


def snapshot_stale_warning() -> str:
    health = snapshot_health()
    if not health.get('stale'):
        return ''
    age = health.get('age_minutes')
    return f"⚠️ <i>Snapshot may be stale — last refresh {age}m ago</i>\n\n"


def get_canonical_intelligence() -> dict:
    """Load intelligence merged with frozen active snapshot fields."""
    intel = _load_json(INTEL_FILE, {})
    snap = load_active_snapshot()
    if not intel or intel.get('error'):
        return intel
    if not snap:
        return intel
    out = dict(intel)
    snap_id = snap.get('active_snapshot_id') or snap.get('snapshot_id')
    out['active_snapshot_id'] = snap_id
    out['snapshot_cycle_id'] = snap.get('cycle_id')
    if snap.get('sector_rotation'):
        out['sector_rotation'] = snap['sector_rotation']
    if snap.get('market_mood'):
        out['market_mood'] = {**(out.get('market_mood') or {}), **snap['market_mood']}
    if snap.get('action_plan'):
        out['action_plan'] = snap['action_plan']
    if snap.get('top_opportunities'):
        out['top_opportunities'] = snap['top_opportunities']
        out['opportunities'] = snap['top_opportunities']
    if snap.get('canonical_opportunity_feed'):
        out['canonical_opportunity_feed'] = snap['canonical_opportunity_feed']
    out['snapshot_published_at'] = snap.get('published_at')
    return out


def log_snapshot_anomaly(event: str, detail: str) -> None:
    _log.warning('[SNAPSHOT ANOMALY] %s — %s', event, detail)
