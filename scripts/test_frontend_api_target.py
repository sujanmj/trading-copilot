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
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
VITE_CONFIG = PROJECT_ROOT / 'frontend' / 'vite.config.js'
API_TARGET_JS = PROJECT_ROOT / 'frontend' / 'src' / 'lib' / 'apiTarget.js'
FRONTEND_SRC = PROJECT_ROOT / 'frontend' / 'src'

RAILWAY_URL_PATTERNS = (
    re.compile(r'https?://[a-z0-9-]+\.up\.railway\.app', re.IGNORECASE),
    re.compile(r'railway\.app/[a-z0-9-]+', re.IGNORECASE),
)

SRC_EXTENSIONS = {'.js', '.jsx', '.ts', '.tsx'}


def _fail(msg: str) -> int:
    print(f'FRONTEND_API_TARGET_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _no_hardcoded_railway_url(src: str) -> str | None:
    for pattern in RAILWAY_URL_PATTERNS:
        match = pattern.search(src)
        if match:
            return f'hardcoded Railway URL found: {match.group(0)!r}'
    return None


def _check_import_meta_locations() -> str | None:
    if not INDEX.is_file():
        return 'frontend/index.html missing'
    index_src = INDEX.read_text(encoding='utf-8')
    if 'import.meta' in index_src:
        return 'index.html must not use import.meta (use __ASTRAEDGE_ENV__ in inline scripts)'

    if not FRONTEND_SRC.is_dir():
        return 'frontend/src missing'

    for path in FRONTEND_SRC.rglob('*'):
        if path.suffix not in SRC_EXTENSIONS:
            continue
        text = path.read_text(encoding='utf-8')
        if 'import.meta' not in text:
            continue
        if 'import.meta.env' not in text:
            return f'{path.relative_to(PROJECT_ROOT)} uses import.meta outside import.meta.env'
    return None


def _run_api_target_js_tests() -> str | None:
    if not API_TARGET_JS.is_file():
        return 'frontend/src/lib/apiTarget.js missing'

    script = r"""
import {
  getApiMode,
  isLocalApiBase,
  isRailwayApiBase,
  normalizeBaseUrl,
  readInjectedViteApiBaseUrl,
} from './frontend/src/lib/apiTarget.js';

const local = 'http://127.0.0.1:8080';
const railway = 'https://trading-copilot-production.up.railway.app';

if (getApiMode(local) !== 'LOCAL') throw new Error('localhost should be LOCAL');
if (getApiMode(railway) !== 'RAILWAY') throw new Error('railway.app should be RAILWAY');
if (!isLocalApiBase(local)) throw new Error('isLocalApiBase localhost');
if (!isRailwayApiBase(railway)) throw new Error('isRailwayApiBase railway');
if (isRailwayApiBase(local)) throw new Error('localhost is not railway');

globalThis.window = {
  __ASTRAEDGE_ENV__: { VITE_API_BASE_URL: railway },
};
if (readInjectedViteApiBaseUrl() !== railway) {
  throw new Error('readInjectedViteApiBaseUrl failed');
}
if (normalizeBaseUrl(railway + '/') !== railway) {
  throw new Error('normalizeBaseUrl trailing slash');
}
"""
    proc = subprocess.run(
        ['node', '--input-type=module', '-e', script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or '').strip()
        return f'apiTarget.js node checks failed: {detail}'
    return None


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    err = _no_hardcoded_railway_url(src)
    if err:
        return _fail(err)

    err = _check_import_meta_locations()
    if err:
        return _fail(err)

    err = _run_api_target_js_tests()
    if err:
        return _fail(err)

    required_fragments = (
        'VITE_API_BASE_URL',
        '__ASTRAEDGE_ENV__',
        'ASTRAEDGE_API_BASE_URL',
        'ASTRAEDGE_API_TARGET',
        'http://127.0.0.1:8080',
        'apiTargetBadge',
        'API: LOCAL',
        'API: RAILWAY',
        'Set API Local',
        'Set API Railway',
        'Save Railway API URL',
        'readInjectedViteApiBaseUrl',
        'readViteApiBaseUrl',
        'resolveApiBase',
        'getApiMode',
        'isLocalApiBase',
        '[API_TARGET]',
        'astraApiBase',
        'aiOpsApiTarget',
        'bootstrapApiTarget.js',
    )
    for fragment in required_fragments:
        if fragment not in src:
            return _fail(f'index.html missing: {fragment}')

    if 'const API_BASE = resolveApiBase()' in src:
        return _fail('API_BASE should be mutable (let) for runtime target switch')

    if not API_TARGET_JS.is_file():
        return _fail('frontend/src/lib/apiTarget.js missing')

    api_src = API_TARGET_JS.read_text(encoding='utf-8')
    for fragment in (
        'resolveApiBase',
        'getApiMode',
        'readViteApiBaseUrl',
        'readInjectedViteApiBaseUrl',
        'ASTRAEDGE_API_BASE_URL',
        '[API_TARGET]',
    ):
        if fragment not in api_src:
            return _fail(f'apiTarget.js missing: {fragment}')

    if VITE_CONFIG.is_file():
        vite_src = VITE_CONFIG.read_text(encoding='utf-8')
        if 'VITE_API_BASE_URL' not in vite_src:
            return _fail('vite.config.js missing VITE_API_BASE_URL define')
        if '%VITE_API_BASE_URL%' not in vite_src and 'astraedge-html-env' not in vite_src:
            return _fail('vite.config.js missing HTML env injection for VITE_API_BASE_URL')

    print('FRONTEND_API_TARGET_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
