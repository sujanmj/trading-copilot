#!/usr/bin/env python3
"""
Migrate legacy: prediction_ids to deterministic mm:* canonical IDs.

Copies rows under new IDs; leaves legacy rows unless --delete-legacy.

Usage:
  python scripts/migrate_legacy_market_memory_ids.py [--dry-run] [--delete-legacy]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _row_to_payload(row) -> dict:
    raw_payload = row['raw_payload']
    if isinstance(raw_payload, str) and raw_payload.strip():
        try:
            raw_payload = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError):
            raw_payload = {}
    if not isinstance(raw_payload, dict):
        raw_payload = {}

    signal_stack = row['signal_stack']
    if isinstance(signal_stack, str) and signal_stack.strip():
        try:
            signal_stack = json.loads(signal_stack)
        except (json.JSONDecodeError, TypeError):
            signal_stack = None

    payload = {
        'ticker': row['ticker'],
        'timestamp': row['timestamp'],
        'source': row['source'],
        'direction': row['direction'],
        'confidence': row['confidence'],
        'confidence_label': row['confidence_label'],
        'market_regime': row['market_regime'],
        'sector': row['sector'],
        'reasoning': row['reasoning'],
        'signal_stack': signal_stack,
        'raw_payload': raw_payload,
        'legacy_prediction_id': row['legacy_prediction_id'],
        'created_at': row['created_at'],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description='Migrate legacy market memory prediction IDs.')
    parser.add_argument('--dry-run', action='store_true', help='Report only; no DB writes')
    parser.add_argument(
        '--delete-legacy',
        action='store_true',
        help='Delete legacy:* prediction rows after successful copy (default: keep)',
    )
    args = parser.parse_args()

    from backend.storage.market_memory_db import (
        get_connection,
        init_market_memory_db,
        make_canonical_prediction_id,
    )

    if not init_market_memory_db():
        print('[MIGRATE_IDS] error=init_market_memory_db failed', file=sys.stderr)
        return 1

    legacy_found = 0
    would_create = 0
    created = 0
    skipped_existing = 0
    outcomes_relinked = 0

    conn = get_connection()
    try:
        legacy_rows = conn.execute(
            """
            SELECT prediction_id, legacy_prediction_id, ticker, timestamp, source,
                   direction, confidence, confidence_label, market_regime, sector,
                   reasoning, signal_stack, raw_payload, created_at, updated_at
            FROM predictions
            WHERE prediction_id LIKE 'legacy:%'
            ORDER BY prediction_id
            """
        ).fetchall()
        legacy_found = len(legacy_rows)

        for row in legacy_rows:
            old_id = row['prediction_id']
            payload = _row_to_payload(row)
            new_id = make_canonical_prediction_id(payload)

            exists = conn.execute(
                'SELECT 1 FROM predictions WHERE prediction_id = ?',
                (new_id,),
            ).fetchone()
            if exists is not None:
                skipped_existing += 1
                continue

            would_create += 1
            if args.dry_run:
                continue

            conn.execute(
                """
                INSERT INTO predictions (
                    prediction_id, legacy_prediction_id, ticker, timestamp, source,
                    direction, confidence, confidence_label, market_regime, sector,
                    reasoning, signal_stack, raw_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    payload.get('legacy_prediction_id'),
                    row['ticker'],
                    row['timestamp'],
                    row['source'],
                    row['direction'],
                    row['confidence'],
                    row['confidence_label'],
                    row['market_regime'],
                    row['sector'],
                    row['reasoning'],
                    row['signal_stack'],
                    row['raw_payload'],
                    row['created_at'],
                    row['updated_at'],
                ),
            )
            created += 1

            outcome_rows = conn.execute(
                'SELECT * FROM outcomes WHERE prediction_id = ?',
                (old_id,),
            ).fetchall()
            for outcome in outcome_rows:
                conflict = conn.execute(
                    """
                    SELECT 1 FROM outcomes
                    WHERE prediction_id = ? AND holding_period = ?
                    """,
                    (new_id, outcome['holding_period']),
                ).fetchone()
                if conflict is not None:
                    continue
                conn.execute(
                    """
                    INSERT INTO outcomes (
                        prediction_id, actual_move, high, low, expiry_result, resolved_as,
                        holding_period, market_context, vix, crude, fii_dii, global_sentiment,
                        india_sentiment, sector_strength, market_regime, raw_payload,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id,
                        outcome['actual_move'],
                        outcome['high'],
                        outcome['low'],
                        outcome['expiry_result'],
                        outcome['resolved_as'],
                        outcome['holding_period'],
                        outcome['market_context'],
                        outcome['vix'],
                        outcome['crude'],
                        outcome['fii_dii'],
                        outcome['global_sentiment'],
                        outcome['india_sentiment'],
                        outcome['sector_strength'],
                        outcome['market_regime'],
                        outcome['raw_payload'],
                        outcome['created_at'],
                        outcome['updated_at'],
                    ),
                )
                outcomes_relinked += 1

        if not args.dry_run and args.delete_legacy and created > 0:
            for row in legacy_rows:
                conn.execute(
                    'DELETE FROM predictions WHERE prediction_id = ?',
                    (row['prediction_id'],),
                )

        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    delete_legacy = bool(args.delete_legacy)
    print(f'[MIGRATE_IDS] legacy_found={legacy_found}')
    print(f'[MIGRATE_IDS] would_create={would_create}')
    print(f'[MIGRATE_IDS] created={created}')
    print(f'[MIGRATE_IDS] skipped_existing={skipped_existing}')
    print(f'[MIGRATE_IDS] outcomes_relinked={outcomes_relinked}')
    print(f'[MIGRATE_IDS] delete_legacy={delete_legacy}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
