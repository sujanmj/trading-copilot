#!/usr/bin/env python3
"""
Test deterministic canonical market memory prediction IDs.

Usage:
  python scripts/test_market_memory_id_generation.py

Prints exactly MARKET_MEMORY_ID_GENERATION_OK on success.
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

SOURCE = 'runtime_snapshot_active_predictions'


def _fail(msg: str) -> int:
    print(f'MARKET_MEMORY_ID_GENERATION_FAIL: {msg}', file=sys.stderr)
    return 1


def _id(item: dict, *, date: str | None = None) -> str:
    from backend.storage.market_memory_db import make_canonical_prediction_id
    from backend.storage.market_memory_capture import normalize_prediction_payload

    merged = dict(item)
    if date is not None:
        merged['prediction_date'] = date
    normalized = normalize_prediction_payload(merged, source_hint=SOURCE)
    if normalized is None:
        raise ValueError('normalize returned None')
    return make_canonical_prediction_id(normalized, source_hint=SOURCE)


def main() -> int:
    base = {
        'ticker': 'TEXRAIL',
        'prediction_id': 201,
        'prediction_horizon': 'intraday',
        'run_type': 'scanner',
    }

    id_date_a = _id(base, date='2026-05-27')
    id_date_b = _id(base, date='2026-05-28')
    if id_date_a == id_date_b:
        return _fail('same raw prediction_id different date should differ')
    if not id_date_a.startswith('mm:'):
        return _fail(f'expected mm: prefix, got {id_date_a!r}')

    id_same_a = _id(base, date='2026-05-27')
    id_same_b = _id(base, date='2026-05-27')
    if id_same_a != id_same_b:
        return _fail('same raw id/date/ticker should produce identical IDs')

    other_ticker = dict(base)
    other_ticker['ticker'] = 'RELIANCE'
    id_other = _id(other_ticker, date='2026-05-27')
    if id_other == id_same_a:
        return _fail('different ticker same raw id should differ')

    no_raw = {
        'ticker': 'ABC',
        'prediction_date': '2026-05-27',
        'prediction_horizon': 'swing',
    }
    id_no_raw_a = _id(no_raw)
    id_no_raw_b = _id(no_raw)
    if id_no_raw_a != id_no_raw_b:
        return _fail('missing raw id should still be deterministic')
    if not id_no_raw_a.startswith('mm:'):
        return _fail('missing raw id should still use mm: prefix')

    print('MARKET_MEMORY_ID_GENERATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
