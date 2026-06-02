#!/usr/bin/env python3
"""
Delete legacy:* prediction rows that have a verified mm:* copy and no outcome refs.

Default is dry-run; pass --confirm to delete safe duplicates only.

Usage:
  python scripts/delete_legacy_market_memory_predictions.py
  python scripts/delete_legacy_market_memory_predictions.py --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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

    return {
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


def delete_legacy_market_memory_predictions(
    *,
    confirm: bool = False,
    only_prediction_ids: set[str] | None = None,
) -> dict[str, Any]:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, make_canonical_prediction_id

    init_market_memory_db()
    conn = get_connection()
    checked = 0
    safe_to_delete = 0
    blocked_missing_mm = 0
    blocked_outcome_refs = 0
    deleted = 0

    try:
        legacy_rows = conn.execute(
            """
            SELECT prediction_id, legacy_prediction_id, ticker, timestamp, source,
                   direction, confidence, confidence_label, market_regime, sector,
                   reasoning, signal_stack, raw_payload, created_at, updated_at
            FROM predictions
            WHERE prediction_id LIKE 'legacy:%'
            ORDER BY prediction_id
            """,
        ).fetchall()

        if only_prediction_ids is not None:
            legacy_rows = [
                row for row in legacy_rows
                if row['prediction_id'] in only_prediction_ids
            ]

        mm_ids = {
            row['prediction_id']
            for row in conn.execute(
                "SELECT prediction_id FROM predictions WHERE prediction_id LIKE 'mm:%'",
            ).fetchall()
        }

        legacy_ids_with_outcomes = {
            row['prediction_id']
            for row in conn.execute(
                """
                SELECT DISTINCT prediction_id
                FROM outcomes
                WHERE prediction_id LIKE 'legacy:%'
                """,
            ).fetchall()
        }

        for row in legacy_rows:
            checked += 1
            legacy_id = row['prediction_id']
            payload = _row_to_payload(row)
            expected_mm_id = make_canonical_prediction_id(payload)

            has_mm_copy = expected_mm_id in mm_ids
            has_outcome_ref = legacy_id in legacy_ids_with_outcomes

            if not has_mm_copy:
                blocked_missing_mm += 1
            if has_outcome_ref:
                blocked_outcome_refs += 1

            if has_mm_copy and not has_outcome_ref:
                safe_to_delete += 1
                if confirm:
                    cur = conn.execute(
                        'DELETE FROM predictions WHERE prediction_id = ?',
                        (legacy_id,),
                    )
                    deleted += cur.rowcount

        if confirm:
            conn.commit()
    finally:
        conn.close()

    return {
        'checked': checked,
        'safe_to_delete': safe_to_delete,
        'blocked_missing_mm': blocked_missing_mm,
        'blocked_outcome_refs': blocked_outcome_refs,
        'deleted': deleted,
        'dry_run': not confirm,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Delete legacy market memory predictions with verified mm:* copies',
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Delete safe legacy duplicates (default: dry-run only)',
    )
    args = parser.parse_args()

    summary = delete_legacy_market_memory_predictions(confirm=args.confirm)
    print(f"[DELETE_LEGACY] checked={summary['checked']}")
    print(f"[DELETE_LEGACY] safe_to_delete={summary['safe_to_delete']}")
    print(f"[DELETE_LEGACY] blocked_missing_mm={summary['blocked_missing_mm']}")
    print(f"[DELETE_LEGACY] blocked_outcome_refs={summary['blocked_outcome_refs']}")
    print(f"[DELETE_LEGACY] deleted={summary['deleted']}")
    print(f"[DELETE_LEGACY] dry_run={summary['dry_run']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
