#!/usr/bin/env python3
"""Validate Issue 1 intelligence cache freshness wiring."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
IST = ZoneInfo('Asia/Kolkata')


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

    budget_impact = _read('backend/analytics/budget_impact.py')
    for needle in (
        "CACHE_FILE = get_data_path('budget_impact_cache.json')",
        "payload['cache_path'] = str(CACHE_FILE)",
        '[BUDGET_COMMAND] source=',
        'compute_freshness_panel()',
    ):
        if needle not in budget_impact:
            raise AssertionError(f'budget command wiring missing {needle!r}')

    catalyst_radar = _read('backend/intelligence/stock_catalyst_radar.py')
    for needle in (
        "CACHE_FILE = DATA_DIR / 'stock_catalyst_radar_latest.json'",
        "'cache_path': str(CACHE_FILE)",
        '[CATALYST_COMMAND] source=',
        'Fresh cache: no actionable catalysts',
    ):
        if needle not in catalyst_radar:
            raise AssertionError(f'catalyst command wiring missing {needle!r}')

    theme_baskets = _read('backend/analytics/theme_baskets.py')
    for needle in (
        'format_theme_budget_telegram',
        'compute_freshness_panel',
        'Budget cache:',
        'Theme cache:',
    ):
        if needle not in theme_baskets:
            raise AssertionError(f'theme budget wiring missing {needle!r}')


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


def _fake_theme_payload(old_iso: str, fresh_iso: str) -> dict:
    return {
        'generated_at': old_iso,
        'cache_refreshed_at': fresh_iso,
        'baskets': [
            {
                'theme_id': 'infrastructure',
                'display_name': 'Infrastructure',
                'category': 'Government/Budget',
                'stocks': {'direct': ['LT'], 'avoid_or_risk': []},
                'direct_beneficiary_sectors': ['Roads'],
                'indirect_beneficiary_sectors': ['Cement'],
                'raw_material_beneficiaries': [],
                'risk_sectors': [],
            }
        ],
        'catalyst_cache': {
            'infrastructure': [
                {
                    'theme_id': 'infrastructure',
                    'headline': 'Government clears road project package',
                    'impact_10': 7,
                    'catalyst_score': 70,
                    'why': 'fresh policy project',
                    'action': 'watch only',
                    'relevant': True,
                }
            ]
        },
    }


def _assert_budget_commands_use_canonical_refreshed_cache() -> None:
    import backend.analytics.budget_impact as bi
    import backend.analytics.theme_baskets as tb

    old_iso = (datetime.now(IST) - timedelta(hours=300)).replace(microsecond=0).isoformat()
    fresh_iso = datetime.now(IST).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        budget_path = tmp_path / 'budget_impact_cache.json'
        theme_path = tmp_path / 'theme_baskets.json'
        theme_payload = _fake_theme_payload(old_iso, fresh_iso)
        theme_path.write_text(json.dumps(theme_payload), encoding='utf-8')
        budget_path.write_text(
            json.dumps(
                {
                    'ok': True,
                    'generated_at': old_iso,
                    'refreshed_at': fresh_iso,
                    'freshness': {
                        'status': 'stale',
                        'budget_cache': {
                            'timestamp': old_iso,
                            'age_hours': 300,
                            'age_label': '300.0h ago',
                            'status': 'stale',
                        },
                        'theme_cache': {
                            'timestamp': old_iso,
                            'age_hours': 300,
                            'age_label': '300.0h ago',
                            'status': 'stale',
                        },
                    },
                    'top_themes': [{'theme_id': 'infrastructure', 'display_name': 'Infrastructure', 'budget_impact_score': 70}],
                    'top_catalysts': [],
                    'beneficiary_map': {},
                    'risk_map': {},
                    'stock_rankings': [],
                    'source_counts': {'themes': 1, 'budget_themes': 1, 'catalysts': 1},
                },
                default=str,
            ),
            encoding='utf-8',
        )

        original_budget_cache = bi.CACHE_FILE
        original_theme_file = tb.BASKETS_FILE
        original_budget_ids = tb.BUDGET_THEME_IDS
        try:
            bi.CACHE_FILE = budget_path
            tb.BASKETS_FILE = theme_path
            tb.BUDGET_THEME_IDS = ('infrastructure',)

            fresh = bi.compute_freshness_panel()
            if fresh.get('budget_cache', {}).get('status') != 'fresh':
                raise AssertionError(f'budget canonical cache not fresh: {fresh.get("budget_cache")}')
            if fresh.get('theme_cache', {}).get('status') != 'fresh':
                raise AssertionError(f'budget theme canonical cache not fresh: {fresh.get("theme_cache")}')

            budget_text = bi.handle_budget_command('overview')
            if '300.0h ago' in budget_text or 'Budget cache: 300' in budget_text:
                raise AssertionError('budget command used stale embedded freshness instead of canonical refreshed_at')
            if 'Budget cache: 0m ago' not in budget_text or 'Theme cache: 0m ago' not in budget_text:
                raise AssertionError(f'budget command did not show fresh canonical cache: {budget_text}')

            theme_text = tb.format_theme_budget_telegram()
            if '300.0h ago' in theme_text or 'stale' in theme_text.lower():
                raise AssertionError('theme budget command surfaced stale legacy cache despite fresh canonical cache')
            if 'Budget cache: 0m ago' not in theme_text or 'Theme cache: 0m ago' not in theme_text:
                raise AssertionError(f'theme budget command did not use canonical budget freshness: {theme_text}')
        finally:
            bi.CACHE_FILE = original_budget_cache
            tb.BASKETS_FILE = original_theme_file
            tb.BUDGET_THEME_IDS = original_budget_ids


def _assert_catalysts_today_uses_canonical_radar_cache() -> None:
    import backend.intelligence.stock_catalyst_radar as scr

    fresh_iso = datetime.now(IST).replace(microsecond=0).isoformat()
    with tempfile.TemporaryDirectory() as tmp:
        catalyst_path = Path(tmp) / 'stock_catalyst_radar_latest.json'
        catalyst_path.write_text(
            json.dumps({
                'ok': True,
                'session_date': scr._today(),
                'generated_at': fresh_iso,
                'cache_path': str(catalyst_path),
                'items': [],
                'priority_list': [],
                'bullish_watch': [],
            }),
            encoding='utf-8',
        )
        original_cache = scr.CACHE_FILE
        try:
            scr.CACHE_FILE = catalyst_path
            text = scr.format_catalyst_radar_telegram(today_only=True)
            if 'check again after news refresh' in text:
                raise AssertionError('catalysts today still uses stale/missing wording for fresh canonical cache')
            if 'Fresh cache: no actionable catalysts for today.' not in text:
                raise AssertionError(f'catalysts today did not read canonical radar cache: {text}')
        finally:
            scr.CACHE_FILE = original_cache


def main() -> int:
    try:
        _assert_source_wiring()
        _assert_formatter_sections()
        _assert_static_theme_helper()
        _assert_budget_commands_use_canonical_refreshed_cache()
        _assert_catalysts_today_uses_canonical_radar_cache()
    except Exception as exc:
        return _fail(str(exc))
    print('INTELLIGENCE_CACHE_FRESHNESS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
