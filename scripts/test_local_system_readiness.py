#!/usr/bin/env python3
"""
Unit tests for local system readiness gate (mocked checks).

Usage:
  python scripts/test_local_system_readiness.py

Prints LOCAL_SYSTEM_READINESS_TEST_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'LOCAL_SYSTEM_READINESS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_all_ok() -> None:
    from scripts import local_system_readiness as mod

    for name in mod.COMPACT_ORDER:
        setattr(mod, f'_check_{name}', lambda result, _n=name: result.set_ok(_n))


def main() -> int:
    from scripts.local_system_readiness import (
        COMPACT_ORDER,
        ReadinessResult,
        print_readiness,
        run_local_system_readiness,
    )
    import scripts.local_system_readiness as mod

    # All-pass path with mocked checkers
    _mock_all_ok()
    result = run_local_system_readiness()
    if not result.ready():
        return _fail('mocked all-ok run should be ready')
    if set(result.sections.keys()) != set(COMPACT_ORDER):
        return _fail(f'unexpected sections: {result.sections.keys()}')

    captured: list[str] = []

    def _capture_print(*args, **kwargs):
        captured.append(' '.join(str(a) for a in args))

    with patch('builtins.print', side_effect=_capture_print):
        print_readiness(result)
    output = '\n'.join(captured)
    if 'LOCAL_SYSTEM_READY' not in output:
        return _fail('print_readiness missing LOCAL_SYSTEM_READY')
    if '[LOCAL_READY] ready=True' not in output:
        return _fail('print_readiness missing ready=True')

    # Fail-fast path
    original_checkers = mod.CHECKERS

    def _fail_local_safety(result: ReadinessResult) -> None:
        result.set_fail('local_safety', 'mock failure')

    def _should_not_run(_result: ReadinessResult) -> None:
        raise AssertionError('checker ran after fail-fast stop')

    mod.CHECKERS = (
        ('local_safety', _fail_local_safety),
        ('market_memory', _should_not_run),
    )
    try:
        fail_result = run_local_system_readiness(stop_on_first_fail=True)
        if fail_result.ready():
            return _fail('fail-fast run should not be ready')
        if fail_result.sections.get('local_safety') != 'fail':
            return _fail('local_safety should be fail')
        if 'market_memory' in fail_result.sections:
            return _fail('market_memory should not run under fail-fast')
        first = fail_result.first_failure()
        if not first or first[0] != 'local_safety':
            return _fail('first_failure should be local_safety')
    finally:
        mod.CHECKERS = original_checkers

    # Continue-on-fail path
    calls: list[str] = []

    def _track(name: str):
        def _checker(result: ReadinessResult) -> None:
            calls.append(name)
            if name == 'local_safety':
                result.set_fail(name, 'mock')
            else:
                result.set_ok(name)

        return _checker

    mod.CHECKERS = tuple((name, _track(name)) for name in COMPACT_ORDER)
    try:
        cont_result = run_local_system_readiness(stop_on_first_fail=False)
        if cont_result.ready():
            return _fail('continue-on-fail with one failure should not be ready')
        if calls != list(COMPACT_ORDER):
            return _fail(f'continue-on-fail should run all checks, got {calls}')
    finally:
        mod.CHECKERS = original_checkers

    # Real local_safety keys.env existence (no content read)
    keys_path = PROJECT_ROOT / 'config' / 'keys.env'
    if not keys_path.is_file():
        return _fail('config/keys.env must exist for integration smoke')

    real_result = ReadinessResult()
    mod._check_local_safety(real_result)
    if real_result.sections.get('local_safety') != 'ok':
        detail = real_result.failures.get('local_safety', 'unknown')
        return _fail(f'real local_safety failed: {detail}')

    print('LOCAL_SYSTEM_READINESS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
