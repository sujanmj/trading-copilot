#!/usr/bin/env python3
"""Unit tests for broker refresh cache write verification (Stage 48M)."""

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
    print(f'BROKER_REFRESH_WRITES_CACHE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics import broker_intelligence as bi

    payload = {
        'ok': True,
        'generated_at': '2026-05-27T12:00:00+05:30',
        'evidence_items': [{'ticker': 'RELIANCE', 'headline': 'Target raised'}],
        'consensus_by_ticker': {
            'RELIANCE': {'ticker': 'RELIANCE', 'confidence_score': 72, 'consensus_label': 'Positive'},
        },
        'tracked_tickers': 1,
        'freshness': {'status': 'fresh'},
    }

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / 'broker_intelligence_cache.json'
        with patch.object(bi, 'CACHE_FILE', cache_path):
            with patch.object(bi, 'build_broker_intelligence_cache', return_value=payload):
                result = bi.refresh_broker_intelligence(persist=True)
        if not cache_path.is_file():
            return _fail('refresh must write broker_intelligence_cache.json')
        on_disk = json.loads(cache_path.read_text(encoding='utf-8'))
        if not on_disk.get('generated_at'):
            return _fail('cache must include generated_at')
        verify = result.get('cache_verify') or {}
        if not verify.get('ok'):
            return _fail('cache_verify must pass after write')
        if int(verify.get('evidence_count') or 0) < 1:
            return _fail('cache_verify must count evidence_items')

    print('BROKER_REFRESH_WRITES_CACHE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
