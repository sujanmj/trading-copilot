#!/usr/bin/env python3
"""
Inspect historical price anomalies with readable detail lines.

Usage:
  python scripts/inspect_historical_anomalies.py
  python scripts/inspect_historical_anomalies.py --ticker RELIANCE
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
    print(f'HISTORICAL_ANOMALY_INSPECT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect historical price anomalies.')
    parser.add_argument('--ticker', help='Filter anomalies to one ticker')
    args = parser.parse_args()

    from backend.analytics.historical_price_audit import audit_historical_prices
    from backend.storage.historical_market_store import get_historical_db_path, init_db

    if not init_db():
        return _fail('init_db failed')

    db_path = get_historical_db_path()
    if not db_path.exists():
        return _fail(f'database missing: {db_path}')

    audit = audit_historical_prices(ticker=args.ticker)
    details = audit.get('anomaly_details') or []
    print(f'[HIST_ANOMALY] anomalies={audit.get("anomalies", len(details))}')

    for item in details:
        print(f'[HIST_ANOMALY] ticker={item.get("ticker")}')
        print(f'[HIST_ANOMALY] date={item.get("date")}')
        print(f'[HIST_ANOMALY] reason={item.get("reason") or item.get("type")}')
        if item.get('open') is not None:
            print(f'[HIST_ANOMALY] open={item.get("open")}')
        if item.get('high') is not None:
            print(f'[HIST_ANOMALY] high={item.get("high")}')
        if item.get('low') is not None:
            print(f'[HIST_ANOMALY] low={item.get("low")}')
        if item.get('close') is not None:
            print(f'[HIST_ANOMALY] close={item.get("close")}')
        if item.get('volume') is not None:
            print(f'[HIST_ANOMALY] volume={item.get("volume")}')
        if item.get('source'):
            print(f'[HIST_ANOMALY] source={item.get("source")}')

    print('HISTORICAL_ANOMALY_INSPECT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
