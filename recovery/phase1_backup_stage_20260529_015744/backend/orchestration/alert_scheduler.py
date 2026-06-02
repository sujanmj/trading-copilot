"""
Alert scheduler — IST time windows, night mode, low-power after hours.

Called every minute from master_scheduler.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import pytz

from backend.orchestration import telegram_alert_engine as engine
from backend.orchestration.alert_filters import get_telegram_alert_obs_summary

IST = pytz.timezone('Asia/Kolkata')

# Track last run slots to avoid duplicate triggers within same minute window
_last_slot: dict = {}


def _now_ist() -> datetime:
    return datetime.now(IST)


def _t(hour: int, minute: int = 0) -> time:
    return time(hour, minute)


def _in_range(now: datetime, start: time, end: time) -> bool:
    t = now.time()
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def is_night_mode(now: Optional[datetime] = None) -> bool:
    """11 PM – 6 AM IST: no normal alerts."""
    now = now or _now_ist()
    return _in_range(now, _t(23, 0), _t(6, 0))


def is_after_hours(now: Optional[datetime] = None) -> bool:
    """After 5 PM IST — low power."""
    now = now or _now_ist()
    return now.time() >= _t(17, 0) and not is_night_mode(now)


def is_weekday(now: Optional[datetime] = None) -> bool:
    now = now or _now_ist()
    return now.weekday() < 5


def _once_per_slot(key: str, now: datetime, minute_granularity: int = 1) -> bool:
    slot = f"{key}_{now.strftime('%Y-%m-%d_%H')}_{now.minute // minute_granularity}"
    if _last_slot.get(key) == slot:
        return False
    _last_slot[key] = slot
    return True


def tick() -> dict:
    """Main scheduler tick — returns summary of actions."""
    now = _now_ist()
    result = {'time': now.isoformat(), 'sent': 0, 'mode': 'market', 'actions': []}

    if not is_weekday(now):
        result['mode'] = 'weekend'
        if is_night_mode(now) and _once_per_slot('emergency_weekend', now, 15):
            n = engine.try_emergency_macro()
            result['sent'] += n
            if n:
                result['actions'].append('emergency')
        return result

    if is_night_mode(now):
        result['mode'] = 'night'
        if _once_per_slot('emergency_night', now, 10):
            n = engine.try_emergency_macro()
            result['sent'] += n
            if n:
                result['actions'].append('emergency')
        return result

    if is_after_hours(now):
        result['mode'] = 'after_hours'
        if _once_per_slot('emergency_ah', now, 15):
            n = engine.try_emergency_macro()
            result['sent'] += n
            if n:
                result['actions'].append('emergency')
        return result

    # ── Pre-market 8:00–8:45 (once ~8:20) ──
    if _in_range(now, _t(8, 0), _t(8, 45)) and now.minute in (15, 20, 25):
        if _once_per_slot('pre_market', now, 5):
            n = engine.try_pre_market()
            result['sent'] += n
            result['actions'].append(f'pre_market:{n}')

    # ── Outcome 8:00 ──
    if now.hour == 8 and now.minute == 5 and _once_per_slot('outcome', now, 60):
        n = engine.run_outcome_report()
        result['sent'] += n
        result['actions'].append(f'outcome:{n}')

    # ── Open opportunity 9:20–9:45 every 5 min ──
    if _in_range(now, _t(9, 20), _t(9, 45)) and now.minute % 5 == 0:
        if _once_per_slot('open_opp', now, 5):
            n = engine.try_open_opportunity()
            result['sent'] += n
            if n:
                result['actions'].append(f'open:{n}')

    # ── Intraday events 10:00–14:30 every 10 min ──
    if _in_range(now, _t(10, 0), _t(14, 30)) and now.minute % 10 == 0:
        if _once_per_slot('intraday', now, 10):
            n = engine.try_intraday_events()
            result['sent'] += n
            if n:
                result['actions'].append(f'intraday:{n}')

    # ── Midday 13:00 ──
    if now.hour == 13 and now.minute == 0 and _once_per_slot('midday', now, 60):
        n = engine.try_midday_update()
        result['sent'] += n
        result['actions'].append(f'midday:{n}')

    # ── Close summary 15:45–16:15 (once ~15:50) ──
    if _in_range(now, _t(15, 45), _t(16, 15)) and now.minute in (50, 55):
        if _once_per_slot('close', now, 5):
            n = engine.try_close_summary()
            result['sent'] += n
            result['actions'].append(f'close:{n}')

    # ── Emergency anytime in market hours (15 min cadence) ──
    if _once_per_slot('emergency', now, 15):
        n = engine.try_emergency_macro()
        result['sent'] += n
        if n:
            result['actions'].append('emergency')

    return result


def get_scheduler_status() -> dict:
    now = _now_ist()
    return {
        'ist_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'night_mode': is_night_mode(now),
        'after_hours': is_after_hours(now),
        'weekday': is_weekday(now),
        'telegram_alerts': get_telegram_alert_obs_summary(),
    }
