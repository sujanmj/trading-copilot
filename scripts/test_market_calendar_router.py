#!/usr/bin/env python3
"""
Smoke tests for market calendar router.

Usage:
  python scripts/test_market_calendar_router.py

Prints exactly MARKET_CALENDAR_ROUTER_OK on success; exits 1 on failure.
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
    print(f'MARKET_CALENDAR_ROUTER_FAIL: {msg}', file=sys.stderr)
    return 1


def _utc(iso: str) -> datetime:
    text = iso.replace('Z', '+00:00')
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> int:
    from backend.analytics.market_calendar_router import (
        MODE_INDIA,
        MODE_INDIA_POSTMARKET,
        MODE_INDIA_PREMARKET,
        MODE_RESEARCH,
        MODE_USA,
        MODE_USA_POSTMARKET,
        MODE_USA_PREMARKET,
        SESSION_CLOSED,
        SESSION_POSTMARKET,
        SESSION_PREMARKET,
        SESSION_REGULAR,
        get_active_market_mode,
        get_market_router_payload,
        get_market_session_status,
        get_next_market_open,
        is_india_market_day,
        is_us_market_day,
    )

    # Tuesday 2026-06-02 — India regular (10:30 IST)
    t_india_reg = _utc('2026-06-02T05:00:00+00:00')
    mode = get_active_market_mode(t_india_reg)
    if mode.get('active_mode') != MODE_INDIA:
        return _fail(f'expected INDIA_MODE at 05:00 UTC, got {mode.get("active_mode")}')
    if mode.get('india_session') != SESSION_REGULAR:
        return _fail(f'expected india regular session, got {mode.get("india_session")}')

    # India premarket (08:30 IST)
    t_india_pre = _utc('2026-06-02T03:00:00+00:00')
    mode = get_active_market_mode(t_india_pre)
    if mode.get('active_mode') != MODE_INDIA_PREMARKET:
        return _fail(f'expected INDIA_PREMARKET_MODE, got {mode.get("active_mode")}')

    # India postmarket (16:00 IST)
    t_india_post = _utc('2026-06-02T10:30:00+00:00')
    mode = get_active_market_mode(t_india_post)
    if mode.get('active_mode') != MODE_INDIA_POSTMARKET:
        return _fail(f'expected INDIA_POSTMARKET_MODE, got {mode.get("active_mode")}')

    # USA regular (11:00 ET on 2026-06-02 — EDT)
    t_usa_reg = _utc('2026-06-02T15:00:00+00:00')
    mode = get_active_market_mode(t_usa_reg)
    if mode.get('active_mode') != MODE_USA:
        return _fail(f'expected USA_MODE, got {mode.get("active_mode")}')
    if mode.get('usa_session') != SESSION_REGULAR:
        return _fail(f'expected usa regular session, got {mode.get("usa_session")}')

    # USA premarket (08:00 ET)
    t_usa_pre = _utc('2026-06-02T12:00:00+00:00')
    mode = get_active_market_mode(t_usa_pre)
    if mode.get('active_mode') != MODE_USA_PREMARKET:
        return _fail(f'expected USA_PREMARKET_MODE, got {mode.get("active_mode")}')

    # USA postmarket (18:00 ET)
    t_usa_post = _utc('2026-06-02T22:00:00+00:00')
    mode = get_active_market_mode(t_usa_post)
    if mode.get('active_mode') != MODE_USA_POSTMARKET:
        return _fail(f'expected USA_POSTMARKET_MODE, got {mode.get("active_mode")}')

    # Weekend — Saturday
    t_weekend = _utc('2026-06-06T12:00:00+00:00')
    mode = get_active_market_mode(t_weekend)
    if mode.get('active_mode') != MODE_RESEARCH:
        return _fail(f'expected RESEARCH_MODE on weekend, got {mode.get("active_mode")}')
    status = get_market_session_status(t_weekend)
    if status.get('india', {}).get('session') != SESSION_CLOSED:
        return _fail('expected india closed on weekend')
    if status.get('usa', {}).get('session') != SESSION_CLOSED:
        return _fail('expected usa closed on weekend')

    # India holiday — Republic Day 2026-01-26 (Monday)
    if is_india_market_day('2026-01-26'):
        return _fail('Republic Day should not be an India market day')
    t_holiday = _utc('2026-01-26T05:00:00+00:00')
    mode = get_active_market_mode(t_holiday)
    if mode.get('india_session') != SESSION_CLOSED:
        return _fail('India should be closed on Republic Day')

    # US holiday — Christmas 2026-12-25 (Friday)
    if is_us_market_day('2026-12-25'):
        return _fail('Christmas should not be a US market day')

    # next open helpers
    nxt_in = get_next_market_open('india', t_weekend)
    nxt_us = get_next_market_open('usa', t_weekend)
    if not nxt_in.get('ok') or not nxt_us.get('ok'):
        return _fail('get_next_market_open failed')
    if not nxt_in.get('next_open_utc') or not nxt_us.get('next_open_utc'):
        return _fail('next_open_utc missing')

    payload = get_market_router_payload()
    required = (
        'ok',
        'active_mode',
        'active_mode_label',
        'recommended_focus',
        'india_session',
        'usa_session',
        'india',
        'usa',
        'next_india_open',
        'next_usa_open',
        'holiday_calendar',
        'warnings',
    )
    for key in required:
        if key not in payload:
            return _fail(f'missing payload key: {key}')
    if payload.get('ok') is not True:
        return _fail('payload ok != true')

    print('MARKET_CALENDAR_ROUTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
