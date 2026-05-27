"""
Deterministic snapshot pipeline — build → validate → commit → publish.

Integrates with existing scheduler/collectors; does not run collectors itself unless
triggered from a full refresh cycle. No partial publishing.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from backend.runtime.market_snapshot import MarketSnapshot
from backend.runtime.market_snapshot_engine import (
    build_market_snapshot,
    commit_market_snapshot,
    invalidate_snapshot_cache,
    validate_market_snapshot,
)


def _log_stage(stage: str, *, status: str = 'ok', detail: str = '') -> None:
    try:
        from backend.runtime.pipeline_stage_log import pipeline_stage_log
        pipeline_stage_log(stage, status=status, detail=detail)
    except Exception:
        pass


def run_snapshot_cycle(
    *,
    trigger: str = 'manual',
    force_refresh: bool = True,
) -> Dict[str, Any]:
    """
    scheduler → normalize → snapshot build → validation → commit → publish

    Collector steps are assumed complete when this runs after /refresh or scheduler tick.
    """
    started = time.time()
    result: Dict[str, Any] = {
        'ok': False,
        'trigger': trigger,
        'stages': [],
    }

    _log_stage('aggregation', status='start', detail=trigger)
    result['stages'].append('normalize')

    invalidate_snapshot_cache()
    snapshot = build_market_snapshot(force_refresh=force_refresh)
    result['stages'].append('build')
    result['snapshot_id'] = snapshot.snapshot_id

    ok, issues = validate_market_snapshot(snapshot)
    result['stages'].append('validate')
    result['validation'] = {'valid': ok, 'issues': issues}
    if not ok:
        result['error'] = 'validation_failed'
        _log_stage('snapshot_export', status='error', detail=';'.join(issues[:3]))
        return result

    path = commit_market_snapshot(snapshot)
    result['stages'].append('commit')
    result['path'] = str(path)

    publish_snapshot(snapshot, trigger=trigger)
    result['stages'].append('publish')
    result['ok'] = True
    result['elapsed_ms'] = int((time.time() - started) * 1000)

    _log_stage('snapshot_export', status='ok', detail=snapshot.snapshot_id)
    _log_stage('cache', status='ok', detail='snapshot_committed')
    return result


def publish_snapshot(snapshot: MarketSnapshot, *, trigger: str = '') -> None:
    """Signal downstream readers — cache bust only after commit."""
    try:
        from backend.runtime.pipeline_stage_log import refresh_stages_on_snapshot_publish
        refresh_stages_on_snapshot_publish(snapshot.snapshot_id or trigger or 'publish')
    except Exception:
        pass
    try:
        from backend.utils.config import DATA_DIR
        flag = DATA_DIR / '_runtime_cache_invalidate.flag'
        import json
        from datetime import datetime
        flag.write_text(
            json.dumps({
                'at': datetime.now().isoformat(),
                'reason': f'snapshot_publish:{trigger}',
                'snapshot_id': snapshot.snapshot_id,
            }),
            encoding='utf-8',
        )
    except Exception:
        pass
    invalidate_snapshot_cache()


def get_committed_snapshot_dict() -> Optional[Dict[str, Any]]:
    from backend.runtime.market_snapshot_engine import load_committed_snapshot
    snap = load_committed_snapshot()
    return snap.to_dict() if snap else None
