#!/usr/bin/env python3
"""
Validate frontend refresh-local-intelligence uses longer timeouts than snapshot fetch.

Usage:
  python scripts/validate_frontend_refresh_timeout.py

Prints exactly FRONTEND_REFRESH_TIMEOUT_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = PROJECT_ROOT / 'frontend' / 'index.html'
RUNTIME_MANAGER = PROJECT_ROOT / 'frontend' / 'runtime' / 'runtimeManager.js'


def _fail(msg: str) -> int:
    print(f'[FRONTEND_REFRESH_TIMEOUT] FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not INDEX_HTML.is_file():
        return _fail('frontend/index.html missing')

    index_text = INDEX_HTML.read_text(encoding='utf-8')
    rm_text = RUNTIME_MANAGER.read_text(encoding='utf-8') if RUNTIME_MANAGER.is_file() else ''

    if 'refresh-local-intelligence' not in index_text:
        return _fail('refresh-local-intelligence call not found in index.html')

    if 'tab-refresh-btn' not in index_text or 'refreshTabByPanel' not in index_text:
        return _fail('per-tab refresh wiring missing')

    if 'REFRESH_TIMEOUT' not in index_text and 'refreshTimeoutForScope' not in index_text:
        return _fail('refresh timeout configuration missing')

    if 'Refresh still running' not in index_text:
        return _fail('long-running refresh message missing')

    if 'package_generated_at' not in rm_text and 'Updated package:' not in rm_text:
        return _fail('package_generated_at / Updated package label missing in runtimeManager.js')

    if 'Data as-of:' not in rm_text:
        return _fail('Data as-of label missing in runtimeManager.js')

    refresh_timeout_match = re.search(r'REFRESH_TIMEOUT_(?:DEFAULT|SLOW)_MS\s*=\s*(\d+)', index_text)
    snapshot_timeout_match = re.search(r'FETCH_TIMEOUT_MS\s*=\s*(\d+)', index_text)
    rm_snapshot_match = re.search(r'FETCH_TIMEOUT_MS\s*=\s*(\d+)', rm_text)

    refresh_ms = int(refresh_timeout_match.group(1)) if refresh_timeout_match else 0
    snapshot_ms = 15000
    if snapshot_timeout_match:
        snapshot_ms = int(snapshot_timeout_match.group(1))
    elif rm_snapshot_match:
        snapshot_ms = int(rm_snapshot_match.group(1))

    if refresh_ms <= snapshot_ms:
        return _fail(f'refresh timeout {refresh_ms}ms must exceed snapshot fetch {snapshot_ms}ms')

    if 'timeoutMs' not in index_text or 'fetchWithTimeout' not in index_text:
        return _fail('refresh fetchWithTimeout(timeoutMs) wiring missing')

    slow_match = re.search(r'REFRESH_TIMEOUT_SLOW_MS\s*=\s*(\d+)', index_text)
    if not slow_match or int(slow_match.group(1)) < 60000:
        return _fail('slow refresh timeout (reddit/tv/global) must be >= 60000ms')

    print(f'[FRONTEND_REFRESH_TIMEOUT] snapshot_fetch_ms={snapshot_ms} refresh_ms={refresh_ms}')
    print('FRONTEND_REFRESH_TIMEOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
