#!/usr/bin/env python3
"""
Inspect canonical market memory DB contents.

Usage:
  python scripts/inspect_market_memory.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def main() -> int:
    from backend.storage.market_memory_db import get_connection, get_market_memory_stats

    stats = get_market_memory_stats()
    print(f"[INSPECT] db_path={stats.get('db_path')}")
    print(f"[INSPECT] db_exists={stats.get('db_exists')}")
    print(
        "[INSPECT] stats="
        + json.dumps(
            {
                k: stats[k]
                for k in (
                    "predictions",
                    "broker_predictions",
                    "outcomes",
                    "market_context_snapshots",
                )
            },
            default=str,
        )
    )

    if not stats.get("db_exists"):
        return 0

    conn = get_connection()
    try:
        contexts = conn.execute(
            """
            SELECT context_id, timestamp, market_regime, vix, crude,
                   global_sentiment, india_sentiment, sector_strength
            FROM market_context_snapshots
            ORDER BY timestamp DESC
            LIMIT 5
            """
        ).fetchall()
        preds = conn.execute(
            """
            SELECT prediction_id, ticker, timestamp, source, direction,
                   confidence, confidence_label
            FROM predictions
            ORDER BY timestamp DESC
            LIMIT 5
            """
        ).fetchall()
        outs = conn.execute(
            """
            SELECT prediction_id, resolved_as, expiry_result, holding_period,
                   actual_move, created_at
            FROM outcomes
            ORDER BY created_at DESC
            LIMIT 5
            """
        ).fetchall()
    finally:
        conn.close()

    print("[INSPECT] last_5_market_context_snapshots:")
    for row in contexts:
        print(
            f"  {row['context_id']} | {row['timestamp']} | regime={row['market_regime']} | "
            f"vix={row['vix']} | crude={row['crude']}"
        )

    print(f"[INSPECT] predictions_count={stats.get('predictions', 0)}")
    print("[INSPECT] last_5_predictions:")
    for row in preds:
        conf = row['confidence_label'] or row['confidence']
        print(
            f"  {row['prediction_id']} | {row['ticker']} | {row['timestamp']} | "
            f"{row['source']} | {row['direction']} | conf={conf}"
        )

    print("[INSPECT] last_5_outcomes:")
    for row in outs:
        print(
            f"  {row['prediction_id']} | {row['resolved_as']} | {row['expiry_result']} | "
            f"{row['holding_period']} | move={row['actual_move']} | {row['created_at']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
