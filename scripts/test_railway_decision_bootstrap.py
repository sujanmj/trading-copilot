#!/usr/bin/env python3
"""
Unit tests for Railway decision bootstrap (Stage 46F).

Usage:
  python scripts/test_railway_decision_bootstrap.py

Prints RAILWAY_DECISION_BOOTSTRAP_TEST_OK on success.
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

STAGE_MARKER = 'RAILWAY_STAGE_46F_DECISION_BOOTSTRAP'

FORBIDDEN_TELEGRAM = (
    'Run python scripts',
    'python scripts\\generate_final_confidence',
    'python scripts/generate_final_confidence',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_DECISION_BOOTSTRAP_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def test_module_wiring() -> str | None:
    path = PROJECT_ROOT / 'backend/analytics/railway_decision_bootstrap.py'
    if not path.is_file():
        return 'railway_decision_bootstrap.py missing'
    src = path.read_text(encoding='utf-8')
    for fragment in (
        '[RAILWAY_DECISION_BOOTSTRAP]',
        'final_confidence=',
        'stock_decision_today=',
        'stock_decision_tomorrow=',
        'WARMING_MESSAGE',
        'start_background_bootstrap_if_needed',
        'ensure_decision_cache_for_command',
        'run_railway_bootstrap_reports',
    ):
        if fragment not in src:
            return f'bootstrap module missing: {fragment}'
    web = (PROJECT_ROOT / 'scripts/run_railway_web.py').read_text(encoding='utf-8')
    if 'start_background_report_bootstrap' not in web:
        return 'run_railway_web missing background bootstrap'
    fmt = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'repair_decision_for_telegram' not in fmt:
        return 'response_format missing lazy bootstrap hook'
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
    return None


def test_build_info_stage() -> str | None:
    api = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for fragment in (
        "'stage': '46F'",
        "'decision_bootstrap': 'enabled'",
        "'data_preserved': data_preserved()",
    ):
        if fragment not in api:
            return f'build-info missing {fragment}'
    return None


def test_bootstrap_skip_fresh() -> str | None:
    from backend.analytics import railway_decision_bootstrap as mod

    if mod.decision_cache_needs_bootstrap():
        return None
    result = mod.run_railway_decision_bootstrap(force=False, timeout_sec=5)
    if not (result.get('skipped') and result.get('ok')):
        return f'expected skipped fresh-cache result, got {result}'
    return None


def test_warming_messages() -> str | None:
    from backend.analytics.railway_decision_bootstrap import (
        no_candidate_message,
        warming_message,
    )

    if '1–2 minutes' not in warming_message() and '1-2 minutes' not in warming_message():
        return 'warming_message missing retry hint'
    if '/aihub market' not in no_candidate_message():
        return 'no_candidate_message missing aihub hint'
    return None


def main() -> int:
    tests = (
        test_module_wiring,
        test_no_run_python_in_telegram_sources,
        test_build_info_stage,
        test_bootstrap_skip_fresh,
        test_warming_messages,
    )
    for test_fn in tests:
        err = test_fn()
        if err:
            return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_DECISION_BOOTSTRAP_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
