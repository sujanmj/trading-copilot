#!/usr/bin/env python3
"""
Inspect broker consensus for a ticker.

Usage:
  python scripts/inspect_broker_consensus.py --ticker RELIANCE
  python scripts/inspect_broker_consensus.py --ticker RELIANCE --timeframe 1d
  python scripts/inspect_broker_consensus.py --all
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


def _show_top_tickers(limit: int = 20) -> int:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    if not init_market_memory_db():
        print('[BROKER_CONSENSUS] init_market_memory_db returned False', file=sys.stderr)
        return 1

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT ticker, COUNT(*) AS pick_count
            FROM broker_predictions
            GROUP BY ticker
            ORDER BY pick_count DESC, ticker ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print('[BROKER_CONSENSUS] no broker_predictions rows found')
        return 0

    print('[BROKER_CONSENSUS] top tickers in broker_predictions:')
    for row in rows:
        print(f"  {row['ticker']} | picks={row['pick_count']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect broker consensus for a ticker')
    parser.add_argument('--ticker', default=None, help='Stock ticker symbol')
    parser.add_argument('--timeframe', default=None, help='Optional broker timeframe filter')
    parser.add_argument(
        '--all',
        action='store_true',
        help='List top tickers in broker_predictions when --ticker is omitted',
    )
    args = parser.parse_args()

    if args.ticker:
        from backend.analytics.broker_consensus_engine import get_consensus_for_ticker

        consensus = get_consensus_for_ticker(args.ticker, timeframe=args.timeframe)
        print(json.dumps(consensus, indent=2, default=str))
        return 0

    if args.all:
        return _show_top_tickers()

    parser.error('one of --ticker or --all is required')


if __name__ == '__main__':
    raise SystemExit(main())
