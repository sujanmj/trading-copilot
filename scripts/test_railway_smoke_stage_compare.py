#!/usr/bin/env python3
"""Unit tests for Railway post-deploy smoke stage comparator (Stage 47B)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'RAILWAY_SMOKE_STAGE_COMPARE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from scripts.railway_post_deploy_smoke import (
        _parse_build_stage,
        _stage_at_least,
        _stage_at_least_46e,
        _validate_build_info,
    )

    cases = {
        '46D': (46, ord('D')),
        '46E': (46, ord('E')),
        '46J': (46, ord('J')),
        '47A': (47, ord('A')),
        '47B': (47, ord('B')),
        '47C': (47, ord('C')),
        '47D': (47, ord('D')),
        '47E': (47, ord('E')),
        '47F': (47, ord('F')),
        '48A': (48, ord('A')),
    }
    for stage, expected in cases.items():
        parsed = _parse_build_stage(stage)
        if parsed != expected:
            return _fail(f'_parse_build_stage({stage!r}) = {parsed!r}, want {expected!r}')

    if _parse_build_stage('') is not None:
        return _fail('empty stage should not parse')
    if _parse_build_stage('stage47A') is not None:
        return _fail('invalid stage should not parse')

    if not _stage_at_least_46e('46E'):
        return _fail('46E should pass minimum')
    if not _stage_at_least_46e('46J'):
        return _fail('46J should pass minimum')
    if not _stage_at_least_46e('47A'):
        return _fail('47A should pass minimum')
    if not _stage_at_least_46e('47B'):
        return _fail('47B should pass minimum')
    if not _stage_at_least_46e('47C'):
        return _fail('47C should pass minimum')
    if not _stage_at_least_46e('47D'):
        return _fail('47D should pass minimum')
    if not _stage_at_least_46e('47E'):
        return _fail('47E should pass minimum')
    if not _stage_at_least_46e('47F'):
        return _fail('47F should pass minimum')
    if not _stage_at_least_46e('48A'):
        return _fail('48A should pass minimum')
    if _stage_at_least_46e('46D'):
        return _fail('46D should fail minimum')
    if _stage_at_least_46e('45Z'):
        return _fail('45Z should fail minimum')

    if not _stage_at_least('47A', '47B'):
        return _fail('47B should be >= 47A')
    if _stage_at_least('47B', '47A'):
        return _fail('47A should not be >= 47B')
    if not _stage_at_least('47B', '47C'):
        return _fail('47C should be >= 47B')
    if _stage_at_least('47C', '47B'):
        return _fail('47B should not be >= 47C')
    if not _stage_at_least('47C', '47D'):
        return _fail('47D should be >= 47C')
    if _stage_at_least('47D', '47C'):
        return _fail('47C should not be >= 47D')
    if not _stage_at_least('47D', '47E'):
        return _fail('47E should be >= 47D')
    if _stage_at_least('47E', '47D'):
        return _fail('47D should not be >= 47E')

    payload_47a = {
        'app': 'AstraEdge',
        'stage': '47A',
        'telegram_handler': 'astraedge_analysis_bot',
        'legacy_telegram_listener': False,
        'data_root': '/app/data',
        'data_preserved': True,
        'astraedge_telegram_started': True,
    }
    err = _validate_build_info(payload_47a)
    if err:
        return _fail(f'47A build-info should pass strict validation, got: {err}')

    payload_47b = dict(payload_47a)
    payload_47b['stage'] = '47B'
    err = _validate_build_info(payload_47b)
    if err:
        return _fail(f'47B build-info should pass strict validation, got: {err}')

    payload_47c = dict(payload_47a)
    payload_47c['stage'] = '47C'
    err = _validate_build_info(payload_47c)
    if err:
        return _fail(f'47C build-info should pass strict validation, got: {err}')

    payload_47d = dict(payload_47a)
    payload_47d['stage'] = '47D'
    err = _validate_build_info(payload_47d)
    if err:
        return _fail(f'47D build-info should pass strict validation, got: {err}')

    payload_47e = dict(payload_47a)
    payload_47e['stage'] = '47E'
    err = _validate_build_info(payload_47e)
    if err:
        return _fail(f'47E build-info should pass strict validation, got: {err}')

    payload_47f = dict(payload_47a)
    payload_47f['stage'] = '47F'
    err = _validate_build_info(payload_47f)
    if err:
        return _fail(f'47F build-info should pass strict validation, got: {err}')

    bad = dict(payload_47a)
    bad['stage'] = '46D'
    err = _validate_build_info(bad)
    if err is None:
        return _fail('46D build-info should fail strict validation')

    print('RAILWAY_SMOKE_STAGE_COMPARE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
