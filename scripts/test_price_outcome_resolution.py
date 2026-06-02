#!/usr/bin/env python3
"""
Synthetic tests for price-based market memory outcome resolution.

Usage:
  python scripts/test_price_outcome_resolution.py

Prints exactly PRICE_OUTCOME_RESOLUTION_OK on success; exits 1 on failure.
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

TEST_TICKER = '__TEST_PRICE_OUTCOME__'
TEST_HOLDING = 'test_price'


def _fail(msg: str) -> int:
    print(f'PRICE_OUTCOME_RESOLUTION_FAIL: {msg}', file=sys.stderr)
    return 1


def _cleanup(conn, prediction_ids: list[str]) -> None:
    for prediction_id in prediction_ids:
        conn.execute(
            'DELETE FROM outcomes WHERE prediction_id = ? AND holding_period = ?',
            (prediction_id, TEST_HOLDING),
        )
        conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (prediction_id,))
    conn.commit()


def main() -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction
    from backend.storage.market_memory_outcomes import (
        extract_prediction_price_context,
        lookup_latest_price,
        resolve_outcome_from_prices,
        resolve_prediction_outcome,
    )

    if not init_market_memory_db():
        return _fail('init_market_memory_db returned False')

    synthetic_market_data = {
        'last_updated': '2026-01-10T12:00:00+00:00',
        'prices': {
            TEST_TICKER: {'price': 120.0},
            '__TEST_PRICE_WIN__': {'price': 120.0},
            '__TEST_PRICE_LOSS__': {'price': 90.0},
            '__TEST_PRICE_MID__': {'price': 105.0},
            '__TEST_PRICE_MISSING__': {'price': 50.0},
        },
    }

    cases = [
        {
            'name': 'bullish_target_hit',
            'ticker': '__TEST_PRICE_WIN__',
            'direction': 'BULLISH',
            'raw_payload': {
                'entry_price': 100.0,
                'target_price': 115.0,
                'stop_loss': 95.0,
            },
            'latest': 120.0,
            'expect': ('WIN', 'TARGET_HIT_BY_PRICE'),
        },
        {
            'name': 'bullish_stop_loss_hit',
            'ticker': '__TEST_PRICE_LOSS__',
            'direction': 'BULLISH',
            'raw_payload': {
                'entry_price': 100.0,
                'target_price': 115.0,
                'stop_loss': 95.0,
            },
            'latest': 90.0,
            'expect': ('LOSS', 'STOP_LOSS_HIT_BY_PRICE'),
        },
        {
            'name': 'bullish_between_levels',
            'ticker': '__TEST_PRICE_MID__',
            'direction': 'BULLISH',
            'raw_payload': {
                'entry_price': 100.0,
                'target_price': 115.0,
                'stop_loss': 95.0,
            },
            'latest': 105.0,
            'expect': None,
        },
        {
            'name': 'missing_latest_price',
            'ticker': '__TEST_PRICE_MISSING__',
            'direction': 'BULLISH',
            'raw_payload': {
                'entry_price': 100.0,
                'target_price': 115.0,
                'stop_loss': 95.0,
            },
            'latest': None,
            'expect': None,
        },
    ]

    prediction_ids: list[str] = []
    conn = get_connection()
    try:
        for index, case in enumerate(cases):
            prediction_id = upsert_prediction({
                'ticker': case['ticker'],
                'timestamp': f'2026-01-1{index}T00:00:00+00:00',
                'source': 'price_outcome_test',
                'direction': case['direction'],
                'confidence': 0.7,
                'reasoning': f'price outcome test: {case["name"]}',
                'raw_payload': case['raw_payload'],
            })
            if not prediction_id:
                return _fail(f'upsert_prediction failed for {case["name"]}')

            prediction_ids.append(prediction_id)
            prediction = {
                'prediction_id': prediction_id,
                'ticker': case['ticker'],
                'direction': case['direction'],
                'raw_payload': case['raw_payload'],
            }

            ctx = extract_prediction_price_context(prediction)
            if ctx is None and case['expect'] is not None:
                return _fail(f'{case["name"]}: extract_prediction_price_context returned None')

            if case['name'] == 'missing_latest_price':
                latest = lookup_latest_price(
                    {'prices': {}},
                    case['ticker'],
                )
                if latest is not None:
                    return _fail(f'{case["name"]}: expected missing latest price')
                outcome_payload = None
            else:
                latest = lookup_latest_price(synthetic_market_data, case['ticker'])
                if latest is None:
                    return _fail(f'{case["name"]}: lookup_latest_price returned None')
                if case.get('latest') is not None and latest != case['latest']:
                    return _fail(
                        f'{case["name"]}: latest={latest} expected {case["latest"]}',
                    )
                outcome_payload = resolve_outcome_from_prices(
                    prediction,
                    latest,
                    holding_period=TEST_HOLDING,
                    latest_market_data_timestamp='2026-01-10T12:00:00+00:00',
                )

            if case['expect'] is None:
                if outcome_payload is not None:
                    return _fail(f'{case["name"]}: expected skip, got payload')
                continue

            if outcome_payload is None:
                return _fail(f'{case["name"]}: expected outcome, got None')

            expected_resolved, expected_expiry = case['expect']
            if outcome_payload.get('resolved_as') != expected_resolved:
                return _fail(
                    f'{case["name"]}: resolved_as={outcome_payload.get("resolved_as")} '
                    f'expected {expected_resolved}',
                )
            if outcome_payload.get('expiry_result') != expected_expiry:
                return _fail(
                    f'{case["name"]}: expiry_result={outcome_payload.get("expiry_result")} '
                    f'expected {expected_expiry}',
                )

            raw = outcome_payload.get('raw_payload') or {}
            if raw.get('source') != 'latest_market_data_price_resolution':
                return _fail(f'{case["name"]}: unexpected raw_payload source')

            if not resolve_prediction_outcome(prediction_id, outcome_payload):
                return _fail(f'resolve_prediction_outcome failed for {case["name"]}')

            row = conn.execute(
                """
                SELECT resolved_as, expiry_result
                FROM outcomes
                WHERE prediction_id = ? AND holding_period = ?
                """,
                (prediction_id, TEST_HOLDING),
            ).fetchone()
            if row is None:
                return _fail(f'outcome row missing for {case["name"]}')
            if row['resolved_as'] != expected_resolved:
                return _fail(f'db resolved_as mismatch for {case["name"]}')
            if row['expiry_result'] != expected_expiry:
                return _fail(f'db expiry_result mismatch for {case["name"]}')

        _cleanup(conn, prediction_ids)
    finally:
        conn.close()

    print('PRICE_OUTCOME_RESOLUTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
