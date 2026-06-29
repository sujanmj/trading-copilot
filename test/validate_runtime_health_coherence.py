#!/usr/bin/env python3
"""Validate runtime health coherence for quiet scanner periods and /review."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'RUNTIME_HEALTH_COHERENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def main() -> int:
    from backend.runtime import runtime_state as rs

    with patch('backend.runtime.pipeline_stage_log.get_pipeline_stage_summary') as summary:
        summary.return_value = {'stages': {}, 'stalled_stages': [], 'any_stalled': False}
        rs._load_pipeline_status(
            {'age_minutes': 240},
            {'lifecycle_state': 'DEGRADED', 'after_hours_mode': False},
            {'period': 'weekend', 'expect_quiet_collectors': True},
        )
        if summary.call_args.kwargs.get('after_hours') is not True:
            return _fail('weekend quiet collectors must suppress active scanner stage stalls')

    primary = rs._map_primary_runtime_state(
        {'lifecycle_state': 'DEGRADED', 'after_hours_mode': False},
        {'period': 'weekend', 'expect_quiet_collectors': True, 'after_hours_mode': False},
        {'age_minutes': 0, 'degraded': False, 'stale': False},
        {'healthy': True, 'stalled': False},
        {'any_stalled': False},
    )
    if primary != 'AFTER_HOURS':
        return _fail(f'weekend fresh snapshot should be AFTER_HOURS, got {primary}')

    weekend_aging = rs._map_primary_runtime_state(
        {'lifecycle_state': 'DEGRADED', 'after_hours_mode': False},
        {'period': 'weekend', 'expect_quiet_collectors': True, 'after_hours_mode': False},
        {
            'age_minutes': 86,
            'degraded': False,
            'stale': False,
            'closed_market_aging': True,
            'closed_market_stale_threshold_minutes': 360,
        },
        {'healthy': True, 'stalled': False, 'idle': True},
        {'any_stalled': False, 'stalled_stages': []},
    )
    if weekend_aging != 'AFTER_HOURS':
        return _fail(f'weekend snapshot_age=86m should not be DEGRADED, got {weekend_aging}')

    market_aging = rs._map_primary_runtime_state(
        {'lifecycle_state': 'MARKET_ACTIVE', 'after_hours_mode': False},
        {'period': 'market', 'market_hours': True, 'after_hours_mode': False},
        {'age_minutes': 86, 'degraded': True, 'stale': True},
        {'healthy': True, 'stalled': False},
        {'any_stalled': False, 'stalled_stages': []},
    )
    if market_aging != 'DEGRADED':
        return _fail(f'market-hours snapshot_age=86m must remain DEGRADED, got {market_aging}')

    closed_alert = rs._load_alert_eligibility(
        {'lifecycle_state': 'AFTER_HOURS', 'after_hours_mode': True},
        {'stale': False, 'degraded': False, 'market_closed': True, 'closed_market_aging': True},
        {'elite_blocked': False, 'status': 'ready'},
    )
    if not closed_alert.get('eligible') or closed_alert.get('block_reasons'):
        return _fail(f'after-hours aging should not block research alerts: {closed_alert}')
    if closed_alert.get('execution_eligible') is not False:
        return _fail('after-hours execution eligibility must remain false')

    from backend.telegram.formatting.telegram_formatter import format_status

    closed_status = format_status({
        'primary_state': 'AFTER_HOURS',
        'lifecycle': {'lifecycle_state': 'AFTER_HOURS'},
        'session': {'session_display': 'After-hours intelligence mode', 'after_hours_mode': True},
        'snapshot_freshness': {
            'age_display': '1h 26m',
            'health_tier': 'closed-market aging',
            'stale': False,
            'closed_market_aging': True,
        },
        'scanner_health': {'display': 'Scanner: idle market closed', 'stalled': False},
        'alert_eligibility': closed_alert,
        'telegram_metrics': {'alerts_sent_today': 0, 'suppressed_today': 0},
        'source_freshness': {},
        'intelligence_freshness': {'rows': {}},
        'pipeline': {'stalled_stages': [], 'any_stalled': False},
        'metrics': {},
        'prediction_counts': {},
        'win_rate': {},
        'secondary_flags': {'closed_market_snapshot_aging': True},
    })
    if 'Alerts: eligible' not in closed_status:
        return _fail(f'/status should show closed-market research alerts eligible: {closed_status}')
    if '<b>Blockers</b>' in closed_status:
        return _fail(f'/status should not show closed-market aging as blocker: {closed_status}')

    premarket_alert = rs._load_alert_eligibility(
        {'lifecycle_state': 'PREMARKET', 'after_hours_mode': False},
        {'stale': True, 'degraded': True, 'market_state': 'PREMARKET'},
        {'elite_blocked': True, 'status': 'degraded'},
    )
    if not premarket_alert.get('eligible') or premarket_alert.get('execution_eligible'):
        return _fail(f'premarket stale data should allow watchlist-only, got {premarket_alert}')
    if 'stale_snapshot_live_setup_block' not in (premarket_alert.get('block_reasons') or []):
        return _fail('premarket stale data must block live setup explicitly')

    from backend.runtime.pipeline_stage_log import _filter_active_stalls

    active = _filter_active_stalls(
        ['scanner', 'aggregation', 'snapshot_export'],
        snapshot_age_minutes=86,
        after_hours=True,
    )
    if active:
        return _fail(f'closed-market stage filtering should suppress historical scanner/snapshot stalls, got {active}')

    active_failure = _filter_active_stalls(
        ['snapshot_export'],
        snapshot_age_minutes=86,
        after_hours=True,
        stage_rows={'snapshot_export': {'status': 'error', 'detail': 'active refresh failed'}},
    )
    if active_failure != ['snapshot_export']:
        return _fail('active refresh failures must remain visible during closed market')

    from backend.runtime.pipeline_stage_log import get_pipeline_stage_summary

    old_stage_state = {
        'stages': {
            'snapshot_export': {
                'status': 'ok',
                'at_unix': time.time() - 7200,
                'last_success_unix': time.time() - 7200,
            }
        },
        'last_stage': 'snapshot_export',
    }
    with patch('backend.runtime.pipeline_stage_log._load_state', return_value=old_stage_state):
        closed_pipeline = get_pipeline_stage_summary(snapshot_age_minutes=86, after_hours=True)
        if closed_pipeline.get('any_stalled') or 'snapshot_export' in (closed_pipeline.get('stalled_stages') or []):
            return _fail('closed-market snapshot_export:sla_exceeded must be warning-only')
        live_pipeline = get_pipeline_stage_summary(snapshot_age_minutes=86, after_hours=False)
        if 'snapshot_export' not in (live_pipeline.get('stalled_stages') or []):
            return _fail('market-hours snapshot_export:sla_exceeded must remain blocking')

    active_fresh = _filter_active_stalls(
        ['aggregation', 'synthesis', 'telegram'],
        snapshot_age_minutes=0,
        after_hours=False,
    )
    if active_fresh:
        return _fail('fresh snapshot should suppress downstream historical stalls')

    from backend.runtime.scanner_heartbeat_monitor import evaluate_scanner_health

    with (
        patch('backend.runtime.scanner_heartbeat_monitor._scanner_file_age_minutes', return_value=300),
        patch('backend.runtime.scanner_heartbeat_monitor._heartbeat_age_minutes', return_value=300),
        patch(
            'backend.utils.market_hours.get_operational_status',
            return_value={'expect_quiet_collectors': True, 'market_hours': False},
        ),
    ):
        scanner = evaluate_scanner_health()
        if scanner.get('stalled') or not scanner.get('healthy'):
            return _fail('quiet-period scanner should report idle/healthy, not stalled')

    from backend.runtime.snapshot_freshness_monitor import evaluate_snapshot_freshness

    with (
        patch('backend.runtime.snapshot_freshness_monitor._snapshot_age_minutes_direct', return_value=86),
        patch('backend.runtime.snapshot_freshness_monitor._pipeline_stalled', return_value=False),
        patch('backend.runtime.snapshot_freshness_monitor._load_heartbeats', return_value={'sources': {}}),
        patch(
            'backend.runtime.snapshot_freshness_monitor._closed_market_context',
            return_value={'closed': True, 'period': 'weekend', 'state': 'WEEKEND'},
        ),
    ):
        closed_freshness = evaluate_snapshot_freshness()
    if closed_freshness.get('degraded') or closed_freshness.get('stale'):
        return _fail(f'closed-market snapshot_age=86m should not degrade runtime: {closed_freshness}')
    if not closed_freshness.get('closed_market_aging'):
        return _fail('closed-market snapshot_age=86m should carry closed_market_aging warning')

    with (
        patch('backend.runtime.snapshot_freshness_monitor._snapshot_age_minutes_direct', return_value=86),
        patch('backend.runtime.snapshot_freshness_monitor._pipeline_stalled', return_value=False),
        patch('backend.runtime.snapshot_freshness_monitor._load_heartbeats', return_value={'sources': {}}),
        patch(
            'backend.runtime.live_lite_snapshot.maybe_publish_live_lite_snapshot',
            return_value={'ok': False, 'skipped': True, 'reason': 'test_disabled', 'ai_calls': 0},
        ),
        patch(
            'backend.runtime.snapshot_freshness_monitor._closed_market_context',
            return_value={'closed': False, 'period': 'market', 'state': 'INDIA_MARKET_HOURS'},
        ),
    ):
        live_freshness = evaluate_snapshot_freshness()
    if not live_freshness.get('degraded') or not live_freshness.get('stale'):
        return _fail('market-hours snapshot_age=86m must remain degraded/stale')

    from backend.orchestration.telegram_review import normalize_review_snapshot
    from backend.runtime.market_snapshot import MarketSnapshot

    stale_review = MarketSnapshot(
        snapshot_id='old',
        generated_at='2026-06-02T15:46:56+05:30',
        runtime_state={'primary_state': 'LIVE'},
        freshness={'age_minutes': 0, 'health_tier': 'healthy', 'stale': False},
        pipeline_health={'stalled_stages': []},
    )
    current_runtime = {
        'primary_state': 'DEGRADED',
        'lifecycle': {'lifecycle_state': 'DEGRADED'},
        'snapshot_freshness': {
            'age_minutes': 212,
            'age_display': '3h 32m',
            'health_tier': 'stale',
            'stale': True,
            'degraded': True,
        },
        'pipeline': {
            'stalled_stages': ['scanner'],
            'any_stalled': True,
            'last_stage': 'cache',
            'stages': {'scanner': {'age_minutes': 212}},
        },
        'scanner_health': {'display': 'Scanner stalled: 3h', 'stalled': True},
        'secondary_flags': {'stale_snapshot': True, 'scanner_stalled': True},
        'alert_eligibility': {'block_reasons': ['stale_snapshot']},
        'intelligence_status': {'degraded': True, 'message': 'Snapshot stale'},
        'stall_watchdog': {'issues': ['scanner_stalled']},
        'collector_activity': {'collectors_active': False},
        'metrics': {},
        'quality_score': {},
    }

    with patch('backend.runtime.runtime_state.build_runtime_state', return_value=current_runtime):
        normalized = normalize_review_snapshot(stale_review)

    if not normalized:
        return _fail('normalize_review_snapshot returned None')
    if (normalized.runtime_state or {}).get('primary_state') != 'DEGRADED':
        return _fail('/review did not overlay current primary_state')
    if (normalized.freshness or {}).get('age_minutes') != 212:
        return _fail('/review reused stale embedded freshness age')
    if (normalized.pipeline_health or {}).get('stalled_stages') != ['scanner']:
        return _fail('/review did not overlay current pipeline health')
    if 'scanner_stalled' not in (normalized.blockers or []):
        return _fail('/review blockers missing current scanner_stalled flag')

    from backend.intelligence import active_snapshot
    from backend.runtime.snapshot_freshness_monitor import evaluate_snapshot_freshness

    now = datetime.now(active_snapshot.IST)
    fresh_ts = now.isoformat()
    stale_ts = (now - timedelta(hours=4)).isoformat()

    with TemporaryDirectory() as td:
        temp_root = Path(td)
        active_path = temp_root / 'active_snapshot.json'
        current_path = temp_root / 'runtime' / 'current_snapshot.json'
        _write_json(
            active_path,
            {
                'active_snapshot_id': 'snap_stale_active',
                'snapshot_id': 'snap_stale_active',
                'snapshot_version': 8,
                'published_at': stale_ts,
                'sector_rotation': {'bullish': ['OLD']},
            },
        )
        _write_json(
            current_path,
            {
                'snapshot_id': 'snap_fresh_current',
                'generated_at': fresh_ts,
                'published_at': fresh_ts,
                '_committed_at': fresh_ts,
                'sector_rotation': {'bullish': ['IT']},
                'market_mood': {'india_bias': 'constructive'},
                'top_opportunities': [{'symbol': 'TEST'}],
                'action_plan': 'Monitor confirmed setups',
                'intelligence': {'cycle_id': 'cycle_fresh_current'},
            },
        )

        original_active_path = active_snapshot.ACTIVE_SNAPSHOT_FILE
        original_current_path = active_snapshot.CURRENT_SNAPSHOT_FILE
        try:
            active_snapshot.ACTIVE_SNAPSHOT_FILE = active_path
            active_snapshot.CURRENT_SNAPSHOT_FILE = current_path

            bridged = active_snapshot.load_active_snapshot()
            if bridged.get('snapshot_id') != 'snap_fresh_current':
                return _fail('active snapshot bridge did not prefer fresher current_snapshot')
            meta = active_snapshot.get_active_snapshot_meta()
            if meta.get('snapshot_id') != 'snap_fresh_current':
                return _fail('active_snapshot_meta diverged from fresher current_snapshot')
            if active_snapshot.snapshot_age_minutes() is None or active_snapshot.snapshot_age_minutes() > 1:
                return _fail('active_snapshot freshness did not follow fresh current_snapshot')

            with (
                patch('backend.runtime.snapshot_freshness_monitor._pipeline_stalled', return_value=False),
                patch('backend.runtime.snapshot_freshness_monitor._load_heartbeats', return_value={'sources': {}}),
                patch(
                    'backend.runtime.live_lite_snapshot.maybe_publish_live_lite_snapshot',
                    return_value={'ok': False, 'skipped': True, 'reason': 'test_disabled', 'ai_calls': 0},
                ),
            ):
                freshness = evaluate_snapshot_freshness()
            if freshness.get('stale') or freshness.get('age_minutes') is None or freshness.get('age_minutes') > 1:
                return _fail('runtime freshness source stayed stale despite fresh current_snapshot')
        finally:
            active_snapshot.ACTIVE_SNAPSHOT_FILE = original_active_path
            active_snapshot.CURRENT_SNAPSHOT_FILE = original_current_path

    from backend.runtime.market_snapshot import MarketSnapshot
    from backend.runtime.market_snapshot_engine import commit_market_snapshot
    from backend.utils import config as cfg

    with TemporaryDirectory() as td:
        temp_root = Path(td)
        active_path = temp_root / 'active_snapshot.json'
        current_path = temp_root / 'runtime' / 'current_snapshot.json'
        original_active_path = active_snapshot.ACTIVE_SNAPSHOT_FILE
        original_current_path = active_snapshot.CURRENT_SNAPSHOT_FILE
        original_cfg_current_path = cfg.CURRENT_SNAPSHOT_FILE
        try:
            active_snapshot.ACTIVE_SNAPSHOT_FILE = active_path
            active_snapshot.CURRENT_SNAPSHOT_FILE = current_path
            cfg.CURRENT_SNAPSHOT_FILE = current_path
            snapshot = MarketSnapshot(
                snapshot_id='snap_commit_bridge',
                generated_at=fresh_ts,
                sector_rotation={'bullish': ['IT']},
                market_mood={'india_bias': 'constructive'},
                top_opportunities=[{'symbol': 'TEST'}],
                action_plan='Monitor confirmed setups',
                intelligence={'cycle_id': 'cycle_commit_bridge'},
            )
            with (
                patch('backend.runtime.snapshot_freshness_monitor.record_collector_heartbeat'),
                patch(
                    'backend.storage.runtime_snapshot_memory_capture.capture_after_snapshot_publish',
                    return_value={'ok': True},
                ),
            ):
                commit_market_snapshot(snapshot)

            if not current_path.exists():
                return _fail('commit_market_snapshot did not write current_snapshot')
            if not active_path.exists():
                return _fail('commit_market_snapshot did not sync active_snapshot')
            current_payload = json.loads(current_path.read_text(encoding='utf-8'))
            active_payload = json.loads(active_path.read_text(encoding='utf-8'))
            if active_payload.get('snapshot_id') != current_payload.get('snapshot_id'):
                return _fail('active_snapshot sync did not mirror current snapshot id')
            if active_payload.get('published_at') != current_payload.get('published_at'):
                return _fail('active_snapshot sync did not mirror current snapshot timestamp')
            if active_payload.get('source') != 'market_snapshot_commit':
                return _fail('active_snapshot sync source is not market_snapshot_commit')
        finally:
            active_snapshot.ACTIVE_SNAPSHOT_FILE = original_active_path
            active_snapshot.CURRENT_SNAPSHOT_FILE = original_current_path
            cfg.CURRENT_SNAPSHOT_FILE = original_cfg_current_path

    print('RUNTIME_HEALTH_COHERENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
