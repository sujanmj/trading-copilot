#!/usr/bin/env python3
"""
Dry-run static inspection for Stage 45A GUI E2E matrix (no browser).

Prints exactly GUI_E2E_MATRIX_STATIC_TEST_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC = PROJECT_ROOT / 'tests' / 'gui' / 'e2e' / 'astraedge-full-e2e.spec.js'
PW_CONFIG = PROJECT_ROOT / 'frontend' / 'playwright.config.js'
PKG = PROJECT_ROOT / 'frontend' / 'package.json'
RUNNER = PROJECT_ROOT / 'scripts' / 'run_gui_e2e.ps1'
VALIDATOR = PROJECT_ROOT / 'scripts' / 'validate_gui_e2e_matrix.py'
MARKER = 'QA_STAGE_45A_FULL_GUI_E2E_MATRIX'


def _fail(msg: str) -> int:
    print(f'GUI_E2E_MATRIX_STATIC_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (SPEC, PW_CONFIG, PKG, RUNNER, VALIDATOR):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    spec = SPEC.read_text(encoding='utf-8')
    if MARKER not in spec:
        return _fail(f'{MARKER} missing')
    if "test.describe('45A" not in spec:
        return _fail('spec must define 45A describe groups')

    pw = PW_CONFIG.read_text(encoding='utf-8')
    for token in ("screenshot: 'only-on-failure'", "video: 'retain-on-failure'", "trace: 'retain-on-failure'"):
        if token not in pw:
            return _fail(f'playwright.config.js missing {token}')

    pkg = json.loads(PKG.read_text(encoding='utf-8'))
    if 'test:e2e' not in (pkg.get('scripts') or {}):
        return _fail('package.json missing test:e2e')

    val = VALIDATOR.read_text(encoding='utf-8')
    if 'GUI_E2E_MATRIX_OK' not in val:
        return _fail('validate_gui_e2e_matrix.py must print GUI_E2E_MATRIX_OK')

    print('GUI_E2E_MATRIX_STATIC_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
