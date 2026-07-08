#!/usr/bin/env python3
"""Phase 4B.16 — Safe Telegram /qa command and allowlisted test runner."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'QA_COMMAND_4B16_FAIL: {msg}', file=sys.stderr)
    return 1


def test_qa_menu() -> int:
    from backend.telegram.lazy_command_runner import run_qa_only

    result = run_qa_only('')
    text = result.get('text') or ''
    for needle in (
        'QA — AstraEdge',
        '/qa smoke — fast safe checks',
        '/qa full — safe regression suite',
        '/qa last — last QA result',
        '/qa explain — what QA covers',
    ):
        if needle not in text:
            return _fail(f'/qa menu missing {needle!r}')
    return 0


def test_qa_explain() -> int:
    from backend.telegram.lazy_command_runner import run_qa_only

    text = run_qa_only('explain').get('text') or ''
    lowered = text.lower()
    for needle in (
        'command routing',
        'chart patterns',
        'candle memory',
        'does not place trades',
        'does not call ai',
        'paper/research system validation only',
    ):
        if needle not in lowered:
            return _fail(f'/qa explain missing {needle!r}')
    return 0


def test_allowlisted_scripts_only() -> int:
    from backend.qa import qa_runner

    allowed = qa_runner.ALL_SCRIPT_ALLOWLIST
    for _, script_rel in qa_runner.SMOKE_SCRIPT_ALLOWLIST + qa_runner.FULL_SCRIPT_ALLOWLIST:
        if script_rel not in allowed:
            return _fail(f'{script_rel} missing from allowlist')

    blocked = qa_runner._execute_script('blocked', 'scripts/evil_custom_test.py', timeout=5)
    if blocked.get('status') != 'FAIL':
        return _fail('non-allowlisted script must fail')
    if 'allowlisted' not in str(blocked.get('summary', '')).lower():
        return _fail('blocked script must explain allowlist rejection')
    return 0


def test_no_shell_true() -> int:
    src = (PROJECT_ROOT / 'backend/qa/qa_runner.py').read_text(encoding='utf-8')
    if 'shell=True' in src:
        return _fail('qa_runner must not use shell=True')
    if 'shell=False' not in src:
        return _fail('qa_runner must pass shell=False explicitly')
    return 0


def test_qa_smoke_pass_mocked() -> int:
    from backend.qa import qa_runner

    def _pass(name: str, script_rel: str, *, timeout: int, smoke_mode: bool = False) -> dict:
        return {
            'name': name,
            'status': 'PASS',
            'duration_seconds': 0.1,
            'summary': 'ok',
        }

    with patch.object(qa_runner, '_execute_script', side_effect=_pass):
        result = qa_runner.run_qa_smoke()
    if result.get('overall_status') != 'PASS':
        return _fail(f'expected PASS got {result.get("overall_status")!r}')
    if result.get('passed_count') != len(qa_runner.SMOKE_SCRIPT_ALLOWLIST):
        return _fail('smoke passed_count mismatch')
    return 0


def test_qa_full_fail_mocked() -> int:
    from backend.qa import qa_runner

    def _mixed(name: str, script_rel: str, *, timeout: int, smoke_mode: bool = False) -> dict:
        if name == 'chart patterns':
            return {
                'name': name,
                'status': 'FAIL',
                'duration_seconds': 0.2,
                'summary': 'assertion failed',
                'error_tail': 'assertion failed in chart patterns',
            }
        return {
            'name': name,
            'status': 'PASS',
            'duration_seconds': 0.1,
            'summary': 'ok',
        }

    with patch.object(qa_runner, '_execute_script', side_effect=_mixed):
        result = qa_runner.run_qa_full()
    if result.get('overall_status') != 'FAIL':
        return _fail('full suite must FAIL when one script fails')
    if result.get('failed_count') != 1:
        return _fail(f'expected 1 failed got {result.get("failed_count")!r}')
    text = qa_runner.format_qa_result(result)
    if 'chart patterns' not in text.lower():
        return _fail('full fail output must name failed script')
    return 0


def test_qa_last_shows_stored_result() -> int:
    from backend.qa import qa_runner
    from backend.telegram.lazy_command_runner import run_qa_only

    sample = {
        'started_at': '2026-05-27T10:00:00+00:00',
        'finished_at': '2026-05-27T10:00:12+00:00',
        'duration_seconds': 12.4,
        'mode': 'smoke',
        'overall_status': 'PASS',
        'passed_count': 3,
        'failed_count': 0,
        'tests': [
            {'name': 'telegram routing', 'status': 'PASS', 'duration_seconds': 1.0, 'summary': 'ok'},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'qa_last_result.json'
        with patch.object(qa_runner, 'QA_LAST_RESULT_PATH', path):
            qa_runner._save_last_result(sample)
            text = run_qa_only('last').get('text') or ''
    if 'QA LAST — SMOKE — PASS' not in text:
        return _fail('/qa last missing stored status header')
    if 'Duration: 12.4s' not in text:
        return _fail('/qa last missing duration')
    return 0


def test_timeout_is_fail() -> int:
    import subprocess

    from backend.qa import qa_runner

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get('timeout', 1))

    with patch('backend.qa.qa_runner.subprocess.run', side_effect=_timeout):
        row = qa_runner._execute_script(
            'telegram routing',
            'scripts/test_telegram_stage_51a_canonical_routing.py',
            timeout=1,
        )
    if row.get('status') != 'FAIL':
        return _fail('timeout must mark script FAIL')
    if 'timeout' not in str(row.get('summary', '')).lower():
        return _fail('timeout summary missing timeout reason')
    return 0


def test_qa_last_result_gitignored() -> int:
    gitignore = (PROJECT_ROOT / '.gitignore').read_text(encoding='utf-8')
    if 'data/qa_last_result.json' not in gitignore:
        return _fail('.gitignore must list data/qa_last_result.json')
    return 0


def test_build_label_51w() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52C' or ASTRAEDGE_BUILD_STAGE != '52C':
        return _fail(f'expected AstraEdge 52C got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def test_regression_prior_phases() -> int:
    from backend.qa.smoke_mode import should_skip_nested_regression

    if should_skip_nested_regression():
        print('SKIP: test_regression_prior_phases (ASTRAEDGE_QA_SMOKE=1)')
        return 0
    scripts = (
        'test_help_chart_patterns_4b15b.py',
        'test_intraday_candle_memory_4b15a.py',
        'test_chart_patterns_4b15.py',
        'test_screener_longterm_polish_4b14b.py',
        'test_screener_import_attachment_4b14a.py',
        'test_tradecard_memory_4b13.py',
    )
    for script in scripts:
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(proc.stdout, file=sys.stderr)
            print(proc.stderr, file=sys.stderr)
            return _fail(f'{script} failed with code {proc.returncode}')
    return 0


def main() -> int:
    tests = [
        test_qa_menu,
        test_qa_explain,
        test_allowlisted_scripts_only,
        test_no_shell_true,
        test_qa_smoke_pass_mocked,
        test_qa_full_fail_mocked,
        test_qa_last_shows_stored_result,
        test_timeout_is_fail,
        test_qa_last_result_gitignored,
        test_build_label_51w,
        test_regression_prior_phases,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print(f'ALL {len(tests)} QA_COMMAND_4B16 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
