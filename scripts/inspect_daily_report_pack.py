#!/usr/bin/env python3
"""Inspect latest daily report pack."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LATEST = PROJECT_ROOT / 'data' / 'daily_report_pack_latest.json'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from backend.analytics.daily_report_pack import _load_json

    report = _load_json(LATEST)
    exists = report is not None and report.get('ok') is True
    print(f'[DAILY_PACK] exists={exists}')
    if not exists:
        return 1

    tw = report.get('tomorrow_watchlist') or {}
    files = report.get('files') or {}
    print(f'[DAILY_PACK] generated_at={report.get("generated_at")}')
    print(f'[DAILY_PACK] market_mode={report.get("market_mode")}')
    print(
        f'[DAILY_PACK] watch={tw.get("watch", 0)} '
        f'avoid={tw.get("avoid", 0)} '
        f'no_decision={tw.get("no_decision", 0)}',
    )
    print(f'[DAILY_PACK] risk_notes={len(report.get("risk_notes") or [])}')
    print(f'[DAILY_PACK] files={",".join(f"{k}={v}" for k, v in files.items())}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
