#!/usr/bin/env python3
"""
Unit tests for frontend API auth (Railway X-API-Key / Bearer).

Usage:
  python scripts/test_frontend_api_auth.py

Prints FRONTEND_API_AUTH_TEST_OK on success.
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
API_AUTH_JS = PROJECT_ROOT / 'frontend' / 'src' / 'lib' / 'apiAuth.js'
BOOTSTRAP_AUTH = PROJECT_ROOT / 'frontend' / 'src' / 'bootstrapApiAuth.js'
FRONTEND_SRC = PROJECT_ROOT / 'frontend' / 'src'

KEY_LITERAL_PATTERNS = (
    re.compile(r"['\"]sk-[a-zA-Z0-9]{20,}['\"]"),
    re.compile(r"['\"]astraedge_[a-zA-Z0-9]{16,}['\"]", re.IGNORECASE),
    re.compile(r"['\"]railway_[a-zA-Z0-9]{16,}['\"]", re.IGNORECASE),
)

COMMITTED_KEY_ENV = re.compile(
    r'(?:VITE_ASTRAEDGE_API_KEY|VITE_API_KEY)\s*=\s*[\'"][^\'"\s%]{8,}[\'"]',
    re.IGNORECASE,
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_API_AUTH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _no_committed_key_literal(src: str, label: str) -> str | None:
    for pattern in KEY_LITERAL_PATTERNS:
        match = pattern.search(src)
        if match:
            return f'{label}: committed API key literal found: {match.group(0)!r}'
    return None


def _no_key_in_console_log(src: str, label: str) -> str | None:
    for line in src.splitlines():
        if 'console.log' not in line:
            continue
        if '[API_AUTH]' in line and 'enabled=' in line:
            continue
        if re.search(r'console\.log\([^)]*(?:api[_-]?key|API_KEY|resolveApiKey|ASTRAEDGE_API_KEY)', line, re.IGNORECASE):
            if 'enabled=' in line:
                continue
            return f'{label}: console.log may expose API key: {line.strip()!r}'
    return None


def _run_api_auth_js_tests() -> str | None:
    if not API_AUTH_JS.is_file():
        return 'frontend/src/lib/apiAuth.js missing'

    script = r"""
import {
  buildAuthHeaders,
  getStoredApiKey,
  isApiAuthEnabled,
  readInjectedViteApiKey,
  resolveApiKey,
} from './frontend/src/lib/apiAuth.js';

const testKey = 'test-key-abc123';

globalThis.localStorage = {
  _data: {},
  getItem(k) { return this._data[k] ?? null; },
  setItem(k, v) { this._data[k] = String(v); },
  removeItem(k) { delete this._data[k]; },
};

globalThis.window = {
  __ASTRAEDGE_ENV__: {
    VITE_ASTRAEDGE_API_KEY: '%VITE_ASTRAEDGE_API_KEY%',
    VITE_API_KEY: '%VITE_API_KEY%',
  },
  location: { reload() {} },
};

if (resolveApiKey()) throw new Error('resolveApiKey should be empty initially');
if (isApiAuthEnabled()) throw new Error('isApiAuthEnabled should be false initially');

localStorage.setItem('ASTRAEDGE_API_KEY', testKey);
if (resolveApiKey() !== testKey) throw new Error('localStorage priority failed');
if (!isApiAuthEnabled()) throw new Error('isApiAuthEnabled should be true with key');

const headers = buildAuthHeaders({ Accept: 'application/json' });
if (headers['X-API-Key'] !== testKey) throw new Error('X-API-Key missing');
if (headers['Authorization'] !== 'Bearer ' + testKey) throw new Error('Authorization Bearer missing');

localStorage.removeItem('ASTRAEDGE_API_KEY');
globalThis.window.__ASTRAEDGE_ENV__ = { VITE_ASTRAEDGE_API_KEY: testKey };
if (readInjectedViteApiKey('VITE_ASTRAEDGE_API_KEY') !== testKey) {
  throw new Error('readInjectedViteApiKey failed');
}
if (resolveApiKey() !== testKey) throw new Error('injected env priority failed');
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
        return f'apiAuth.js node checks failed: {detail}'
    return None


