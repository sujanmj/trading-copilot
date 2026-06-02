#!/usr/bin/env python3
"""
Inspect active historical price anomaly quarantine records.

Usage:
  python scripts/inspect_historical_anomaly_quarantine.py
  python scripts/inspect_historical_anomaly_quarantine.py --ticker GOLDBEES
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'HISTORICAL_ANOMALY_QUARANTINE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect historical anomaly quarantine.')
    parser.add_argument('--ticker', help='Filter to one ticker')
    parser.add_argument('--market', help='Filter to one market')
    args = parser.parse_args()

    from backend.storage.historical_market_store import (
        get_active_anomalies,
        get_historical_db_path,
        get_stats,
        init_db,
    )

    if not init_db():
        return _fail('init_db failed')

    db_path = get_historical_db_path()
    if not db_path.exists():
        return _fail(f'database missing: {db_path}')

    stats = get_stats()
    active = int(stats.get('historical_price_anomalies_active') or 0)
    warning = int(stats.get('historical_price_anomalies_warning') or 0)
    suspicious = int(stats.get('historical_price_anomalies_suspicious') or 0)
    exclude = int(stats.get('historical_price_anomalies_exclude') or 0)

    print(f'[HIST_ANOMALY_Q] active={active}')
    print(f'[HIST_ANOMALY_Q] warning={warning}')
    print(f'[HIST_ANOMALY_Q] suspicious={suspicious}')
    print(f'[HIST_ANOMALY_Q] exclude_from_simulation={exclude}')

    rows = get_active_anomalies(market=args.market, ticker=args.ticker)
    for row in rows:
        print(
            '[HIST_ANOMALY_Q] '
            f'ticker={row.get("ticker")} '
            f'date={row.get("date")} '
            f'reason={row.get("reason")} '
            f'severity={row.get("severity")}'
        )

    print('HISTORICAL_ANOMALY_QUARANTINE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
