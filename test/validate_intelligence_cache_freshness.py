#!/usr/bin/env python3
"""Validate Issue 1 intelligence cache freshness wiring."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(message: str) -> int:
    print(f'INTELLIGENCE_CACHE_FRESHNESS_FAIL: {message}', file=sys.stderr)
    return 1


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding='utf-8')


def _assert_source_wiring() -> None:
    listener = _read('backend/orchestration/telegram_listener.py')
    for needle in (
        '_refresh_intelligence_caches_for_full_refresh',
        '[REFRESH_CACHE]',
        'publish_runtime_snapshot_wrapper',
        'refresh_theme_catalyst_cache',
        'refresh_budget_intel',
        'build_catalyst_radar',
        'build_aihub_tab_payload',
        "('brain', 'govt', 'market')",
    ):
        if needle not in listener:
            raise AssertionError(f'refresh wiring missing {needle!r}')

    runtime_state = _read('backend/runtime/runtime_state.py')
    for needle in (
        '_load_intelligence_freshness',
        "'intelligence_freshness': intelligence_freshness",
        'aihub_tabs',
        'runtime_snapshot',
        'legacy_report',
        'not refreshed by full refresh',
        'static_wishlist',
        'stock_catalyst_radar_latest.json',
    ):
        if needle not in runtime_state:
            raise AssertionError(f'runtime freshness missing {needle!r}')

    response_format = _read('backend/telegram/response_format.py')
    for needle in (
        '<b>Core runtime freshness</b>',
        '<b>Intelligence freshness</b>',
        'AIHub brain cache',
        'AIHub govt cache',
        'AIHub market cache',
        '_format_runtime_snapshot_freshness_line',
        '_format_optional_broker_freshness_line',
        '_format_static_theme_freshness_line',
    ):
        if needle not in response_format:
            raise AssertionError(f'status response missing {needle!r}')


def _assert_formatter_sections() -> None:
    from backend.telegram.formatting.telegram_formatter import format_status

    state = {
        'primary_state': 'AFTER_HOURS',
        'lifecycle': {'lifecycle_state': 'AFTER_HOURS'},
        'session': {'session_display': 'Weekend research mode', 'after_hours_mode': True},
        'snapshot_freshness': {'age_display': '4m', 'health_tier': 'healthy', 'stale': False},
        'telegram_metrics': {'alerts_sent_today': 0, 'suppressed_today': 0},
        'provider_health': {'status': 'ok'},
        'scheduler': {'phase': 'RUNNING'},
        'scanner_health': {'display': 'Scanner: fresh - 1m'},
        'pipeline': {'stalled_stages': [], 'last_stage': 'cache'},
        'prediction_counts': {'pending': 0, 'resolved': 0, 'wins': 0, 'losses': 0, 'partials': 0},
        'win_rate': {'win_rate_display': 'Awaiting statistical confidence'},
        'alert_eligibility': {'eligible': True, 'execution_eligible': False, 'block_reasons': []},
        'source_freshness': {'scanner': {'status': 'fresh', 'age_display': '1m', 'stale': False}},
        'brain_age': {'age_display': '1m', 'stale': False},
        'secondary_flags': {},
        'metrics': {},
        'intelligence_freshness': {
            'rows': {
                'legacy_report': {'status': 'stale', 'age_display': '602h', 'stale': True},
                'news': {'status': 'stale', 'age_display': '27h', 'stale': True},
                'budget': {'status': 'fresh', 'age_display': '1m', 'stale': False},
                'theme': {'status': 'static_wishlist', 'age_display': 'static wishlist', 'stale': False},
                'catalysts': {'status': 'fresh', 'age_display': '1m', 'stale': False},
                'aihub_brain': {'status': 'fresh', 'age_display': '1m', 'stale': False},
                'aihub_govt': {'status': 'fresh', 'age_display': '1m', 'stale': False},
                'aihub_market': {'status': 'fresh', 'age_display': '1m', 'stale': False},
                'broker': {
                    'status': 'optional',
                    'age_display': 'not refreshed by full refresh',
                    'stale': False,
                    'reason': 'not refreshed by full refresh',
                },
            },
        },
    }
    text = format_status(state)
    for needle in (
        '<b>Core runtime freshness</b>',
        '<b>Intelligence freshness</b>',
        'Runtime snapshot: 4m (fresh)',
        'News: 27h (stale)',
        'Theme catalysts: static wishlist',
        'AIHub brain: 1m (fresh)',
        '<b>Optional</b>',
        'Legacy report cache: 602h (stale)',
        'Broker: optional / not refreshed by full refresh',
    ):
        if needle not in text:
            raise AssertionError(f'formatted status missing {needle!r}')
    if 'State: <code>DEGRADED</code>' in text:
        raise AssertionError('optional stale intelligence must not force DEGRADED status text')
    core_block = text.split('<b>Intelligence freshness</b>', 1)[0]
    if 'Report: 602h' in core_block or 'Legacy report cache: 602h' in core_block:
        raise AssertionError('core runtime freshness must not use stale legacy report cache')


def _assert_static_theme_helper() -> None:
    from backend.telegram.response_format import (
        _format_optional_broker_freshness_line,
        _format_runtime_snapshot_freshness_line,
        _format_static_theme_freshness_line,
    )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'theme_baskets.json'
        path.write_text(
            json.dumps({'generated_at': '2026-01-01T09:00:00+05:30', 'baskets': []}),
            encoding='utf-8',
        )
        line = _format_static_theme_freshness_line(path)
    if line != 'Legacy theme cache: static wishlist':
        raise AssertionError(f'static theme helper returned {line!r}')

    with tempfile.TemporaryDirectory() as tmp:
        data_root = Path(tmp) / 'data'
        runtime_path = data_root / 'cache' / 'runtime_snapshot.json'
        report_path = data_root / 'daily_report_pack_latest.json'
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(json.dumps({'ok': True}), encoding='utf-8')
        report_path.write_text(
            json.dumps({'generated_at': '2026-01-01T09:00:00+05:30'}),
            encoding='utf-8',
        )

        import backend.storage.data_paths as dp

        orig_root = dp.get_data_root
        dp.get_data_root = lambda: data_root  # type: ignore[method-assign]
        try:
            runtime_line = _format_runtime_snapshot_freshness_line(fallback_report_path=report_path)
        finally:
            dp.get_data_root = orig_root  # type: ignore[method-assign]
    if not runtime_line.startswith('Runtime snapshot: fresh'):
        raise AssertionError(f'runtime snapshot helper used stale fallback: {runtime_line!r}')
    if '602h' in runtime_line or 'stale' in runtime_line:
        raise AssertionError(f'runtime snapshot helper must not surface stale legacy report: {runtime_line!r}')

    broker_line = _format_optional_broker_freshness_line()
    if broker_line != 'Broker: optional / not refreshed by full refresh':
        raise AssertionError(f'broker optional helper returned {broker_line!r}')


def main() -> int:
    try:
        _assert_source_wiring()
        _assert_formatter_sections()
        _assert_static_theme_helper()
    except Exception as exc:
        return _fail(str(exc))
    print('INTELLIGENCE_CACHE_FRESHNESS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
