#!/usr/bin/env python3
"""
Validate Stage 45A — full GUI E2E test matrix wiring.

Prints exactly GUI_E2E_MATRIX_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC = PROJECT_ROOT / 'tests' / 'gui' / 'e2e' / 'astraedge-full-e2e.spec.js'
PKG = PROJECT_ROOT / 'frontend' / 'package.json'
RUNNER = PROJECT_ROOT / 'scripts' / 'run_gui_e2e.ps1'
MARKER = 'QA_STAGE_45A_FULL_GUI_E2E_MATRIX'

COVERAGE_TOKENS = (
    'Memory',
    'Brokers',
    'AI Hub',
    'Refresh',
    'Backend API JSON',
    'brain',
    'govt',
    'scanner',
    'markets',
    'global',
    'news',
    'tv',
    'reddit',
    'stats',
    'history',
    '/api/runtime/snapshot',
    '/api/debug/aihub-tab/',
)


def _fail(msg: str) -> int:
    print(f'GUI_E2E_MATRIX_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not SPEC.is_file():
        return _fail(f'missing {SPEC.relative_to(PROJECT_ROOT)}')

    src = SPEC.read_text(encoding='utf-8')
    if MARKER not in src:
        return _fail(f'{MARKER} marker missing in spec')

    for token in COVERAGE_TOKENS:
        if token not in src:
            return _fail(f'spec missing coverage token: {token!r}')

    if not RUNNER.is_file():
        return _fail('scripts/run_gui_e2e.ps1 missing')

    runner = RUNNER.read_text(encoding='utf-8')
    if 'npm run test:e2e' not in runner:
        return _fail('run_gui_e2e.ps1 must run npm run test:e2e')

    if not PKG.is_file():
        return _fail('frontend/package.json missing')

    pkg = json.loads(PKG.read_text(encoding='utf-8'))
    scripts = pkg.get('scripts') or {}
    e2e = scripts.get('test:e2e', '')
    if not e2e:
        return _fail('frontend/package.json missing test:e2e script')
    if 'astraedge-full-e2e.spec.js' not in e2e:
        return _fail('test:e2e must target astraedge-full-e2e.spec.js')

    print('GUI_E2E_MATRIX_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