def main() -> int:
    if not API_AUTH_JS.is_file():
        return _fail('frontend/src/lib/apiAuth.js missing')

    api_src = API_AUTH_JS.read_text(encoding='utf-8')
    for fragment in (
        'ASTRAEDGE_API_KEY',
        'VITE_ASTRAEDGE_API_KEY',
        'VITE_API_KEY',
        'X-API-Key',
        'Authorization',
        'Bearer ',
        'buildAuthHeaders',
        'resolveApiKey',
        '[API_AUTH]',
        'localStorage',
    ):
        if fragment not in api_src:
            return _fail(f'apiAuth.js missing: {fragment}')

    err = _no_committed_key_literal(api_src, 'apiAuth.js')
    if err:
        return _fail(err)

    err = _no_key_in_console_log(api_src, 'apiAuth.js')
    if err:
        return _fail(err)

    if not BOOTSTRAP_AUTH.is_file():
        return _fail('frontend/src/bootstrapApiAuth.js missing')
    bootstrap_src = BOOTSTRAP_AUTH.read_text(encoding='utf-8')
    if 'setAstraEdgeApiKey' not in bootstrap_src:
        return _fail('bootstrapApiAuth.js missing setAstraEdgeApiKey export')

    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    index_src = INDEX.read_text(encoding='utf-8')
    for fragment in (
        'VITE_ASTRAEDGE_API_KEY',
        'VITE_API_KEY',
        '__ASTRAEDGE_ENV__',
        'bootstrapApiAuth.js',
        'astraApiHeaders',
        'buildAuthHeaders',
        'setAstraEdgeApiKey',
        'railwayAuthMissingBanner',
        'api-auth-missing-banner',
        'Railway API auth missing. Set ASTRAEDGE_API_KEY in browser localStorage or VITE_ASTRAEDGE_API_KEY in frontend/.env.local.',
        '[API_AUTH]',
        'mergeFetchOptions',
        'handleRailwayAuthMissingStartup',
    ):
        if fragment not in index_src:
            return _fail(f'index.html missing: {fragment}')

    if 'Authorization' not in index_src or 'Bearer' not in index_src:
        return _fail('index.html missing Authorization Bearer wiring')

    err = _no_committed_key_literal(index_src, 'index.html')
    if err:
        return _fail(err)

    err = _no_key_in_console_log(index_src, 'index.html')
    if err:
        return _fail(err)

    rm = PROJECT_ROOT / 'frontend' / 'runtime' / 'runtimeManager.js'
    if rm.is_file():
        rm_src = rm.read_text(encoding='utf-8')
        if 'mergeFetchAuthHeaders' not in rm_src:
            return _fail('runtimeManager.js missing mergeFetchAuthHeaders')
        if 'buildAuthHeaders' not in rm_src:
            return _fail('runtimeManager.js missing buildAuthHeaders merge')

    if VITE_CONFIG.is_file():
        vite_src = VITE_CONFIG.read_text(encoding='utf-8')
        if 'VITE_ASTRAEDGE_API_KEY' not in vite_src:
            return _fail('vite.config.js missing VITE_ASTRAEDGE_API_KEY injection')
        if 'VITE_API_KEY' not in vite_src:
            return _fail('vite.config.js missing VITE_API_KEY injection')
        if '%VITE_ASTRAEDGE_API_KEY%' not in vite_src:
            return _fail('vite.config.js missing %VITE_ASTRAEDGE_API_KEY% placeholder replace')

    env_local = PROJECT_ROOT / 'frontend' / '.env.local'
    if env_local.is_file():
        env_src = env_local.read_text(encoding='utf-8')
        if COMMITTED_KEY_ENV.search(env_src):
            return _fail('.env.local appears to contain a real API key — use local only, never commit')

    err = _run_api_auth_js_tests()
    if err:
        return _fail(err)

    print('FRONTEND_API_AUTH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
