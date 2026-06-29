#!/usr/bin/env python3
"""Validate live scanner-lite runtime snapshot policy."""

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


def _fail(message: str) -> int:
    print(f'LIVE_LITE_SNAPSHOT_FAIL: {message}', file=sys.stderr)
    return 1


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    from backend.intelligence import active_snapshot
    from backend.runtime import ai_confirmation_gate as gate
    from backend.runtime import live_lite_snapshot as lite
    from backend.runtime import pipeline_stage_log
    from backend.runtime import runtime_state as rs
    from backend.runtime import scanner_heartbeat_monitor
    from backend.runtime import snapshot_freshness_monitor as sfm
    from backend.telegram.formatting.telegram_formatter import format_status

    original_paths = {
        'lite_scanner': lite.SCANNER_FILE,
        'lite_market': lite.MARKET_FILE,
        'lite_enriched': lite.ENRICHED_MARKET_FILE,
        'lite_current': lite.CURRENT_SNAPSHOT_FILE,
        'lite_runtime_cache': lite.RUNTIME_SNAPSHOT_CACHE,
        'active_file': active_snapshot.ACTIVE_SNAPSHOT_FILE,
        'active_current': active_snapshot.CURRENT_SNAPSHOT_FILE,
        'scanner_file': scanner_heartbeat_monitor.SCANNER_FILE,
        'heartbeat_file': sfm.HEARTBEAT_FILE,
        'stage_state': pipeline_stage_log._STATE_FILE,
        'stage_log': pipeline_stage_log._LOG_FILE,
        'gate_state': gate.STATE_FILE,
    }

    with TemporaryDirectory() as td:
        root = Path(td)
        data = root / 'data'
        scanner_file = data / 'scanner_data.json'
        market_file = data / 'latest_market_data.json'
        current_file = data / 'runtime' / 'current_snapshot.json'
        runtime_cache = data / 'cache' / 'runtime_snapshot.json'
        active_file = data / 'active_snapshot.json'
        heartbeat_file = data / 'collector_heartbeats.json'
        stage_state = data / 'pipeline_stage_state.json'
        stage_log = root / 'logs' / 'pipeline_stages.log'
        gate_state = data / 'ai_confirmation_gate_state.json'

        try:
            lite.SCANNER_FILE = scanner_file
            lite.MARKET_FILE = market_file
            lite.ENRICHED_MARKET_FILE = data / 'latest_market_data_memory_enriched.json'
            lite.CURRENT_SNAPSHOT_FILE = current_file
            lite.RUNTIME_SNAPSHOT_CACHE = runtime_cache
            active_snapshot.ACTIVE_SNAPSHOT_FILE = active_file
            active_snapshot.CURRENT_SNAPSHOT_FILE = current_file
            scanner_heartbeat_monitor.SCANNER_FILE = scanner_file
            sfm.HEARTBEAT_FILE = heartbeat_file
            pipeline_stage_log._STATE_FILE = stage_state
            pipeline_stage_log._LOG_FILE = stage_log
            gate.STATE_FILE = gate_state

            old_ts = (datetime.now(active_snapshot.IST) - timedelta(minutes=20)).isoformat()
            _write_json(
                active_file,
                {
                    'active_snapshot_id': 'old_snapshot',
                    'snapshot_id': 'old_snapshot',
                    'snapshot_version': 1,
                    'published_at': old_ts,
                    'top_opportunities': [],
                },
            )
            _write_json(
                scanner_file,
                {
                    'generated_at': datetime.now(active_snapshot.IST).isoformat(),
                    'top_signals': [
                        {
                            'symbol': 'AAA',
                            'score': 82,
                            'direction': 'BULLISH',
                            'price': 101.5,
                            'volume_ratio': 2.4,
                            'logic': 'fresh scanner setup',
                        },
                        {
                            'symbol': 'RISKY',
                            'score': 70,
                            'direction': 'BEARISH',
                            'action': 'AVOID',
                        },
                    ],
                },
            )
            _write_json(
                market_file,
                {
                    'generated_at': datetime.now(active_snapshot.IST).isoformat(),
                    'stocks': [{'symbol': 'AAA', 'last_price': 101.5, 'volume_ratio': 2.4}],
                },
            )

            live_op = {
                'market_hours': True,
                'period': 'market',
                'canonical_lifecycle': 'INDIA_MARKET_HOURS',
            }
            with (
                patch('backend.utils.market_hours.get_operational_status', return_value=live_op),
                patch('backend.runtime.live_lite_snapshot._optional_stale_warnings', return_value=['AIHub stale warning']),
            ):
                freshness = sfm.evaluate_snapshot_freshness()

            if freshness.get('stale') or freshness.get('degraded'):
                return _fail(f'live lite snapshot should clear stale/degraded flags: {freshness}')
            if freshness.get('source') != 'live_lite_scanner':
                return _fail(f'freshness should identify live_lite_scanner source: {freshness}')
            if freshness.get('ai_calls') != 0:
                return _fail(f'live lite snapshot must not report AI calls: {freshness}')
            if not current_file.exists() or not runtime_cache.exists() or not active_file.exists():
                return _fail('lite publish did not write canonical runtime/current/active snapshot files')

            current = _read_json(current_file)
            active = _read_json(active_file)
            if current.get('ai_calls') != 0:
                return _fail('current snapshot should record ai_calls=0')
            if active.get('source') != 'live_lite_scanner':
                return _fail(f'active snapshot was not bridged to live_lite_scanner: {active}')
            if not current.get('top_opportunities') or current['top_opportunities'][0].get('symbol') != 'AAA':
                return _fail('lite snapshot did not carry top scanner candidate')
            if not current.get('risk_list') or current['risk_list'][0].get('symbol') != 'RISKY':
                return _fail('lite snapshot did not carry avoid candidates')

            live_state = rs._map_primary_runtime_state(
                {'lifecycle_state': 'MARKET_ACTIVE', 'after_hours_mode': False},
                {'period': 'market', 'market_hours': True, 'after_hours_mode': False},
                {
                    'age_minutes': 0,
                    'degraded': False,
                    'stale': False,
                    'source': 'live_lite_scanner',
                    'live_lite_snapshot': True,
                },
                {'healthy': True, 'stalled': False, 'age_minutes': 2},
                {'any_stalled': False, 'stalled_stages': []},
            )
            if live_state != 'LIVE':
                return _fail(f'scanner-fresh live lite runtime should be LIVE, got {live_state}')

            stale_scanner_state = rs._map_primary_runtime_state(
                {'lifecycle_state': 'MARKET_ACTIVE', 'after_hours_mode': False},
                {'period': 'market', 'market_hours': True, 'after_hours_mode': False},
                {'age_minutes': 0, 'degraded': False, 'stale': False},
                {'healthy': True, 'stalled': False, 'age_minutes': 6},
                {'any_stalled': False, 'stalled_stages': []},
            )
            if stale_scanner_state != 'DEGRADED':
                return _fail(f'live scanner stale >5m must degrade, got {stale_scanner_state}')

            with patch(
                'backend.orchestration.alert_suppression_log.suppression_summary',
                return_value={'suppression_count': 0, 'by_reason': {}},
            ):
                alert = rs._load_alert_eligibility(
                    {'lifecycle_state': 'MARKET_ACTIVE', 'after_hours_mode': False},
                    {
                        'stale': False,
                        'degraded': False,
                        'source': 'live_lite_scanner',
                        'live_lite_snapshot': True,
                    },
                    {'elite_blocked': False, 'status': 'ready'},
                )
            if not alert.get('eligible') or alert.get('block_reasons'):
                return _fail(f'optional stale intelligence should not block live scanner alerts: {alert}')

            status_text = format_status({
                'primary_state': 'LIVE',
                'lifecycle': {'lifecycle_state': 'MARKET_ACTIVE'},
                'session': {'session_display': 'India market hours', 'after_hours_mode': False},
                'snapshot_freshness': {
                    'age_display': '0m',
                    'health_tier': 'lite from scanner',
                    'stale': False,
                    'source': 'live_lite_scanner',
                    'live_lite_snapshot': True,
                },
                'scanner_health': {'display': 'Scanner: healthy', 'stalled': False},
                'alert_eligibility': alert,
                'telegram_metrics': {'alerts_sent_today': 0, 'suppressed_today': 0},
                'source_freshness': {'scanner': {'age_display': '2s', 'stale': False}},
                'intelligence_freshness': {
                    'rows': {
                        'budget': {'label': 'Budget', 'age_display': '5h', 'status': 'stale', 'stale': True},
                        'aihub_brain': {'label': 'AIHub brain', 'age_display': '5h', 'status': 'stale', 'stale': True},
                    }
                },
                'pipeline': {'stalled_stages': [], 'any_stalled': False},
                'metrics': {},
                'prediction_counts': {},
                'win_rate': {},
                'secondary_flags': {},
                'provider_health': {'status': 'ok'},
                'scheduler': {'phase': 'RUNNING'},
            })
            if 'Runtime snapshot: 0m (fresh/lite from scanner)' not in status_text:
                return _fail(f'/status did not label scanner-lite snapshot: {status_text}')
            if 'Alerts: eligible' not in status_text or '<b>Blockers</b>' in status_text:
                return _fail(f'/status should warn optional stale caches without blocking: {status_text}')

            _write_json(
                gate_state,
                {
                    'last': {
                        'AAA': {
                            'ticker': 'AAA',
                            'score': 80,
                            'direct_catalyst': False,
                            'avoid': False,
                            'last_ai_confirmation_unix': time.time() - 3600,
                        }
                    }
                },
            )
            no_change = gate.evaluate_ai_confirmation_gate(
                {'ticker': 'AAA', 'score': 80},
                cooldown_seconds=900,
                record=False,
            )
            if no_change.get('should_run_ai') or no_change.get('reason') != 'no_material_change':
                return _fail(f'AI gate should skip unchanged candidate: {no_change}')

            _write_json(
                gate_state,
                {
                    'last': {
                        'AAA': {
                            'ticker': 'AAA',
                            'score': 70,
                            'direct_catalyst': False,
                            'avoid': False,
                            'last_ai_confirmation_unix': time.time() - 60,
                        }
                    }
                },
            )
            cooldown = gate.evaluate_ai_confirmation_gate(
                {'ticker': 'AAA', 'score': 85},
                cooldown_seconds=900,
                record=False,
            )
            if cooldown.get('should_run_ai') or cooldown.get('reason') != 'cooldown':
                return _fail(f'AI gate should respect cooldown on material change: {cooldown}')
        finally:
            lite.SCANNER_FILE = original_paths['lite_scanner']
            lite.MARKET_FILE = original_paths['lite_market']
            lite.ENRICHED_MARKET_FILE = original_paths['lite_enriched']
            lite.CURRENT_SNAPSHOT_FILE = original_paths['lite_current']
            lite.RUNTIME_SNAPSHOT_CACHE = original_paths['lite_runtime_cache']
            active_snapshot.ACTIVE_SNAPSHOT_FILE = original_paths['active_file']
            active_snapshot.CURRENT_SNAPSHOT_FILE = original_paths['active_current']
            scanner_heartbeat_monitor.SCANNER_FILE = original_paths['scanner_file']
            sfm.HEARTBEAT_FILE = original_paths['heartbeat_file']
            pipeline_stage_log._STATE_FILE = original_paths['stage_state']
            pipeline_stage_log._LOG_FILE = original_paths['stage_log']
            gate.STATE_FILE = original_paths['gate_state']

    print('LIVE_LITE_SNAPSHOT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
