#!/usr/bin/env python3
"""Unit tests for broker lite API routes (Stage 48E)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_API_LITE_ROUTES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    bo_src = (PROJECT_ROOT / 'backend/analytics/broker_overview_cache.py').read_text(encoding='utf-8')

    for needle in (
        '/api/brokers/overview',
        '/api/brokers/status',
        '/api/brokers/refresh',
        'get_broker_overview(cache_only=bool(cache_only), lite=bool(lite))',
        'get_broker_status(lite=bool(lite))',
        'refresh_broker_intel(persist=True)',
    ):
        if needle not in api_src:
            return _fail(f'api_server.py missing {needle!r}')

    if 'def get_broker_overview(*, cache_only: bool = False, lite: bool = False)' not in bo_src:
        return _fail('get_broker_overview missing lite param')

    from backend.analytics import broker_overview_cache as bo

    with patch('backend.analytics.broker_overview_cache._load_cache', return_value={}):
        with patch('backend.analytics.broker_overview_cache._load_intel_cache', return_value={}):
            with patch('backend.analytics.broker_overview_cache._build_full_overview') as build_mock:
                start = time.perf_counter()
                payload = bo.get_broker_overview(cache_only=True, lite=True)
                elapsed = time.perf_counter() - start
                if build_mock.called:
                    return _fail('lite overview must not call _build_full_overview')
                if not payload.get('cache_missing'):
                    return _fail('empty cache must return cache_missing')
                if payload.get('message') != bo.MISSING_MESSAGE:
                    return _fail('missing cache message mismatch')
                for key in ('brokers', 'signals', 'consensus', 'top_positive', 'top_negative'):
                    if key not in payload:
                        return _fail(f'missing payload key {key!r}')
                if elapsed > 2.0:
                    return _fail('lite overview too slow')

    status = bo.get_broker_status(lite=True)
    if not status.get('ok') or not status.get('lite'):
        return _fail('lite status must return ok lite payload')

    if 'api_not_found' not in api_src or 'JSONResponse' not in api_src:
        return _fail('api_server must keep JSON 404 guard')

    print('BROKER_API_LITE_ROUTES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
