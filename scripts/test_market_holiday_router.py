#!/usr/bin/env python3
"""
Smoke tests for holiday-aware market calendar router.

Usage:
  python scripts/test_market_holiday_router.py

Prints exactly MARKET_HOLIDAY_ROUTER_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'MARKET_HOLIDAY_ROUTER_FAIL: {msg}', file=sys.stderr)
    return 1


def _utc(iso: str) -> datetime:
    text = iso.replace('Z', '+00:00')
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> int:
    from backend.analytics.market_calendar_router import (
        SESSION_CLOSED,
        SESSION_REGULAR,
        get_market_router_payload,
        get_market_session_status,
    )

    # Known India holiday — Republic Day 2026-01-26 (Monday)
    t_india_holiday = _utc('2026-01-26T05:00:00+00:00')
    status = get_market_session_status(t_india_holiday)
    india = status.get('india') or {}
    if india.get('session') != SESSION_CLOSED:
        return _fail('India should be closed on Republic Day')
    if 'Republic Day' not in str(india.get('session_label') or ''):
        return _fail('India holiday label should mention Republic Day')

    # Known USA holiday — Christmas 2026-12-25 (Friday)
    t_usa_holiday = _utc('2026-12-25T15:00:00+00:00')
    status = get_market_session_status(t_usa_holiday)
    usa = status.get('usa') or {}
    if usa.get('session') != SESSION_CLOSED:
        return _fail('USA should be closed on Christmas')
    if 'Christmas' not in str(usa.get('session_label') or ''):
        return _fail('USA holiday label should mention Christmas')

    # Normal weekday — Tuesday 2026-06-02 India regular session (10:30 IST)
    t_weekday = _utc('2026-06-02T05:00:00+00:00')
    status = get_market_session_status(t_weekday)
    if (status.get('india') or {}).get('session') != SESSION_REGULAR:
        return _fail('India should be in regular session on 2026-06-02')

    # Same weekday — USA regular session (11:00 ET)
    t_usa_weekday = _utc('2026-06-02T15:00:00+00:00')
    status = get_market_session_status(t_usa_weekday)
    if (status.get('usa') or {}).get('session') != SESSION_REGULAR:
        return _fail('USA should be in regular session on 2026-06-02')

    # Weekend — Saturday 2026-06-06
    t_weekend = _utc('2026-06-06T12:00:00+00:00')
    status = get_market_session_status(t_weekend)
    if (status.get('india') or {}).get('session') != SESSION_CLOSED:
        return _fail('India should be closed on weekend')
    if (status.get('usa') or {}).get('session') != SESSION_CLOSED:
        return _fail('USA should be closed on weekend')

    # USA early close — Day after Thanksgiving 2026-11-27
    t_early_open = _utc('2026-11-27T17:00:00+00:00')  # 12:00 ET
    status = get_market_session_status(t_early_open)
    usa = status.get('usa') or {}
    if usa.get('session') != SESSION_REGULAR:
        return _fail('USA should be regular before early close on 2026-11-27')
    if usa.get('early_close_today') is not True:
        return _fail('USA early_close_today should be true on 2026-11-27')
    if 'usa_early_close_today' not in (status.get('warnings') or []):
        return _fail('expected usa_early_close_today warning on early close day')

    t_early_after = _utc('2026-11-27T19:00:00+00:00')  # 14:00 ET — after 13:00 close
    status = get_market_session_status(t_early_after)
    usa = status.get('usa') or {}
    if usa.get('session') != SESSION_CLOSED:
        return _fail('USA should be closed after early close time on 2026-11-27')
    if usa.get('is_open') is True:
        return _fail('USA is_open should be false after early close')

    # Valid holiday files — no incomplete warning
    payload = get_market_router_payload()
    warnings = payload.get('warnings') or []
    if 'holiday_calendar_incomplete' in warnings:
        return _fail('holiday_calendar_incomplete should not appear when files are valid')
    calendar = payload.get('holiday_calendar') or {}
    if calendar.get('calendar_ok') is not True:
        return _fail('holiday_calendar.calendar_ok should be true with valid files')
    if 'holiday_calendar' not in payload:
        return _fail('payload missing holiday_calendar')

    print('MARKET_HOLIDAY_ROUTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
