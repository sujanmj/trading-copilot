#!/usr/bin/env python3
"""Unit tests for broker live cache persistence reads (Stage 48M)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_LIVE_CACHE_PERSISTENCE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics import broker_intelligence as bi

    payload = {
        'generated_at': '2026-05-27T12:00:00+05:30',
        'evidence_items': [],
        'consensus_by_ticker': {},
        'tracked_tickers': 0,
        'freshness': {'status': 'fresh'},
    }

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / 'broker_intelligence_cache.json'
        cache_path.write_text(json.dumps(payload), encoding='utf-8')
        with patch.object(bi, 'CACHE_FILE', cache_path):
            overview = bi.format_broker_overview_telegram()
            if 'Broker cache unavailable' in overview:
                return _fail('/broker must not say unavailable when cache file exists')
            if 'No fresh broker evidence found' not in overview:
                return _fail('zero-evidence cache should show clean empty message')

    print('BROKER_LIVE_CACHE_PERSISTENCE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
