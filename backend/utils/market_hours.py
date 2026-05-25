"""IST market-hours helpers — watchdog stale tolerance and mode detection."""

from __future__ import annotations

from datetime import datetime, time
from typing import Dict, Optional

import pytz

IST = pytz.timezone('Asia/Kolkata')

# Stale thresholds (seconds) — tuned for ops stability
WATCHDOG_STALE_MARKET = int(__import__('os').environ.get('WATCHDOG_STALE_MARKET', '2700'))       # 45 min
WATCHDOG_STALE_AFTER_HOURS = int(__import__('os').environ.get('WATCHDOG_STALE_AFTER_HOURS', '9000'))  # 2.5 hr
WATCHDOG_STALE_NIGHT = int(__import__('os').environ.get('WATCHDOG_STALE_NIGHT', '18000'))      # 5 hr
WATCHDOG_STALE_PRE_MARKET = int(__import__('os').environ.get('WATCHDOG_STALE_PRE_MARKET', '3600'))  # 1 hr


def _now_ist(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(IST)


def get_market_period(now: Optional[datetime] = None) -> str:
    """Return: market | pre_market | after_hours | night | weekend."""
    now = _now_ist(now)
    if now.weekday() >= 5:
        return 'weekend'
    t = now.time()
    if t >= time(23, 0) or t < time(6, 0):
        return 'night'
    if time(9, 0) <= t <= time(16, 0):
        return 'market'
    if t >= time(17, 0):
        return 'after_hours'
    if time(6, 0) <= t < time(9, 0):
        return 'pre_market'
    return 'after_hours'


def get_watchdog_config(now: Optional[datetime] = None) -> Dict[str, object]:
    """Dynamic stale threshold + mode label for watchdog and health API."""
    period = get_market_period(now)
    thresholds = {
        'market': WATCHDOG_STALE_MARKET,
        'pre_market': WATCHDOG_STALE_PRE_MARKET,
        'after_hours': WATCHDOG_STALE_AFTER_HOURS,
        'night': WATCHDOG_STALE_NIGHT,
        'weekend': WATCHDOG_STALE_NIGHT,
    }
    mode_labels = {
        'market': 'MARKET_HOURS',
        'pre_market': 'PRE_MARKET',
        'after_hours': 'AFTER_HOURS',
        'night': 'NIGHT',
        'weekend': 'WEEKEND',
    }
    return {
        'mode': mode_labels.get(period, period.upper()),
        'period': period,
        'stale_threshold_seconds': thresholds.get(period, WATCHDOG_STALE_AFTER_HOURS),
        'night_mode': period in ('night', 'weekend'),
        'market_hours': period == 'market',
    }


def get_collection_profile(now: Optional[datetime] = None) -> Dict[str, object]:
    """Collector scheduling profile — reduce overnight noise."""
    period = get_market_period(now)
    return {
        'period': period,
        'lightweight_only': period in ('night', 'weekend'),
        'run_india_collector': True,
        'run_parallel_ingestion': period in ('market', 'pre_market', 'after_hours'),
        'run_scanner': period in ('market', 'pre_market'),
        'run_analyzer': period in ('market', 'pre_market', 'after_hours'),
        'skip_heavy_overnight': period in ('night', 'weekend'),
    }
