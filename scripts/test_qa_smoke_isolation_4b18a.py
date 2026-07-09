#!/usr/bin/env python3
"""Phase 4B.18A — /qa smoke isolation and failure reporting."""

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
    print(f'QA_SMOKE_ISOLATION_4B18A_FAIL: {msg}', file=sys.stderr)
    return 1


def test_smoke_runner_sets_qa_smoke_env() -> int:
    from backend.qa import qa_runner
    from backend.qa.smoke_mode import QA_SMOKE_ENV

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured['env'] = dict(kwargs.get('env') or {})
        class _Proc:
            returncode = 0
            stdout = 'ALL OK'
            stderr = ''
        return _Proc()

    script_rel = qa_runner.SMOKE_SCRIPT_ALLOWLIST[0][1]
    with patch('subprocess.run', side_effect=_fake_run):
        qa_runner._execute_script('probe', script_rel, timeout=5, smoke_mode=True)
    env = captured.get('env') or {}
    if env.get(QA_SMOKE_ENV) != '1':
        return _fail(f'smoke runner must set {QA_SMOKE_ENV}=1')
    return 0


def test_full_runner_unsets_qa_smoke_env() -> int:
    from backend.qa import qa_runner
    from backend.qa.smoke_mode import QA_SMOKE_ENV

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured['env'] = dict(kwargs.get('env') or {})
        class _Proc:
            returncode = 0
            stdout = 'ALL OK'
            stderr = ''
        return _Proc()

    script_rel = qa_runner.FULL_SCRIPT_ALLOWLIST[0][1]
    base_env = os.environ.copy()
    base_env[QA_SMOKE_ENV] = '1'
    with patch('subprocess.run', side_effect=_fake_run), patch.dict(os.environ, {QA_SMOKE_ENV: '1'}, clear=False):
        qa_runner._execute_script('probe', script_rel, timeout=5, smoke_mode=False)
    env = captured.get('env') or {}
    if env.get(QA_SMOKE_ENV):
        return _fail('full runner must not pass ASTRAEDGE_QA_SMOKE=1 to child scripts')
    return 0


def test_smoke_skips_nested_regression_in_intraday_script() -> int:
    env = os.environ.copy()
    env['ASTRAEDGE_QA_SMOKE'] = '1'
    env['DISABLE_TELEGRAM'] = '1'
    env['DISABLE_TELEGRAM_SENDS'] = '1'
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / 'test_intraday_candle_memory_4b15a.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    out = (proc.stdout or '') + (proc.stderr or '')
    if 'SKIP: test_regression_prior_phases' not in out:
        return _fail('smoke mode must skip nested regression in intraday candle memory script')
    if 'SCREENER_LONGTERM_POLISH_4B14B_FAIL' in out:
        return _fail('smoke mode must not cascade into screener regression')
    if proc.returncode != 0:
        return _fail(f'intraday smoke run failed: {out[-400:]}')
    return 0


def test_full_mode_runs_nested_regression_hook() -> int:
    import scripts.test_intraday_candle_memory_4b15a as mod

    calls: list[str] = []

    def _fake_regression(script: str) -> int:
        calls.append(script)
        return 0

    old = os.environ.pop('ASTRAEDGE_QA_SMOKE', None)
    try:
        with patch.object(mod, '_run_regression', side_effect=_fake_regression):
            rc = mod.test_regression_prior_phases()
    finally:
        if old is not None:
            os.environ['ASTRAEDGE_QA_SMOKE'] = old
    if rc != 0:
        return _fail('full-mode regression hook must return success when children pass')
    if not calls:
        return _fail('full mode must invoke nested regression scripts')
    return 0


def test_qa_last_reports_script_and_failure_detail() -> int:
    from backend.qa.qa_runner import format_qa_result

    result = {
        'mode': 'smoke',
        'overall_status': 'FAIL',
        'duration_seconds': 3.2,
        'passed_count': 2,
        'failed_count': 1,
        'tests': [
            {'name': 'intraday candle memory', 'status': 'PASS'},
            {
                'name': 'intraday candle memory',
                'script': 'scripts/test_intraday_candle_memory_4b15a.py',
                'status': 'FAIL',
                'failed_test': 'test_patterns_uses_candle_memory',
                'summary': 'patterns command missing header',
                'error_tail': 'INTRADAY_CANDLE_MEMORY_4B15A_FAIL: patterns command missing header',
            },
        ],
    }
    text = format_qa_result(result, detail='last')
    if 'intraday candle memory' not in text:
        return _fail('/qa last must show script label')
    if 'test_patterns_uses_candle_memory' not in text:
        return _fail('/qa last must show failed test name')
    if 'INTRADAY_CANDLE_MEMORY_4B15A_FAIL' not in text:
        return _fail('/qa last must show direct script failure line')
    return 0


def test_regression_catalyst_4b18() -> int:
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / 'test_catalyst_gainer_classification_4b18.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return _fail('catalyst 4B.18 regression failed')
    return 0


def test_regression_pattern_4b17() -> int:
    for script in (
        'test_pattern_board_consistency_4b17b.py',
        'test_pattern_board_4b17a.py',
    ):
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, 'ASTRAEDGE_QA_SMOKE': '1', 'PYTHONPATH': str(PROJECT_ROOT)},
        )
        if proc.returncode != 0:
            print(proc.stdout, file=sys.stderr)
            print(proc.stderr, file=sys.stderr)
            return _fail(f'{script} failed under smoke-safe mode')
    return 0


def test_regression_qa_command_4b16() -> int:
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / 'test_qa_command_4b16.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, 'ASTRAEDGE_QA_SMOKE': '1', 'PYTHONPATH': str(PROJECT_ROOT)},
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return _fail('qa command 4B.16 regression failed')
    return 0


def test_build_label_51z() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52K' or ASTRAEDGE_BUILD_STAGE != '52K':
        return _fail(f'expected AstraEdge 52K got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_smoke_runner_sets_qa_smoke_env,
        test_full_runner_unsets_qa_smoke_env,
        test_smoke_skips_nested_regression_in_intraday_script,
        test_full_mode_runs_nested_regression_hook,
        test_qa_last_reports_script_and_failure_detail,
        test_regression_catalyst_4b18,
        test_regression_pattern_4b17,
        test_regression_qa_command_4b16,
        test_build_label_51z,
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
    print(f'ALL {len(tests)} QA_SMOKE_ISOLATION_4B18A TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
