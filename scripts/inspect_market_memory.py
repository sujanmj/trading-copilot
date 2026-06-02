#!/usr/bin/env python3
"""
Inspect canonical market memory DB contents.

Usage:
  python scripts/inspect_market_memory.py
  python scripts/inspect_market_memory.py --details TICKER_OR_ID
  python scripts/inspect_market_memory.py --details TICKER_OR_ID --raw
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


def _parse_json_field(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_prediction(conn, target: str):
    target = target.strip()
    if not target:
        return None

    row = conn.execute(
        """
        SELECT prediction_id, ticker, timestamp, source, direction,
               confidence, confidence_label, market_regime, sector, reasoning,
               signal_stack, raw_payload
        FROM predictions
        WHERE prediction_id = ?
        """,
        (target,),
    ).fetchone()
    if row is not None:
        return row

    ticker = target.upper()
    return conn.execute(
        """
        SELECT prediction_id, ticker, timestamp, source, direction,
               confidence, confidence_label, market_regime, sector, reasoning,
               signal_stack, raw_payload
        FROM predictions
        WHERE ticker = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (ticker,),
    ).fetchone()


def _print_prediction_details(row, *, show_raw: bool = False) -> None:
    print(f"[DETAILS] prediction_id={row['prediction_id']}")
    print(f"[DETAILS] ticker={row['ticker']}")
    print(f"[DETAILS] timestamp={row['timestamp']}")
    print(f"[DETAILS] source={row['source']}")
    print(f"[DETAILS] direction={row['direction']}")
    print(f"[DETAILS] confidence={row['confidence']}")
    print(f"[DETAILS] confidence_label={row['confidence_label']}")
    print(f"[DETAILS] market_regime={row['market_regime']}")
    print(f"[DETAILS] sector={row['sector']}")
    print(f"[DETAILS] reasoning={row['reasoning']}")

    signal_stack = _parse_json_field(row['signal_stack'])
    print("[DETAILS] signal_stack=")
    if signal_stack is None:
        print("  (empty or invalid JSON)")
    else:
        print(json.dumps(signal_stack, indent=2, default=str))

    raw_payload = _parse_json_field(row['raw_payload'])
    if show_raw:
        print("[DETAILS] raw_payload=")
        if raw_payload is None:
            print("  (empty or invalid JSON)")
        else:
            print(json.dumps(raw_payload, indent=2, default=str))
    else:
        print("[DETAILS] raw_payload_keys=")
        if isinstance(raw_payload, dict):
            for key in sorted(raw_payload.keys()):
                print(f"  {key}")
        elif raw_payload is None:
            print("  (empty or invalid JSON)")
        else:
            print(f"  (non-dict payload type: {type(raw_payload).__name__})")

    if isinstance(signal_stack, dict) and 'broker_consensus' in signal_stack:
        print("[DETAILS] broker_consensus=")
        print(json.dumps(signal_stack['broker_consensus'], indent=2, default=str))


def _print_compact_inspect(stats, conn) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect canonical market memory DB.')
    parser.add_argument(
        '--details',
        metavar='TICKER_OR_ID',
        help='Show full details for a prediction by prediction_id or ticker',
    )
    parser.add_argument(
        '--raw',
        action='store_true',
        help='With --details, pretty-print raw_payload JSON instead of key names only',
    )
    args = parser.parse_args()

    if args.raw and not args.details:
        parser.error('--raw requires --details')

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
        if args.details:
            row = _find_prediction(conn, args.details)
            if row is None:
                print(f"[DETAILS] not found: {args.details}", file=sys.stderr)
                return 1
            _print_prediction_details(row, show_raw=args.raw)
        else:
            _print_compact_inspect(stats, conn)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
