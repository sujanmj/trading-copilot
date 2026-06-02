#!/usr/bin/env python3
"""
Validate frontend API auth wiring.

Usage:
  python scripts/validate_frontend_api_auth.py

Prints FRONTEND_API_AUTH_OK on success.
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
    print(f'FRONTEND_API_AUTH_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index = PROJECT_ROOT / 'frontend' / 'index.html'
    api_auth = PROJECT_ROOT / 'frontend' / 'src' / 'lib' / 'apiAuth.js'

    if not api_auth.is_file():
        return _fail('frontend/src/lib/apiAuth.js missing')

    if not index.is_file():
        return _fail('frontend/index.html missing')

    src = index.read_text(encoding='utf-8')
    for fragment in (
        'window.setAstraEdgeApiKey',
        'ASTRAEDGE_API_KEY',
        'handleRailwayAuthMissingStartup',
        'updateRailwayAuthMissingBanner',
        'mergeFetchOptions',
        'bootstrapApiAuth.js',
    ):
        if fragment not in src:
            return _fail(f'missing wiring: {fragment}')

    auth_src = api_auth.read_text(encoding='utf-8')
    for fragment in (
        "headers['X-API-Key']",
        "headers['Authorization']",
        "'Bearer '",
        'resolveApiKey',
        'ASTRAEDGE_API_KEY_STORAGE_KEY',
    ):
        if fragment not in auth_src:
            return _fail(f'apiAuth.js missing: {fragment}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_frontend_api_auth.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        return _fail(proc.stderr or proc.stdout)
    if 'FRONTEND_API_AUTH_TEST_OK' not in proc.stdout:
        return _fail('test_frontend_api_auth missing OK marker')

    print('FRONTEND_API_AUTH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
