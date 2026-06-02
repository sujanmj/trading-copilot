#!/usr/bin/env python3
"""
Test broker DB audit + cleanup on synthetic rows.

Prints BROKER_DB_AUDIT_CLEANUP_TEST_OK on success.
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


def _fail(msg: str) -> int:
    print(f'BROKER_DB_AUDIT_CLEANUP_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _insert_test_row(payload: dict) -> int | None:
    from backend.storage.market_memory_db import upsert_broker_prediction

    return upsert_broker_prediction(payload, update_existing=False)


def main() -> int:
    from backend.collectors.broker_db_audit import audit_broker_prediction_row, find_unsafe_broker_predictions
    from backend.storage.market_memory_db import delete_broker_predictions_by_ids, get_connection

    test_rows = [
        {
            'prediction_id': 'audit_test_safe_top_pick',
            'broker_source': 'Economic Times',
            'ticker': 'ICICIBANK',
            'bullish_or_bearish': 'BULLISH',
            'target_type': 'top_pick',
            'timeframe': '1w',
            'confidence': 0.7,
            'dedupe_key': 'audit_test_safe_top_pick',
            'raw_payload': {
                'headline': 'Nomura top pick: ICICI Bank with target price Rs 1,500, recommends Buy',
                'classification': 'broker_prediction_candidate',
                'classification_reason': 'explicit_recommendation_with_ticker',
                'direction_confidence': 'explicit',
                'collector_source': 'news',
            },
        },
        {
            'prediction_id': 'audit_test_block_deal',
            'broker_source': 'Moneycontrol',
            'ticker': 'POLICYBZR',
            'bullish_or_bearish': 'BULLISH',
            'target_type': 'broker_pick',
            'timeframe': '1w',
            'confidence': 0.35,
            'dedupe_key': 'audit_test_block_deal',
            'raw_payload': {
                'headline': 'PB Fintech sees Rs 665 crore block deal; Goldman among other buyers',
                'classification': 'broker_prediction_candidate',
                'collector_source': 'news',
            },
        },
        {
            'prediction_id': 'audit_test_credit_rating',
            'broker_source': 'LiveMint',
            'ticker': 'RELIANCE',
            'bullish_or_bearish': 'WATCH',
            'target_type': 'broker_pick',
            'timeframe': '1w',
            'confidence': 0.35,
            'dedupe_key': 'audit_test_credit_rating',
            'raw_payload': {
                'headline': "Moody's upgrades Reliance Industries credit rating outlook to positive",
                'classification': 'broker_prediction_candidate',
                'collector_source': 'news',
            },
        },
        {
            'prediction_id': 'audit_test_question_headline',
            'broker_source': 'ET Markets',
            'ticker': 'TCS',
            'bullish_or_bearish': 'WATCH',
            'target_type': 'broker_pick',
            'timeframe': '1w',
            'confidence': 0.35,
            'dedupe_key': 'audit_test_question_headline',
            'raw_payload': {
                'headline': 'Should you buy, sell or hold TCS after Q4 results?',
                'classification': 'broker_prediction_candidate',
                'collector_source': 'news',
            },
        },
        {
            'prediction_id': 'audit_test_duplicate_a',
            'broker_source': 'Manual Inbox',
            'ticker': 'RELIANCE',
            'bullish_or_bearish': 'BULLISH',
            'target_type': 'top_pick',
            'timeframe': '1w',
            'confidence': 0.7,
            'dedupe_key': 'audit_test_duplicate_a',
            'raw_payload': {
                'headline': 'Manual inbox: Reliance accumulate on dips',
                'classification': 'broker_prediction_candidate',
                'direction_confidence': 'explicit',
                'collector_source': 'manual',
            },
        },
        {
            'prediction_id': 'audit_test_duplicate_b',
            'broker_source': 'Manual Inbox',
            'ticker': 'RELIANCE',
            'bullish_or_bearish': 'BULLISH',
            'target_type': 'top_pick',
            'timeframe': '1w',
            'confidence': 0.7,
            'dedupe_key': 'audit_test_duplicate_b',
            'raw_payload': {
                'headline': 'Manual inbox: Reliance accumulate on dips',
                'classification': 'broker_prediction_candidate',
                'direction_confidence': 'explicit',
                'collector_source': 'manual',
            },
        },
    ]

    inserted_ids: list[int] = []
    for payload in test_rows:
        row_id = _insert_test_row(payload)
        if row_id is None:
            return _fail(f'failed inserting test row {payload.get("prediction_id")}')
        inserted_ids.append(int(row_id))

    conn = get_connection()
    try:
        db_rows = [
            dict(row)
            for row in conn.execute(
                'SELECT * FROM broker_predictions WHERE id IN ({})'.format(
                    ','.join('?' for _ in inserted_ids),
                ),
                inserted_ids,
            ).fetchall()
        ]
    finally:
        conn.close()

    by_key = {row['dedupe_key']: row for row in db_rows}
    safe_audit = audit_broker_prediction_row(by_key['audit_test_safe_top_pick'])
    if safe_audit.get('safety') != 'safe':
        return _fail(f'safe top pick flagged unsafe: {safe_audit}')

    for key in (
        'audit_test_block_deal',
        'audit_test_credit_rating',
        'audit_test_question_headline',
    ):
        audit = audit_broker_prediction_row(by_key[key])
        if audit.get('safety') != 'unsafe':
            return _fail(f'{key} should be unsafe: {audit}')

    dup_a = audit_broker_prediction_row(by_key['audit_test_duplicate_a'])
    dup_b = audit_broker_prediction_row(
        by_key['audit_test_duplicate_b'],
        duplicate_ids={by_key['audit_test_duplicate_b']['id']},
    )
    if dup_b.get('bucket') != 'duplicate':
        return _fail(f'duplicate row not flagged: {dup_b}')
    if dup_a.get('safety') != 'safe':
        return _fail(f'first duplicate row should remain safe: {dup_a}')

    unsafe = find_unsafe_broker_predictions()
    unsafe_test_ids = {
        int(row['id'])
        for row in unsafe.get('unsafe_rows') or []
        if str(row.get('title') or '').startswith(('PB Fintech', "Moody's", 'Should you', 'Manual inbox'))
        or row.get('bucket') == 'duplicate'
    }
    expected_unsafe = {inserted_ids[1], inserted_ids[2], inserted_ids[3], inserted_ids[5]}
    if not expected_unsafe.issubset(unsafe_test_ids):
        return _fail(f'missing unsafe test ids expected={expected_unsafe} got={unsafe_test_ids}')

    removed = delete_broker_predictions_by_ids(inserted_ids)
    if removed != len(inserted_ids):
        return _fail(f'cleanup removed={removed} expected={len(inserted_ids)}')

    print(f'[BROKER_DB_AUDIT_CLEANUP_TEST] inserted={len(inserted_ids)} removed={removed}')
    print('BROKER_DB_AUDIT_CLEANUP_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
