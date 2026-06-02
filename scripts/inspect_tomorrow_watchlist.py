#!/usr/bin/env python3
"""
Inspect tomorrow watchlist report.

Usage:
  python scripts/inspect_tomorrow_watchlist.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

REPORT_PATH = PROJECT_ROOT / 'data' / 'tomorrow_watchlist_report.json'


def main() -> int:
    from backend.analytics.tomorrow_watchlist_report import _load_json

    report = _load_json(REPORT_PATH)
    if not report or report.get('ok') is not True:
        print('[TOMORROW] report missing or invalid — run generate_tomorrow_watchlist.py', file=sys.stderr)
        return 1

    summary = report.get('summary') or {}
    mode = report.get('market_mode') or (report.get('market_mode_summary') or {}).get('active_mode')
    print(f'[TOMORROW] market_mode={mode}')
    print(
        f'[TOMORROW] watch={summary.get("watch", 0)} '
        f'avoid={summary.get("avoid", 0)} '
        f'no_decision={summary.get("no_decision", 0)}',
    )
    print('[TOMORROW] top:')
    for item in (report.get('top_watchlist') or [])[:10]:
        print(
            f"  {item.get('ticker')} | {item.get('score')} | {item.get('decision')} | "
            f"{item.get('reason')}",
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
