#!/usr/bin/env python3
"""Unit tests for broker API routes (Stage 48L)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_API_ROUTES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for needle in (
        '/api/brokers/overview',
        '/api/brokers/ticker/{ticker}',
        '/api/brokers/evidence',
        '/api/brokers/refresh',
        'get_broker_intel_ticker',
        'get_broker_intel_evidence',
        'get_broker_overview(cache_only=bool(cache_only), lite=bool(lite))',
    ):
        if needle not in api_src:
            return _fail(f'api_server.py missing {needle!r}')

    from backend.analytics import broker_intelligence as bi

    with patch('backend.analytics.broker_intelligence._load_cache', return_value={}):
        start = time.perf_counter()
        overview = bi.get_broker_intel_overview(cache_only=True, lite=True)
        elapsed = time.perf_counter() - start
        if not overview.get('cache_missing'):
            return _fail('empty cache must return cache_missing')
        if elapsed > 2.0:
            return _fail('lite overview too slow')

        ticker = bi.get_broker_intel_ticker('RELIANCE', cache_only=True, lite=True)
        if not ticker.get('cache_missing'):
            return _fail('ticker route must handle missing cache')

        evidence = bi.get_broker_intel_evidence(cache_only=True, lite=True)
        if not evidence.get('cache_missing'):
            return _fail('evidence route must handle missing cache')

    if 'api_not_found' not in api_src or 'JSONResponse' not in api_src:
        return _fail('api_server must keep JSON 404 guard')

    print('BROKER_API_ROUTES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
