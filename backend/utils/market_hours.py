"""IST market-hours helpers — watchdog stale tolerance and mode detection."""

from __future__ import annotations

from datetime import datetime, time
from typing import Dict, Optional, Tuple

import pytz

IST = pytz.timezone('Asia/Kolkata')

# IST session boundaries — canonical lifecycle authority
_MARKET_OPEN = time(9, 15)
_MARKET_ACTIVE_END = time(15, 29)
_POST_MARKET_START = time(15, 30)
_POST_MARKET_END = time(16, 30)
_AFTER_HOURS_START = time(16, 30)
_PRE_MARKET_START = time(7, 45)
_PREOPEN_START = time(9, 0)
_PREOPEN_END = time(9, 15)
_NIGHT_START = time(23, 0)
_EARLY_MORNING = time(6, 0)

# Stale thresholds (seconds) — tuned for ops stability
WATCHDOG_STALE_MARKET = int(__import__('os').environ.get('WATCHDOG_STALE_MARKET', '2700'))       # 45 min
WATCHDOG_STALE_AFTER_HOURS = int(__import__('os').environ.get('WATCHDOG_STALE_AFTER_HOURS', '9000'))  # 2.5 hr
WATCHDOG_STALE_NIGHT = int(__import__('os').environ.get('WATCHDOG_STALE_NIGHT', '18000'))      # 5 hr
WATCHDOG_STALE_PRE_MARKET = int(__import__('os').environ.get('WATCHDOG_STALE_PRE_MARKET', '3600'))  # 1 hr


def _now_ist(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(IST)


def is_market_holiday(now: Optional[datetime] = None) -> bool:
    """Optional holiday calendar hook — extend when holiday data is available."""
    _ = _now_ist(now)
    return False


def get_market_period(now: Optional[datetime] = None) -> str:
    """Return: market | preopen | pre_market | post_market | after_hours | night | weekend."""
    now = _now_ist(now)
    if is_market_holiday(now):
        return 'weekend'
    if now.weekday() >= 5:
        return 'weekend'
    t = now.time()
    if t >= _NIGHT_START or t < _EARLY_MORNING:
        return 'night'
    if _MARKET_OPEN <= t <= _MARKET_ACTIVE_END:
        return 'market'
    if _POST_MARKET_START <= t < _POST_MARKET_END:
        return 'post_market'
    if t >= _AFTER_HOURS_START and t < _NIGHT_START:
        return 'after_hours'
    if _PREOPEN_START <= t < _PREOPEN_END:
        return 'preopen'
    if _PRE_MARKET_START <= t < _PREOPEN_START:
        return 'pre_market'
    return 'night'


def get_watchdog_config(now: Optional[datetime] = None) -> Dict[str, object]:
    """Dynamic stale threshold + mode label for watchdog and health API."""
    period = get_market_period(now)
    thresholds = {
        'market': WATCHDOG_STALE_MARKET,
        'preopen': WATCHDOG_STALE_PRE_MARKET,
        'pre_market': WATCHDOG_STALE_PRE_MARKET,
        'post_market': WATCHDOG_STALE_AFTER_HOURS,
        'after_hours': WATCHDOG_STALE_AFTER_HOURS,
        'night': WATCHDOG_STALE_NIGHT,
        'weekend': WATCHDOG_STALE_NIGHT,
    }
    mode_labels = {
        'market': 'MARKET_HOURS',
        'preopen': 'PREOPEN',
        'pre_market': 'INDIA_PREMARKET_MODE',
        'post_market': 'POSTMARKET',
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
    """Collector scheduling profile — night allows global/macro ingestion."""
    period = get_market_period(now)
    return {
        'period': period,
        'lightweight_only': period in ('night', 'weekend'),
        'run_india_collector': period not in ('weekend',),
        'run_parallel_ingestion': period in ('market', 'pre_market', 'post_market', 'after_hours'),
        'run_global_overnight': period in ('night', 'pre_market'),
        'run_scanner': period in ('market', 'pre_market'),
        'run_analyzer': period in ('market', 'pre_market', 'post_market', 'after_hours', 'night'),
        'skip_heavy_overnight': period in ('weekend',),
    }


def get_lifecycle_state(now: Optional[datetime] = None) -> str:
    """Redirect to canonical lifecycle — sole authority."""
    from backend.lifecycle.canonical_lifecycle import resolve_base_lifecycle
    return resolve_base_lifecycle(now)


def get_operational_status(now: Optional[datetime] = None) -> Dict[str, object]:
    """Human-facing operational mode for GUI, OPS, and Telegram status."""
    period = get_market_period(now)
    wd = get_watchdog_config(now)
    lifecycle_state = get_lifecycle_state(now)
    labels = {
        'market': ('market_active', 'MARKET ACTIVE', 'Live session — collectors active'),
        'pre_market': (
            'premarket_prep',
            'PRE-MARKET ANALYSIS',
            'Pre-market prep — scanner, news, and sector synthesis active',
        ),
        'preopen': (
            'preopen_watch',
            'PRE-OPEN',
            'Pre-open auction — confirm setups only after 9:15',
        ),
        'post_market': (
            'postmarket_eval',
            'POST-MARKET EVAL',
            'Post-close evaluation and lifecycle resolution',
        ),
        'after_hours': (
            'after_hours_intel',
            'AFTER-HOURS INTEL',
            'After-hours intelligence mode active',
        ),
        'night': ('night_intel', 'OVERNIGHT GLOBAL INTEL', 'After-hours intelligence mode active'),
        'weekend': ('weekend_idle', 'WEEKEND', 'Market closed — awaiting Monday open'),
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
        'lifecycle_state': lifecycle_state,
        'display_status': display_status,
        'display_message': display_message,
        'period': period,
        'market_hours': period == 'market',
        'night_mode': period in ('night', 'weekend'),
        'watchdog_mode': wd.get('mode'),
        'stale_threshold_seconds': wd.get('stale_threshold_seconds'),
        'expect_quiet_collectors': period in ('weekend',),
        'collectors_active': period in ('market', 'pre_market', 'post_market', 'after_hours', 'night'),
        'canonical_lifecycle': get_lifecycle_state(now),
        'after_hours_mode': period in ('post_market', 'after_hours', 'night'),
        'orchestrator_mode': orchestrator_mode,
    }


def source_idle_message(source_key: str, period: str) -> str:
    """Calm overnight copy instead of stale warnings."""
    if period == 'weekend':
        return 'Market closed — collectors idle until Monday open'
    if period == 'night':
        return 'Market closed — awaiting market open'
    if period == 'pre_market':
        return 'Pre-market analysis — scanner and macro prep active'
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
