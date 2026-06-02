#!/usr/bin/env python3
"""
Inspect broker prediction intelligence summary.

Usage:
  python scripts/inspect_broker_prediction_intelligence.py
  python scripts/inspect_broker_prediction_intelligence.py --ticker RELIANCE
  python scripts/inspect_broker_prediction_intelligence.py --source Moneycontrol --json
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


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect broker prediction intelligence')
    parser.add_argument('--source', default=None, help='Filter by broker source')
    parser.add_argument('--ticker', default=None, help='Filter by ticker')
    parser.add_argument('--json', action='store_true', help='Emit JSON payload')
    args = parser.parse_args()

    from backend.analytics.broker_prediction_intelligence import (
        compare_our_predictions_vs_brokers,
        get_broker_intelligence_dashboard,
        get_source_intelligence,
        get_ticker_intelligence,
    )

    if args.ticker:
        payload = get_ticker_intelligence(args.ticker)
    elif args.source:
        payload = get_source_intelligence(args.source)
    else:
        payload = get_broker_intelligence_dashboard()
        if args.json:
            payload = {
                'dashboard': payload,
                'comparison': compare_our_predictions_vs_brokers(),
            }

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print('[BROKER_INTEL] summary')
        print(json.dumps(payload, indent=2, default=str))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
