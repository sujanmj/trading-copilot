#!/usr/bin/env python3
"""
Compact CLI for market holiday calendars.

Usage:
  python scripts/inspect_market_holidays.py
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


def _fmt_next(block: dict | None) -> str:
    if not block:
        return 'none'
    name = block.get('name') or 'Holiday'
    day = block.get('date') or '?'
    days = block.get('days_until')
    suffix = f' (+{days}d)' if days is not None else ''
    return f'{day} {name}{suffix}'


def main() -> int:
    from backend.analytics.market_calendar_router import get_holiday_calendar_summary

    summary = get_holiday_calendar_summary()
    india = summary.get('india') or {}
    usa = summary.get('usa') or {}

    print(f"[HOLIDAYS] india_year={india.get('year')}")
    print(f"[HOLIDAYS] india_holidays={india.get('holidays', 0)}")
    print(f"[HOLIDAYS] usa_year={usa.get('year')}")
    print(f"[HOLIDAYS] usa_holidays={usa.get('holidays', 0)}")
    print(f"[HOLIDAYS] usa_early_closes={usa.get('early_closes', 0)}")
    print(f"[HOLIDAYS] next_india_holiday={_fmt_next(india.get('next_holiday'))}")
    print(f"[HOLIDAYS] next_usa_holiday={_fmt_next(usa.get('next_holiday'))}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
