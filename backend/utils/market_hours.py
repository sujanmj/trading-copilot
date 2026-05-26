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


def get_operational_status(now: Optional[datetime] = None) -> Dict[str, object]:
    """Human-facing operational mode for GUI, OPS, and Telegram status."""
    period = get_market_period(now)
    wd = get_watchdog_config(now)
    labels = {
        'market': ('healthy_active', 'HEALTHY ACTIVE', 'Live session — collectors active'),
        'pre_market': ('waiting_market_open', 'WAITING MARKET OPEN', 'Pre-market — awaiting 9:00 IST open'),
        'after_hours': ('idle_after_hours', 'IDLE (after hours)', 'Post-close — light collection mode'),
        'night': ('idle_night', 'IDLE (night mode)', 'Market closed — awaiting market open'),
        'weekend': ('idle_weekend', 'IDLE (weekend)', 'Market closed — awaiting Monday open'),
    }
    mode_key, display_status, display_message = labels.get(
        period, ('unknown', period.upper(), 'Operational status unknown')
    )
    orchestrator_mode = None
    try:
        from backend.orchestration.orchestrator_state import load_orchestrator_state, MODE_RECOVERING
        orchestrator_mode = load_orchestrator_state().get('orchestrator_mode')
        if orchestrator_mode == MODE_RECOVERING and period == 'market':
            mode_key = 'recovering'
            display_status = 'RECOVERING'
            display_message = 'Controlled recovery in progress — single attempt per cooldown'
    except Exception:
        pass
    return {
        'operational_mode': mode_key,
        'display_status': display_status,
        'display_message': display_message,
        'period': period,
        'market_hours': period == 'market',
        'night_mode': period in ('night', 'weekend'),
        'watchdog_mode': wd.get('mode'),
        'stale_threshold_seconds': wd.get('stale_threshold_seconds'),
        'expect_quiet_collectors': period in ('night', 'weekend', 'after_hours', 'pre_market'),
        'orchestrator_mode': orchestrator_mode,
    }


def source_idle_message(source_key: str, period: str) -> str:
    """Calm overnight copy instead of stale warnings."""
    if period == 'weekend':
        return 'Market closed — collectors idle until Monday open'
    if period == 'night':
        return 'Market closed — awaiting market open'
    if period == 'pre_market':
        return 'Pre-market — awaiting session open'
    if period == 'after_hours':
        return 'After hours — light collection mode'
    if source_key in ('scanner', 'news', 'reddit', 'youtube', 'inshorts'):
        return 'Collectors quiet outside active session'
    return 'Awaiting next refresh cycle'


def classify_source_freshness(
    age_seconds: Optional[int],
    stale_threshold: int,
    period: str,
) -> Tuple[str, bool]:
    """
    Return (status, treat_as_unhealthy).
    status: ok | idle | stale | missing
    """
    if age_seconds is None:
        return 'missing', False
    if age_seconds <= stale_threshold:
        return 'ok', False
    if period in ('night', 'weekend', 'pre_market', 'after_hours'):
        return 'idle', False
    if period == 'market':
        return 'stale', True
    return 'idle', False
