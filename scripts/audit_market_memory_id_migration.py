#!/usr/bin/env python3
"""
Read-only audit of legacy vs mm:* prediction_id migration readiness.

Usage:
  python scripts/audit_market_memory_id_migration.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
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


def run_audit() -> dict[str, int]:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db, make_canonical_prediction_id

    if not init_market_memory_db():
        print('[ID_AUDIT] error=init_market_memory_db failed', file=sys.stderr)
        raise SystemExit(1)

    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')

        total = int(conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0])
        legacy_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE prediction_id LIKE 'legacy:%'",
            ).fetchone()[0]
        )
        mm_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE prediction_id LIKE 'mm:%'",
            ).fetchone()[0]
        )

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

        mm_ids = {
            row['prediction_id']
            for row in conn.execute(
                "SELECT prediction_id FROM predictions WHERE prediction_id LIKE 'mm:%'",
            ).fetchall()
        }

        legacy_with_mm_copy = 0
        legacy_missing_mm_copy = 0
        recomputed_mm_targets: list[str] = []

        for row in legacy_rows:
            payload = _row_to_payload(row)
            expected_mm_id = make_canonical_prediction_id(payload)
            recomputed_mm_targets.append(expected_mm_id)
            if expected_mm_id in mm_ids:
                legacy_with_mm_copy += 1
            else:
                legacy_missing_mm_copy += 1

        duplicate_mm_ids = sum(1 for _count in Counter(recomputed_mm_targets).values() if _count > 1)

        outcome_refs_legacy = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM outcomes
                WHERE prediction_id LIKE 'legacy:%'
                """,
            ).fetchone()[0]
        )

        return {
            'total': total,
            'legacy': legacy_count,
            'mm': mm_count,
            'legacy_with_mm_copy': legacy_with_mm_copy,
            'legacy_missing_mm_copy': legacy_missing_mm_copy,
            'duplicate_mm_ids': duplicate_mm_ids,
            'outcome_refs_legacy': outcome_refs_legacy,
        }
    finally:
        conn.close()


def main() -> int:
    stats = run_audit()
    print(f"[ID_AUDIT] total={stats['total']}")
    print(f"[ID_AUDIT] legacy={stats['legacy']}")
    print(f"[ID_AUDIT] mm={stats['mm']}")
    print(f"[ID_AUDIT] legacy_with_mm_copy={stats['legacy_with_mm_copy']}")
    print(f"[ID_AUDIT] legacy_missing_mm_copy={stats['legacy_missing_mm_copy']}")
    print(f"[ID_AUDIT] duplicate_mm_ids={stats['duplicate_mm_ids']}")
    print(f"[ID_AUDIT] outcome_refs_legacy={stats['outcome_refs_legacy']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
