#!/usr/bin/env python3
"""
Mapping test for runtime snapshot active_predictions extraction.

Usage:
  python scripts/test_runtime_snapshot_capture_mapping.py

Prints exactly RUNTIME_SNAPSHOT_CAPTURE_MAPPING_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.storage.market_memory_capture import normalize_prediction_payload  # noqa: E402
from backend.storage.runtime_snapshot_capture import (  # noqa: E402
    SOURCE_HINT,
    apply_snapshot_timestamps,
    extract_runtime_snapshot_predictions,
    extract_snapshot_published_at,
    extract_ticker,
)


def _fail(msg: str) -> int:
    print(f'RUNTIME_SNAPSHOT_CAPTURE_MAPPING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    snapshot = {
        'snapshot_published_at': '2026-05-29T02:00:00+05:30',
        'exports': {
            'active_predictions': {
                'predictions': [
                    {
                        'prediction_id': 1,
                        'ticker': 'RELIANCE',
                        'recommendation': 'BUY',
                        'confidence': 'HIGH',
                    },
                    {
                        'prediction_id': 2,
                        'symbol': 'TCS',
                        'direction': 'BULLISH',
                        'confidence': 'MEDIUM',
                        'timestamp': '2026-05-28T10:00:00+00:00',
                    },
                ],
            },
        },
        'data': {
            'active_predictions': {
                'predictions': [
                    {'ticker': 'SHOULD_NOT_USE', 'recommendation': 'BUY'},
                ],
            },
        },
    }

    candidates, source = extract_runtime_snapshot_predictions(snapshot)
    if source != 'exports.active_predictions.predictions':
        return _fail(f'unexpected source: {source}')
    if len(candidates) != 2:
        return _fail(f'expected 2 candidates, got {len(candidates)}')

    snapshot_ts = extract_snapshot_published_at(snapshot)
    prepared = apply_snapshot_timestamps(candidates, snapshot_ts)
    if len(prepared) != 2:
        return _fail(f'expected 2 prepared items, got {len(prepared)}')

    tickers = [extract_ticker(item) for item in prepared]
    if tickers != ['RELIANCE', 'TCS']:
        return _fail(f'unexpected tickers: {tickers}')

    if prepared[0].get('timestamp') != snapshot_ts:
        return _fail('missing snapshot timestamp on item without item timestamp')
    if prepared[1].get('timestamp') != '2026-05-28T10:00:00+00:00':
        return _fail('item timestamp overwritten incorrectly')

    for item in prepared:
        normalized = normalize_prediction_payload(item, source_hint=SOURCE_HINT)
        if normalized is None:
            return _fail('normalize_prediction_payload returned None')
        if normalized['source'] != SOURCE_HINT:
            return _fail(f'unexpected normalized source: {normalized["source"]}')

    print('RUNTIME_SNAPSHOT_CAPTURE_MAPPING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
