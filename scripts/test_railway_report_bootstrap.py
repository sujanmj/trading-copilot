#!/usr/bin/env python3
"""
Unit tests for Railway report bootstrap (Stage 46F).

Usage:
  python scripts/test_railway_report_bootstrap.py

Prints RAILWAY_REPORT_BOOTSTRAP_TEST_OK on success.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46F_LIVE_DATA_BOOTSTRAP'

FORBIDDEN_TELEGRAM = (
    'Run python scripts',
    'python scripts\\generate_final_confidence',
    'python scripts/generate_final_confidence',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_REPORT_BOOTSTRAP_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def test_bootstrap_script_exists() -> str | None:
    script = PROJECT_ROOT / 'scripts/railway_bootstrap_reports.py'
    if not script.is_file():
        return 'scripts/railway_bootstrap_reports.py missing'
    src = script.read_text(encoding='utf-8')
    for fragment in (
        'RAILWAY_BOOTSTRAP_REPORTS_OK',
        'run_railway_bootstrap_reports',
        'get_data_root',
        'log_data_startup',
    ):
        if fragment not in src:
            return f'railway_bootstrap_reports.py missing: {fragment}'
    return None


def test_module_wiring() -> str | None:
    path = PROJECT_ROOT / 'backend/analytics/railway_decision_bootstrap.py'
    if not path.is_file():
        return 'railway_decision_bootstrap.py missing'
    src = path.read_text(encoding='utf-8')
    for fragment in (
        'run_railway_bootstrap_reports',
        'tomorrow_watchlist',
        'stock_decision_today=',
        'stock_decision_tomorrow=',
        'format_watchlist_fallback_telegram',
        'repair_decision_for_telegram',
        'start_background_report_bootstrap',
        'RAILWAY_REPORT_BOOTSTRAP_STARTED',
        'Decision file was missing, rebuilt from Railway cache.',
        'No clean candidate. Use /aihub market and /news.',
        'market_memory_dashboard',
        'start_background_bootstrap_reports',
        'RAILWAY_BOOTSTRAP_REPORTS_OK',
    ):
        if fragment not in src:
            return f'bootstrap module missing: {fragment}'
    web = (PROJECT_ROOT / 'scripts/run_railway_web.py').read_text(encoding='utf-8')
    if 'start_background_report_bootstrap' not in web:
        return 'run_railway_web missing background report bootstrap'
    return None


def test_no_run_python_in_telegram_sources() -> str | None:
    paths = (
        PROJECT_ROOT / 'backend/telegram/response_format.py',
        PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py',
        PROJECT_ROOT / 'backend/analytics/stock_decision_engine.py',
        PROJECT_ROOT / 'backend/analytics/final_confidence_report_loader.py',
    )
    for path in paths:
        src = path.read_text(encoding='utf-8')
        for phrase in FORBIDDEN_TELEGRAM:
            if phrase in src:
                return f'{path.name} still contains {phrase!r}'

    today = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'format_stock_decision_telegram' not in today:
        return 'response_format missing format_stock_decision_telegram'
    if 'repair_decision_for_telegram' not in today:
        return 'response_format missing repair_decision_for_telegram hook'
    if 'format_action_plan_telegram' not in today:
        return 'response_format missing format_action_plan_telegram'
    return None


def test_build_info_stage() -> str | None:
    api = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for fragment in (
        "'stage': '46F'",
        "'report_bootstrap': 'enabled'",
        "'data_preserved': data_preserved()",
    ):
        if fragment not in api:
            return f'build-info missing {fragment}'
    return None


def test_memory_wording() -> str | None:
    mem = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    if 'Cloud memory is collecting outcomes. Local historical memory may differ.' not in mem:
        return 'run_memory_only missing cloud memory wording'
    return None


def test_aihub_brain_fallback() -> str | None:
    src = (PROJECT_ROOT / 'backend/analytics/aihub_tab_payloads.py').read_text(encoding='utf-8')
    if 'Runtime snapshot missing; using report cache.' not in src:
        return 'build_brain_payload missing runtime snapshot fallback message'
    if 'runtime_snapshot_missing' not in src:
        return 'build_brain_payload missing snapshot_limited detection'
    fmt = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'Runtime snapshot missing; using report cache.' not in fmt:
        return 'format_aihub_payload missing brain fallback display'
    return None


def test_bootstrap_skip_fresh() -> str | None:
    from backend.analytics import railway_decision_bootstrap as mod

    if mod.report_cache_needs_bootstrap():
        return None
    result = mod.run_railway_bootstrap_reports(force=False, timeout_sec=5)
    if not (result.get('skipped') and result.get('ok')):
        return f'expected skipped fresh-cache result, got {result}'
    return None


def test_telegram_formatters_no_script_instructions() -> str | None:
    from backend.telegram.response_format import (
        format_action_plan_telegram,
        format_stock_decision_telegram,
    )

    for label, text_fn in (
        ('today', lambda: format_stock_decision_telegram('today')),
        ('tomorrow', lambda: format_stock_decision_telegram('tomorrow')),
        ('action_plan', format_action_plan_telegram),
    ):
        text = text_fn()
        for phrase in FORBIDDEN_TELEGRAM:
            if phrase in text:
                return f'{label} formatter still contains {phrase!r}'
    return None


def main() -> int:
    tests = (
        test_bootstrap_script_exists,
        test_module_wiring,
        test_no_run_python_in_telegram_sources,
        test_build_info_stage,
        test_memory_wording,
        test_aihub_brain_fallback,
        test_bootstrap_skip_fresh,
        test_telegram_formatters_no_script_instructions,
    )
    for test_fn in tests:
        err = test_fn()
        if err:
            return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_REPORT_BOOTSTRAP_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
