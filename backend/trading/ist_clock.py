"""
Runtime IST clock snapshot — Phase 4B.11.

Always uses datetime.now(ZoneInfo('Asia/Kolkata')) for display clocks.
Never uses board generated_at or cache timestamps as "current IST".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.11'
TIMEZONE_SOURCE = 'Asia/Kolkata'
CLOCK_SOURCE = 'runtime'


def runtime_ist_now() -> datetime:
    """Actual runtime IST — not board/cache timestamps."""
    return datetime.now(IST)


def runtime_clock_snapshot(*, now: datetime | None = None) -> dict[str, Any]:
    """Clock + market calendar snapshot for /clock, /health, /status."""
    from backend.trading.opening_session_freshness import (
        current_ist_session_date,
        is_hard_closed_market_lifecycle,
        is_india_market_day,
        resolve_market_lifecycle,
        resolve_market_state,
    )

    ist = now.astimezone(IST) if now is not None and now.tzinfo else (
        now.replace(tzinfo=IST) if now is not None else runtime_ist_now()
    )
    utc = ist.astimezone(timezone.utc)
    lifecycle = resolve_market_lifecycle(ist)
    trading_day = ist.date()
    return {
        'stage': STAGE,
        'server_utc': utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
        'current_ist': ist.strftime('%Y-%m-%d %H:%M IST'),
        'current_ist_date': current_ist_session_date(ist),
        'timezone_source': TIMEZONE_SOURCE,
        'clock_source': CLOCK_SOURCE,
        'market_lifecycle': lifecycle,
        'market_state': resolve_market_state(ist),
        'trading_date': trading_day.isoformat(),
        'india_market_day': is_india_market_day(trading_day),
        'weekend_or_holiday': lifecycle in ('WEEKEND', 'HOLIDAY'),
        'closed_market_reference': is_hard_closed_market_lifecycle(ist),
    }


def format_clock_status_lines(*, now: datetime | None = None) -> list[str]:
    snap = runtime_clock_snapshot(now=now)
    return [
        f"Server UTC: {snap['server_utc']}",
        f"Current IST: {snap['current_ist']}",
        f'Timezone source: {snap["timezone_source"]}',
        f'Clock source: {snap["clock_source"]}',
    ]


def format_clock_telegram(*, now: datetime | None = None) -> str:
    snap = runtime_clock_snapshot(now=now)
    closed = 'yes' if snap.get('closed_market_reference') else 'no'
    market_day = 'yes' if snap.get('india_market_day') else 'no'
    weekend = 'yes' if snap.get('weekend_or_holiday') else 'no'
    lines = [
        '<b>🕐 Clock</b>',
        '<i>Runtime clock — not board/cache timestamps</i>',
        '',
        f"Server UTC: <code>{snap['server_utc']}</code>",
        f"Current IST: <code>{snap['current_ist']}</code>",
        f"Market lifecycle: <code>{snap['market_lifecycle']}</code>",
        f"Trading date: <code>{snap['trading_date']}</code>",
        f'India market day: <code>{market_day}</code>',
        f'Weekend/holiday: <code>{weekend}</code>',
        f'Closed-market reference mode: <code>{closed}</code>',
        f'Timezone source: <code>{snap["timezone_source"]}</code>',
        f'Clock source: <code>{snap["clock_source"]}</code>',
    ]
    return '\n'.join(lines)
