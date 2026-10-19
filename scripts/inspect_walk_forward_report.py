#!/usr/bin/env python3
"""Print a read-only chronological evaluation of one historical simulation run."""

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
        description='Inspect chronological train/validation/test results for a stored simulation run.'
    )
    parser.add_argument('--market', default='INDIA', choices=('INDIA', 'USA', 'ALL'))
    parser.add_argument('--run-id', default=None, help='Specific stored simulation run ID')
    parser.add_argument(
        '--cost-bps', type=float, default=0.0,
        help='Round-trip transaction cost in basis points deducted per scored trade',
    )
    parser.add_argument('--json', action='store_true', help='Emit the complete JSON report')
    args = parser.parse_args()

    from backend.analytics.walk_forward_report import get_walk_forward_report

    report = get_walk_forward_report(
        market=None if args.market == 'ALL' else args.market,
        run_id=args.run_id,
        cost_bps=args.cost_bps,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get('ok') else 1

    print(
        f"[WALK_FORWARD] status={report.get('status')} "
        f"market={report.get('market')} run={report.get('run_id')}"
    )
    if not report.get('ok'):
        print(f"[WALK_FORWARD] error={report.get('status')}")
        return 1
    if not report.get('strategies'):
        print('[WALK_FORWARD] no strategy results in this run')
        return 0

    print('[WALK_FORWARD] strategy | split | dates | n | win% | avg net% | PF | ambiguous')
    for strategy in report['strategies']:
        for split_name in ('train', 'validation', 'test'):
            split = strategy['splits'][split_name]
            dates = '—'
            if split.get('from_date') and split.get('to_date'):
                dates = f"{split['from_date']}..{split['to_date']}"
            print(
                f"[WALK_FORWARD] {strategy['strategy']} | {split_name} | {dates} | "
                f"{split.get('scored_trades', 0)} | {split.get('win_rate_pct')} | "
                f"{split.get('mean_net_return_pct')} | {split.get('profit_factor')} | "
                f"{split.get('ambiguous_excluded', 0)}"
            )
    print(f"[WALK_FORWARD] note={report.get('disclaimer')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
