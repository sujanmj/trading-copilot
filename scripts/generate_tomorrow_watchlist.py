#!/usr/bin/env python3
"""
Generate tomorrow watchlist report from final confidence data.

Usage:
  python scripts/generate_tomorrow_watchlist.py
  python scripts/generate_tomorrow_watchlist.py --refresh-final-confidence --limit 25
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


def _fail(msg: str) -> int:
    print(f'TOMORROW_WATCHLIST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate tomorrow watchlist report.')
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--json', action='store_true', help='Print full report JSON to stdout')
    parser.add_argument(
        '--refresh-final-confidence',
        action='store_true',
        help='Regenerate final_confidence_report.json first',
    )
    args = parser.parse_args()

    if args.refresh_final_confidence:
        from backend.analytics.final_confidence_fusion import build_final_confidence_report
        from backend.utils.config import DATA_DIR

        fc_path = DATA_DIR / 'final_confidence_report.json'
        fc_report = build_final_confidence_report(limit=max(args.limit, 50))
        if fc_report.get('ok') is not True:
            return _fail(fc_report.get('error') or 'final confidence refresh failed')
        fc_path.parent.mkdir(parents=True, exist_ok=True)
        fc_path.write_text(json.dumps(fc_report, indent=2, default=str), encoding='utf-8')

    from backend.analytics.tomorrow_watchlist_report import write_tomorrow_watchlist_report

    report = write_tomorrow_watchlist_report(limit=args.limit)
    if report.get('ok') is not True:
        return _fail(report.get('error') or 'generate failed')

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    summary = report.get('summary') or {}
    mode = report.get('market_mode') or (report.get('market_mode_summary') or {}).get('active_mode')
    output = report.get('output_path') or 'data/tomorrow_watchlist_report.json'
    print(f'[TOMORROW_WATCHLIST] mode={mode}')
    print(f'[TOMORROW_WATCHLIST] raw_candidates={summary.get("raw_candidates", summary.get("checked", 0))}')
    print(f'[TOMORROW_WATCHLIST] unique_tickers={summary.get("unique_tickers", 0)}')
    print(f'[TOMORROW_WATCHLIST] duplicates_removed={summary.get("duplicates_removed", 0)}')
    print(f'[TOMORROW_WATCHLIST] watch={summary.get("watch", 0)}')
    print(f'[TOMORROW_WATCHLIST] avoid={summary.get("avoid", 0)}')
    print(f'[TOMORROW_WATCHLIST] no_decision={summary.get("no_decision", 0)}')
    print(f'[TOMORROW_WATCHLIST] output={output}')
    print('TOMORROW_WATCHLIST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
