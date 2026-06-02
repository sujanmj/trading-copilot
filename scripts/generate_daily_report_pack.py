#!/usr/bin/env python3
"""
Generate daily local report pack JSON.

Usage:
  python scripts/generate_daily_report_pack.py --refresh --limit 25
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
    print(f'DAILY_REPORT_PACK_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate daily report pack.')
    parser.add_argument('--refresh', action='store_true', help='Refresh component reports first')
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    if not init_market_memory_db():
        return _fail('market memory init failed')

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)
    outcomes_before = int(stats_before.get('outcomes') or 0)

    from backend.analytics.daily_report_pack import generate_daily_report_pack

    pack = generate_daily_report_pack(refresh=args.refresh, limit=args.limit)
    if pack.get('ok') is not True:
        return _fail(pack.get('error') or 'generate failed')

    stats_after = get_market_memory_stats()
    if int(stats_after.get('predictions') or 0) != preds_before:
        return _fail('canonical predictions changed')
    if int(stats_after.get('outcomes') or 0) != outcomes_before:
        return _fail('canonical outcomes changed')

    if args.json:
        print(json.dumps(pack, indent=2, default=str))
        return 0

    fc = pack.get('final_confidence') or {}
    tw = pack.get('tomorrow_watchlist') or {}
    cal = pack.get('confidence_calibration') or {}
    refresh = pack.get('refresh_status') or {}

    print(f'[DAILY_PACK] mode={pack.get("market_mode")}')
    print(f'[DAILY_PACK] final_confidence={"ok" if fc.get("ok") else "fail"}')
    print(f'[DAILY_PACK] tomorrow_watchlist={"ok" if tw.get("ok") else "fail"}')
    print(f'[DAILY_PACK] calibration={"ok" if cal.get("ok") else "fail"}')
    if args.refresh:
        print(f'[DAILY_PACK] refresh_final_confidence={refresh.get("final_confidence", "skipped")}')
        print(f'[DAILY_PACK] refresh_tomorrow_watchlist={refresh.get("tomorrow_watchlist", "skipped")}')
        print(f'[DAILY_PACK] refresh_calibration={refresh.get("calibration", "skipped")}')
    print(f'[DAILY_PACK] watch={tw.get("watch", 0)}')
    print(f'[DAILY_PACK] avoid={tw.get("avoid", 0)}')
    print(f'[DAILY_PACK] no_decision={tw.get("no_decision", 0)}')
    print(f'[DAILY_PACK] output={pack.get("output_path", "data/daily_report_pack_latest.json")}')
    print('DAILY_REPORT_PACK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
