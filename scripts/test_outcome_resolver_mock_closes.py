#!/usr/bin/env python3
"""Unit tests — outcome resolver mock close prices (Stage 49A)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_TICKER = '__TEST_RESOLVER_49A__'
HOLDING = 'signal_quality'


def _fail(msg: str) -> int:
    print(f'OUTCOME_RESOLVER_MOCK_CLOSES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.outcome_resolver import (
        BEARISH_HIT_PCT,
        BEARISH_MISS_PCT,
        BULLISH_HIT_PCT,
        BULLISH_MISS_PCT,
        evaluate_return_outcome,
        is_bearish_signal,
        map_outcome_to_resolved_as,
        resolve_single_prediction,
        run_outcome_resolver_once,
    )
    from backend.storage.outcome_price_lookup import PriceHit
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, upsert_prediction

    hit, _ = evaluate_return_outcome(BULLISH_HIT_PCT + 0.1, bearish=False)
    miss, _ = evaluate_return_outcome(BULLISH_MISS_PCT - 0.1, bearish=False)
    neutral, _ = evaluate_return_outcome(0.2, bearish=False)
    if hit != 'hit' or miss != 'miss' or neutral != 'neutral':
        return _fail('bullish hit/miss/neutral thresholds failed')

    b_hit, _ = evaluate_return_outcome(BEARISH_HIT_PCT - 0.1, bearish=True)
    b_miss, _ = evaluate_return_outcome(BEARISH_MISS_PCT + 0.1, bearish=True)
    b_neutral, _ = evaluate_return_outcome(0.2, bearish=True)
    if b_hit != 'hit' or b_miss != 'miss' or b_neutral != 'neutral':
        return _fail('bearish hit/miss/neutral thresholds failed')

    if map_outcome_to_resolved_as('hit') != 'WIN':
        return _fail('hit must map to WIN')

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    old_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    prediction_ids: list[str] = []
    conn = get_connection()
    try:
        for direction, ref, eval_price, expected in (
            ('BULLISH', 100.0, 101.0, 'WIN'),
            ('BEARISH', 100.0, 99.0, 'WIN'),
        ):
            pid = upsert_prediction({
                'ticker': TEST_TICKER,
                'timestamp': old_ts,
                'source': 'resolver_test_49a',
                'direction': direction,
                'confidence': 0.7,
                'raw_payload': {
                    'entry_price': ref,
                    'signal_time': old_ts,
                    'horizon': 'next_day',
                    'signal_type': 'WATCH_FOR_ENTRY' if direction == 'BULLISH' else 'AVOID',
                },
            })
            if not pid:
                return _fail('upsert_prediction failed')
            prediction_ids.append(pid)

        market_data = {
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'prices': {TEST_TICKER: {'price': 101.0}},
        }
        pending_rows = []
        for pid in prediction_ids:
            row = conn.execute('SELECT * FROM predictions WHERE prediction_id = ?', (pid,)).fetchone()
            pending_rows.append(dict(row))

        eval_hit = PriceHit(101.0, 'latest_market_data', datetime.now(timezone.utc))
        with patch(
            'backend.storage.outcome_resolver.get_pending_predictions',
            return_value=pending_rows,
        ):
            with patch('backend.storage.outcome_price_lookup.lookup_evaluation_price', return_value=eval_hit):
                summary = run_outcome_resolver_once(
                    limit=50,
                    market_data=market_data,
                    refresh_cache=False,
                )
        if int(summary.get('resolved_new') or 0) < 1:
            return _fail(f'expected resolved predictions got {summary!r}')

        row = conn.execute(
            """
            SELECT o.resolved_as, o.holding_period
            FROM outcomes o
            JOIN predictions p ON p.prediction_id = o.prediction_id
            WHERE p.ticker = ? AND o.holding_period = ?
            """,
            (TEST_TICKER, HOLDING),
        ).fetchone()
        if not row:
            return _fail('expected outcome row after resolver run')
        if str(row['resolved_as']) not in ('WIN', 'LOSS', 'NEUTRAL'):
            return _fail(f'unexpected resolved_as {row["resolved_as"]!r}')

        pred_row = conn.execute(
            'SELECT * FROM predictions WHERE prediction_id = ? LIMIT 1',
            (prediction_ids[0],),
        ).fetchone()
        payload, skip = resolve_single_prediction(dict(pred_row), market_data)
        if payload is not None or skip != 'already_resolved':
            return _fail(f're-resolving same prediction must skip got skip={skip!r}')
    finally:
        for pid in prediction_ids:
            conn.execute('DELETE FROM outcomes WHERE prediction_id = ?', (pid,))
            conn.execute('DELETE FROM predictions WHERE prediction_id = ?', (pid,))
        conn.commit()
        conn.close()

    bearish_pred = {'direction': 'BEARISH', 'raw_payload': '{"signal_type":"AVOID"}'}
    if not is_bearish_signal(bearish_pred):
        return _fail('AVOID must be bearish')

    print('OUTCOME_RESOLVER_MOCK_CLOSES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
