#!/usr/bin/env python3
"""
Validate frontend API target wiring (Stage 46C).

Usage:
  python scripts/validate_frontend_api_target.py

Prints FRONTEND_API_TARGET_OK on success.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'FRONTEND_API_TARGET_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index = PROJECT_ROOT / 'frontend' / 'index.html'
    if not index.is_file():
        return _fail('frontend/index.html missing')

    src = index.read_text(encoding='utf-8')
    for fragment in (
        'Developer / Ops — API target',
        'localStorage.setItem(ASTRA_RAILWAY_URL_STORAGE_KEY',
        'applyApiTargetBadge',
        'initApiTargetControls',
        'isLocalApiBase',
    ):
        if fragment not in src:
            return _fail(f'missing wiring: {fragment}')

    cors = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if 'http://localhost:5173' not in cors:
        return _fail('api_server missing localhost:5173 in CORS')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_frontend_api_target.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        return _fail(proc.stderr or proc.stdout)
    if 'FRONTEND_API_TARGET_TEST_OK' not in proc.stdout:
        return _fail('test_frontend_api_target missing OK marker')

    print('FRONTEND_API_TARGET_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
