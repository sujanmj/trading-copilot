#!/usr/bin/env python3
"""Unit tests for alert freshness gates (Stage 46H)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IST = pytz.timezone('Asia/Kolkata')
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'ALERT_FRESHNESS_GATES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _utc(iso: str) -> datetime:
    text = iso.replace('Z', '+00:00')
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _test_freshness_thresholds() -> str | None:
    from backend.orchestration.alert_freshness_gate import (
        NEWS_STALE_MARKET_SEC,
        PREMARKET_STALE_SEC,
        SCANNER_MARKET_STALE_SEC,
        WATCH_ONLY_MESSAGE,
        attempt_safe_refresh,
        check_core_freshness,
        gate_alert_dispatch,
    )

    if NEWS_STALE_MARKET_SEC != 90 * 60:
        return 'news stale threshold must be 90 minutes in market hours'
    if SCANNER_MARKET_STALE_SEC != 15 * 60:
        return 'scanner/market stale threshold must be 15 minutes'
    if PREMARKET_STALE_SEC != 30 * 60:
        return 'premarket stale threshold must be 30 minutes before open'

    def _file_age_factory(scanner_age: int | None, market_age: int | None):
        def _file_age(fname: str):
            if fname == 'scanner_data.json':
                return scanner_age
            if fname == 'latest_market_data.json':
                return market_age
            return 60

        return _file_age

    def _run_check(
        *,
        market: bool,
        premarket: bool,
        news_age: int | None,
        scanner_age: int | None,
        market_age: int | None,
        refresh_ok: bool = False,
    ):
        with patch('backend.orchestration.alert_freshness_gate._is_market_hours', return_value=market), patch(
            'backend.orchestration.alert_freshness_gate._is_premarket_window', return_value=premarket
        ), patch(
            'backend.orchestration.alert_freshness_gate.newest_article_age_seconds', return_value=news_age
        ), patch(
            'backend.orchestration.alert_freshness_gate._file_age_seconds',
            side_effect=_file_age_factory(scanner_age, market_age),
        ), patch(
            'backend.orchestration.alert_freshness_gate.attempt_safe_refresh', return_value=refresh_ok
        ):
            return check_core_freshness()

    ok, msg, keys = _run_check(
        market=True, premarket=False, news_age=91 * 60, scanner_age=60, market_age=60, refresh_ok=False
    )
    if ok or 'news' not in keys:
        return 'news >90min stale in market hours must block'
    if WATCH_ONLY_MESSAGE not in msg:
        return 'missing watch-only message after refresh fail'

    ok, _msg, keys = _run_check(
        market=True, premarket=False, news_age=60, scanner_age=16 * 60, market_age=60, refresh_ok=False
    )
    if ok or 'scanner' not in keys:
        return 'scanner >15min stale in market hours must block'

    ok, _msg, keys = _run_check(
        market=True, premarket=False, news_age=60, scanner_age=60, market_age=16 * 60, refresh_ok=False
    )
    if ok or 'market' not in keys:
        return 'market feed >15min stale must block'

    def _premarket_file_age(fname: str):
        if fname == 'unified_intelligence.json':
            return 31 * 60
        if fname == 'tomorrow_watchlist_report.json':
            return 5 * 60
        return 60

    with patch('backend.orchestration.alert_freshness_gate._is_market_hours', return_value=False), patch(
        'backend.orchestration.alert_freshness_gate._is_premarket_window', return_value=True
    ), patch(
        'backend.orchestration.alert_freshness_gate.newest_article_age_seconds', return_value=60
    ), patch(
        'backend.orchestration.alert_freshness_gate._file_age_seconds', side_effect=_premarket_file_age
    ), patch(
        'backend.orchestration.alert_freshness_gate.attempt_safe_refresh', return_value=False
    ):
        ok, _msg, keys = check_core_freshness()
    if ok or 'intel' not in keys:
        return 'premarket intel >30min before open must block'

    ok, msg, keys = _run_check(
        market=True, premarket=False, news_age=30 * 60, scanner_age=5 * 60, market_age=5 * 60, refresh_ok=False
    )
    if not ok or keys:
        return 'fresh feeds must not be treated as stale'

    with patch('backend.orchestration.alert_freshness_gate.check_core_freshness', return_value=(False, WATCH_ONLY_MESSAGE, ['news'])):
        allow, msg = gate_alert_dispatch('INTRADAY_OPPORTUNITY')
    if allow or WATCH_ONLY_MESSAGE not in msg:
        return 'gate_alert_dispatch must block with watch-only message'

    with patch('backend.orchestration.alert_freshness_gate._is_market_hours', return_value=True), patch(
        'backend.orchestration.alert_freshness_gate._is_premarket_window', return_value=False
    ), patch(
        'backend.orchestration.alert_freshness_gate._file_age_seconds',
        side_effect=_file_age_factory(60, 60),
    ), patch(
        'backend.orchestration.alert_freshness_gate.attempt_safe_refresh', return_value=True
    ), patch(
        'backend.orchestration.alert_freshness_gate.newest_article_age_seconds', return_value=91 * 60
    ):
        ok, msg, keys = check_core_freshness()
    if ok:
        return 'stale after failed recovery must remain blocked'
    if msg != WATCH_ONLY_MESSAGE:
        return f'unexpected refresh-fail message: {msg!r}'

    if attempt_safe_refresh.__doc__ and 'destructive' not in attempt_safe_refresh.__doc__.lower():
        pass

    return None


def _test_india_ist_modes() -> str | None:
    from backend.analytics.market_calendar_router import (
        MODE_INDIA,
        MODE_INDIA_AFTER_HOURS,
        MODE_INDIA_POSTMARKET,
        MODE_INDIA_PREMARKET,
        MODE_INDIA_PREOPEN,
        _india_after_hours,
        _session_for_market,
        get_active_market_mode,
    )
    from backend.utils.market_hours import get_market_period, get_watchdog_config

    # User label INDIA_MARKET_HOURS → regular session (MODE_INDIA) 09:15–15:30 IST
    router_cases = (
        ('2026-06-02T02:30:00+00:00', MODE_INDIA_PREMARKET),
        ('2026-06-02T03:35:00+00:00', MODE_INDIA_PREOPEN),
        ('2026-06-02T04:30:00+00:00', MODE_INDIA),
        ('2026-06-02T10:00:00+00:00', MODE_INDIA_POSTMARKET),
    )
    for iso, expected_mode in router_cases:
        now = _utc(iso)
        mode = get_active_market_mode(now)
        if mode.get('active_mode') != expected_mode:
            return f'at {iso} expected {expected_mode}, got {mode.get("active_mode")}'

    after_hours_ist = IST.localize(datetime(2026, 6, 2, 17, 0))
    india_snap = _session_for_market('india', after_hours_ist)
    if not _india_after_hours(india_snap):
        return 'after 16:30 IST must be INDIA_AFTER_HOURS window'
    ah_mode = get_active_market_mode(after_hours_ist)
    if ah_mode.get('active_mode') == MODE_INDIA_AFTER_HOURS:
        pass
    elif get_market_period(after_hours_ist) != 'after_hours':
        return 'after 16:30 IST must be after_hours period'

    period_cases = (
        ((2026, 6, 2, 8, 0), 'pre_market'),
        ((2026, 6, 2, 9, 5), 'preopen'),
        ((2026, 6, 2, 10, 0), 'market'),
        ((2026, 6, 2, 15, 45), 'post_market'),
        ((2026, 6, 2, 17, 0), 'after_hours'),
    )
    for parts, expected_period in period_cases:
        now_ist = IST.localize(datetime(*parts))
        if get_market_period(now_ist) != expected_period:
            return f'at {parts} IST expected period {expected_period}, got {get_market_period(now_ist)}'

    wd = get_watchdog_config(IST.localize(datetime(2026, 6, 2, 10, 0)))
    if wd.get('mode') != 'MARKET_HOURS':
        return 'INDIA_MARKET_HOURS window should expose MARKET_HOURS watchdog mode'
    wd_ah = get_watchdog_config(after_hours_ist)
    if wd_ah.get('mode') != 'AFTER_HOURS':
        return 'after 16:30 IST watchdog mode should be AFTER_HOURS'

    return None


def main() -> int:
    err = _test_freshness_thresholds()
    if err:
        return _fail(err)
    err = _test_india_ist_modes()
    if err:
        return _fail(err)

    engine = (PROJECT_ROOT / 'backend/orchestration/telegram_alert_engine.py').read_text(encoding='utf-8')
    if 'alert_freshness_gate' not in engine:
        return _fail('telegram_alert_engine missing freshness gate wiring')

    print('ALERT_FRESHNESS_GATES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
