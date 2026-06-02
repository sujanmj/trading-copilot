#!/usr/bin/env python3
"""
Validate broker DB write gate enforcement on collector write path.

Prints BROKER_WRITE_GATE_ENFORCEMENT_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'BROKER_WRITE_GATE_ENFORCEMENT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_app_collector import (
        BrokerWriteGateMismatch,
        collect_broker_app_predictions,
        import_gated_broker_predictions,
    )
    from backend.collectors.broker_db_write_gate import evaluate_broker_write_eligibility
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    dry = collect_broker_app_predictions(limit=5, dry_run=True, write_broker_db=False)
    if dry.get('written_to_db', -1) != 0:
        return _fail(f'dry-run wrote_to_db={dry.get("written_to_db")}')

    review_only = collect_broker_app_predictions(limit=5, dry_run=False, write_broker_db=False)
    if review_only.get('written_to_db', -1) != 0:
        return _fail(f'review-only path wrote_to_db={review_only.get("written_to_db")}')

    if not init_market_memory_db():
        return _fail('market memory db unavailable')

    conn = get_connection()
    try:
        before = int(conn.execute('SELECT COUNT(*) AS cnt FROM broker_predictions').fetchone()['cnt'])
    finally:
        conn.close()

    gated = collect_broker_app_predictions(limit=10, dry_run=False, write_broker_db=True)
    if gated.get('ok') is not True and 'BROKER_WRITE_GATE_MISMATCH' not in str(gated.get('error') or ''):
        return _fail(f'write-broker-db failed: {gated.get("error")}')

    summary = (gated.get('broker_write_review') or {}).get('summary') or {}
    write_safe = int(summary.get('write_safe') or 0)
    written = int(gated.get('written_to_db') or 0)
    if gated.get('ok') is True and written > write_safe:
        return _fail(f'written_to_db={written} exceeds write_safe={write_safe}')

    conn = get_connection()
    try:
        after = int(conn.execute('SELECT COUNT(*) AS cnt FROM broker_predictions').fetchone()['cnt'])
    finally:
        conn.close()

    if gated.get('ok') is True and written == 0 and write_safe == 0:
        pass
    elif gated.get('ok') is True and written > 0 and after < before:
        return _fail('write-broker-db decreased row count unexpectedly')

    block_deal = evaluate_broker_write_eligibility({
        'ticker': 'POLICYBZR',
        'title': 'PB Fintech block deal; Goldman among buyers',
        'source': 'Moneycontrol',
        'direction': 'BULLISH',
        'classification': 'broker_prediction_candidate',
    })
    if block_deal.get('eligibility') == 'write_safe':
        return _fail('review_only block deal marked write_safe')

    with patch('backend.collectors.broker_app_collector.import_normalized_to_db', return_value=99):
        try:
            import_gated_broker_predictions([{
                'ticker': 'ICICIBANK',
                'headline': 'Nomura top pick: ICICI Bank recommends Buy',
                'broker_source': 'Economic Times',
                'stance': 'BULLISH',
                'direction_confidence': 'explicit',
                'classification': 'broker_prediction_candidate',
                'classification_reason': 'explicit_recommendation_with_ticker',
                'raw_payload': {'classification': 'broker_prediction_candidate', 'collector_source': 'news'},
            }])
        except BrokerWriteGateMismatch as exc:
            if 'BROKER_WRITE_GATE_MISMATCH' not in str(exc):
                return _fail(f'unexpected mismatch error: {exc}')
        else:
            return _fail('expected BrokerWriteGateMismatch when written_to_db exceeds write_safe')

    print(f'[BROKER_WRITE_GATE_ENFORCEMENT] dry_run_written={dry.get("written_to_db", 0)}')
    print(f'[BROKER_WRITE_GATE_ENFORCEMENT] review_only_written={review_only.get("written_to_db", 0)}')
    print(f'[BROKER_WRITE_GATE_ENFORCEMENT] write_safe={write_safe}')
    print(f'[BROKER_WRITE_GATE_ENFORCEMENT] written_to_db={written}')
    print('BROKER_WRITE_GATE_ENFORCEMENT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
