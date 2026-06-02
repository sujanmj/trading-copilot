#!/usr/bin/env python3
"""
Compare canonical predictions vs external broker picks.

Usage:
  python scripts/compare_our_predictions_vs_brokers.py
  python scripts/compare_our_predictions_vs_brokers.py --ticker RELIANCE --json
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
    parser = argparse.ArgumentParser(
        description='Compare our predictions vs broker evidence'
    )
    parser.add_argument('--ticker', default=None, help='Optional ticker filter')
    parser.add_argument('--json', action='store_true', help='Emit JSON only')
    args = parser.parse_args()

    from backend.analytics.broker_prediction_intelligence import (
        compare_our_predictions_vs_brokers,
    )

    report = compare_our_predictions_vs_brokers(ticker=args.ticker)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print('[OUR_VS_BROKER]')
        print(json.dumps(report, indent=2, default=str))
        rate = report.get('agreement_rate')
        print(
            f"[OUR_VS_BROKER] agreements={report.get('agreements')} "
            f"conflicts={report.get('conflicts')} rate={rate}"
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
