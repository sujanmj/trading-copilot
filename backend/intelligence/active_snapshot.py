"""
Active snapshot engine — single frozen intelligence view per pipeline cycle.

Atomic publish lock, monotonic snapshot_version, stale job abort.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import CURRENT_SNAPSHOT_FILE, DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
ACTIVE_SNAPSHOT_FILE = DATA_DIR / 'active_snapshot.json'
STALE_SNAPSHOT_MINUTES = int(__import__('os').environ.get('SNAPSHOT_STALE_MINUTES', '15'))

_log = logging.getLogger(__name__)
_publish_lock = threading.Lock()
_active_publish_token: Optional[str] = None
_cycle_publish_guard: Dict[str, float] = {}


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


def _parse_snapshot_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        return dt.astimezone(IST)
    except Exception:
        return None


def _snapshot_timestamp(payload: dict) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ('published_at', '_committed_at', 'snapshot_built_at', 'generated_at'):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _file_mtime(path) -> Optional[float]:
    try:
        return path.stat().st_mtime if path.exists() else None
    except Exception:
        return None


def _current_snapshot_is_newer(current: dict, active: dict) -> bool:
    current_dt = _parse_snapshot_dt(_snapshot_timestamp(current))
    active_dt = _parse_snapshot_dt(_snapshot_timestamp(active))
    if current_dt and active_dt:
        return current_dt > active_dt
    if current_dt and not active_dt:
        return True
    current_mtime = _file_mtime(CURRENT_SNAPSHOT_FILE)
    active_mtime = _file_mtime(ACTIVE_SNAPSHOT_FILE)
    return current_mtime is not None and (active_mtime is None or current_mtime > active_mtime)


def _active_payload_from_market_snapshot(
    snapshot_payload: dict,
    *,
    snapshot_version: Optional[int] = None,
    source: str = 'market_snapshot_commit',
) -> dict:
    """Project the committed runtime snapshot into the active snapshot schema."""
    if not isinstance(snapshot_payload, dict):
        return {}
    intelligence = snapshot_payload.get('intelligence')
    if not isinstance(intelligence, dict):
        intelligence = {}
    snapshot_id = (
        snapshot_payload.get('snapshot_id')
        or snapshot_payload.get('active_snapshot_id')
        or intelligence.get('active_snapshot_id')
        or intelligence.get('snapshot_id')
    )
    published_at = _snapshot_timestamp(snapshot_payload)
    if not snapshot_id or not published_at:
        return {}
    top_opportunities = (
        snapshot_payload.get('top_opportunities')
        or intelligence.get('top_opportunities')
        or intelligence.get('opportunities')
        or []
    )
    canonical_feed = intelligence.get('canonical_opportunity_feed') or {}
    if not canonical_feed:
        canonical_feed = {
            'source': 'market_snapshot',
            'top_count': len(top_opportunities) if isinstance(top_opportunities, list) else 0,
        }
    version = _safe_int(
        snapshot_version
        if snapshot_version is not None
        else snapshot_payload.get('snapshot_version') or intelligence.get('snapshot_version'),
        1,
    )
    return {
        'active_snapshot_id': snapshot_id,
        'snapshot_id': snapshot_id,
        'snapshot_version': max(1, version),
        'cycle_id': (
            intelligence.get('snapshot_cycle_id')
            or intelligence.get('cycle_id')
            or snapshot_payload.get('cycle_id')
            or snapshot_id
        ),
        'published_at': published_at,
        'intelligence_timestamp': (
            intelligence.get('timestamp')
            or intelligence.get('generation_time')
            or snapshot_payload.get('generated_at')
            or published_at
        ),
        'source': source,
        'sector_rotation': snapshot_payload.get('sector_rotation') or intelligence.get('sector_rotation') or {},
        'market_mood': snapshot_payload.get('market_mood') or intelligence.get('market_mood') or {},
        'executive_summary': (
            snapshot_payload.get('executive_summary')
            or intelligence.get('executive_summary')
            or intelligence.get('analysis')
        ),
        'action_plan': snapshot_payload.get('action_plan') or intelligence.get('action_plan'),
        'top_opportunities': top_opportunities if isinstance(top_opportunities, list) else [],
        'canonical_opportunity_feed': canonical_feed,
        'runtime_snapshot_id': snapshot_payload.get('snapshot_id'),
        'runtime_generated_at': snapshot_payload.get('generated_at'),
    }


def _bridge_current_snapshot(active: dict) -> dict:
    current = _load_json(CURRENT_SNAPSHOT_FILE, {})
    if not current or not _current_snapshot_is_newer(current, active):
        return {}
    version = _safe_int(active.get('snapshot_version') or current.get('snapshot_version'), 1)
    return _active_payload_from_market_snapshot(
        current,
        snapshot_version=version,
        source='current_snapshot_bridge',
    )


def _next_version() -> int:
    snap = load_active_snapshot()
    return int(snap.get('snapshot_version') or 0) + 1


def begin_publish_job(*, source: str = 'pipeline', cycle_id: Optional[str] = None) -> dict:
    """Acquire publish intent — stale async jobs must compare token before publishing."""
    global _active_publish_token
    token = f"{source}_{uuid.uuid4().hex[:12]}_{int(time.time())}"
    with _publish_lock:
        _active_publish_token = token
        current = load_active_snapshot()
        return {
            'publish_token': token,
            'expected_version': int(current.get('snapshot_version') or 0),
            'cycle_id': cycle_id,
            'started_at': _now_iso(),
        }


def assert_publish_allowed(publish_token: Optional[str], *, expected_version: Optional[int] = None) -> Tuple[bool, str]:
    """Return (allowed, reason). Stale jobs self-abort when token/version mismatches."""
    if not publish_token:
        return True, 'no_token'
    with _publish_lock:
        if _active_publish_token and publish_token != _active_publish_token:
            return False, 'superseded_token'
    if expected_version is not None:
        current = load_active_snapshot()
        cur_ver = int(current.get('snapshot_version') or 0)
        if cur_ver > expected_version:
            return False, 'newer_snapshot_exists'
    return True, 'ok'


def validate_snapshot_schema(payload: dict) -> Tuple[bool, list]:
    issues = []
    if not isinstance(payload, dict):
        return False, ['not_dict']
    for key in ('active_snapshot_id', 'published_at', 'snapshot_version'):
        if payload.get(key) is None:
            issues.append(f'missing_{key}')
    return (len(issues) == 0, issues)


def publish_active_snapshot(
    intel: dict,
    *,
    cycle_id: Optional[str] = None,
    source: str = 'pipeline',
    publish_token: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> Optional[dict]:
    """Freeze canonical fields — only one publish wins per cycle/version."""
    from backend.intelligence.sector_consistency import stabilize_sector_rotation

    allowed, reason = assert_publish_allowed(publish_token, expected_version=expected_version)
    if not allowed:
        log_snapshot_anomaly('publish_aborted', f'{source}: {reason}')
        return None

    intel = intel if isinstance(intel, dict) else {}
    resolved_cycle = cycle_id or intel.get('cycle_id') or intel.get('snapshot_cycle_id')
    published_at = _now_iso()

    with _publish_lock:
        current = load_active_snapshot()
        cur_ver = int(current.get('snapshot_version') or 0)
        if expected_version is not None and cur_ver > expected_version:
            log_snapshot_anomaly('stale_job_abort', f'{source} expected v{expected_version} but v{cur_ver} live')
            return None

        if resolved_cycle and current.get('cycle_id') == resolved_cycle:
            last_pub = current.get('published_at')
            if last_pub:
                try:
                    prev_dt = datetime.fromisoformat(str(last_pub).replace('Z', '+00:00'))
                    new_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    if prev_dt.tzinfo is None:
                        prev_dt = IST.localize(prev_dt)
                    if new_dt.tzinfo is None:
                        new_dt = IST.localize(new_dt)
                    if prev_dt >= new_dt.astimezone(IST):
                        log_snapshot_anomaly('stale_timestamp', f'{source} publish timestamp not newer')
                        return None
                except Exception:
                    pass

        guard_key = str(resolved_cycle or source)
        now_ts = time.time()
        last_guard = _cycle_publish_guard.get(guard_key)
        if last_guard and (now_ts - last_guard) < 2.0:
            log_snapshot_anomaly('cycle_duplicate', f'{source} duplicate publish within 2s for {guard_key}')
            return current

        sectors = stabilize_sector_rotation(intel)
        ts = intel.get('timestamp') or intel.get('generation_time') or published_at
        snapshot_id = f"snap_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}"
        new_version = max(cur_ver + 1, _next_version())

        payload = {
            'active_snapshot_id': snapshot_id,
            'snapshot_id': snapshot_id,
            'snapshot_version': new_version,
            'cycle_id': resolved_cycle,
            'published_at': published_at,
            'intelligence_timestamp': ts,
            'source': source,
            'publish_token': publish_token,
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

        ok, schema_issues = validate_snapshot_schema(payload)
        if not ok:
            log_snapshot_anomaly('schema_fail', ','.join(schema_issues))
            return None

        atomic_write_json(ACTIVE_SNAPSHOT_FILE, payload)
        try:
            from backend.storage.runtime_snapshot_memory_capture import capture_after_snapshot_publish

            result = capture_after_snapshot_publish(
                file_snapshot=payload,
                source_name='snapshot_export',
            )
            print(f'[MARKET_MEMORY_AUTO] {result}')
        except Exception as e:
            print(f'[MARKET_MEMORY_AUTO] non-fatal skipped: {e}')
        _cycle_publish_guard[guard_key] = now_ts
        try:
            from backend.runtime.snapshot_freshness_monitor import record_collector_heartbeat
            record_collector_heartbeat('intelligence', status='published', detail=snapshot_id)
        except Exception:
            pass
        _log.info('[SNAPSHOT] published v%s %s cycle=%s source=%s', new_version, snapshot_id, resolved_cycle, source)
        try:
            from backend.runtime.pipeline_stage_log import pipeline_stage_log
            pipeline_stage_log(
                'snapshot_export',
                status='ok',
                detail=f'v{new_version}',
                extra={'cycle_id': resolved_cycle, 'source': source},
            )
        except Exception:
            pass
        return payload


def sync_active_snapshot_from_market_snapshot(
    snapshot_payload: dict,
    *,
    source: str = 'market_snapshot_commit',
) -> Optional[dict]:
    """Keep active_snapshot.json aligned with canonical current_snapshot commits."""
    if not isinstance(snapshot_payload, dict):
        return None
    with _publish_lock:
        current = _load_json(ACTIVE_SNAPSHOT_FILE, {})
        payload = _active_payload_from_market_snapshot(
            snapshot_payload,
            snapshot_version=_safe_int(current.get('snapshot_version'), 0) + 1,
            source=source,
        )
        ok, schema_issues = validate_snapshot_schema(payload)
        if not ok:
            log_snapshot_anomaly('market_snapshot_sync_schema_fail', ','.join(schema_issues))
            return None
        atomic_write_json(ACTIVE_SNAPSHOT_FILE, payload)
        try:
            from backend.runtime.snapshot_freshness_monitor import record_collector_heartbeat
            record_collector_heartbeat('intelligence', status='published', detail=payload['snapshot_id'])
        except Exception:
            pass
        _log.info(
            '[SNAPSHOT] synced active snapshot v%s %s source=%s',
            payload.get('snapshot_version'),
            payload.get('snapshot_id'),
            source,
        )
        return payload


def load_active_snapshot() -> dict:
    active = _load_json(ACTIVE_SNAPSHOT_FILE, {})
    bridged = _bridge_current_snapshot(active)
    return bridged or active


def get_active_snapshot_meta() -> dict:
    snap = load_active_snapshot()
    if not snap:
        return {'active_snapshot_id': None, 'published_at': None, 'cycle_id': None, 'snapshot_version': 0}
    return {
        'active_snapshot_id': snap.get('active_snapshot_id') or snap.get('snapshot_id'),
        'snapshot_id': snap.get('snapshot_id'),
        'snapshot_version': int(snap.get('snapshot_version') or 0),
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
    if not snap.get('snapshot_version'):
        score -= 5
        warnings.append('Snapshot version missing')
    return {
        'score': max(0, score),
        'stale': bool(age is not None and age > STALE_SNAPSHOT_MINUTES),
        'warnings': warnings,
        'age_minutes': age,
        'active_snapshot_id': snap.get('active_snapshot_id'),
        'snapshot_version': int(snap.get('snapshot_version') or 0),
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
    ver = int(snap.get('snapshot_version') or 0)
    return f"<i>Snapshot: {label} · v{ver}{stale}</i>\n\n"


def snapshot_stale_warning() -> str:
    health = snapshot_health()
    if not health.get('stale'):
        return ''
    try:
        from backend.runtime.freshness_engine import format_age_minutes
        age = format_age_minutes(health.get('age_minutes'))
    except Exception:
        age = 'freshness unavailable'
    return f"⚠️ <i>Snapshot may be stale — {age}</i>\n\n"


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
    out['snapshot_version'] = int(snap.get('snapshot_version') or 0)
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


def assert_snapshot_current(expected_version: Optional[int] = None, expected_cycle: Optional[str] = None) -> Tuple[bool, str]:
    snap = load_active_snapshot()
    if not snap:
        return False, 'no_snapshot'
    if expected_version is not None:
        live = int(snap.get('snapshot_version') or 0)
        if live != expected_version:
            return False, f'version_mismatch live={live} expected={expected_version}'
    if expected_cycle and snap.get('cycle_id') != expected_cycle:
        return False, 'cycle_mismatch'
    return True, 'ok'


def log_snapshot_anomaly(event: str, detail: str) -> None:
    _log.warning('[SNAPSHOT ANOMALY] %s — %s', event, detail)
