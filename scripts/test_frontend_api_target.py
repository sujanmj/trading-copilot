#!/usr/bin/env python3
"""
Unit tests for frontend API target (Stage 46C).

Usage:
  python scripts/test_frontend_api_target.py

Prints FRONTEND_API_TARGET_TEST_OK on success.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
VITE_CONFIG = PROJECT_ROOT / 'frontend' / 'vite.config.js'

RAILWAY_URL_PATTERNS = (
    re.compile(r'https?://[a-z0-9-]+\.up\.railway\.app', re.IGNORECASE),
    re.compile(r'railway\.app/[a-z0-9-]+', re.IGNORECASE),
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_API_TARGET_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _no_hardcoded_railway_url(src: str) -> str | None:
    for pattern in RAILWAY_URL_PATTERNS:
        match = pattern.search(src)
        if match:
            return f'hardcoded Railway URL found: {match.group(0)!r}'
    return None


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    err = _no_hardcoded_railway_url(src)
    if err:
        return _fail(err)

    required_fragments = (
        'VITE_API_BASE_URL',
        'ASTRAEDGE_API_BASE_URL',
        'ASTRAEDGE_API_TARGET',
        'http://127.0.0.1:8080',
        'apiTargetBadge',
        'API: LOCAL',
        'API: RAILWAY',
        'Set API Local',
        'Set API Railway',
        'Save Railway API URL',
        'readViteApiBaseUrl',
        'resolveApiBase',
        'isLocalApiBase',
        'astraApiBase',
        'aiOpsApiTarget',
    )
    for fragment in required_fragments:
        if fragment not in src:
            return _fail(f'index.html missing: {fragment}')

    if 'const API_BASE = resolveApiBase()' in src:
        return _fail('API_BASE should be mutable (let) for runtime target switch')

    if VITE_CONFIG.is_file():
        vite_src = VITE_CONFIG.read_text(encoding='utf-8')
        if 'VITE_API_BASE_URL' not in vite_src:
            return _fail('vite.config.js missing VITE_API_BASE_URL define')

    print('FRONTEND_API_TARGET_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
