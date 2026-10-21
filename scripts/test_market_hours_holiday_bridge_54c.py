#!/usr/bin/env python3
"""Regression: canonical runtime lifecycle respects the India holiday calendar."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from unittest.mock import patch

import pytz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from backend.lifecycle.canonical_lifecycle import HOLIDAY, MARKET_ACTIVE, resolve_base_lifecycle
    from backend.utils.market_hours import (
        get_collection_profile,
        get_market_period,
        get_operational_status,
        is_market_holiday,
    )

    ist = pytz.timezone('Asia/Kolkata')
    holiday = ist.localize(datetime(2026, 10, 20, 10, 0))
    trading_day = ist.localize(datetime(2026, 10, 21, 10, 0))

    def is_trading_day(day):
        return day.isoformat() != '2026-10-20'

    with patch('backend.analytics.market_calendar_router.is_india_market_day', side_effect=is_trading_day):
        if not is_market_holiday(holiday):
            raise AssertionError('configured weekday holiday was not recognized')
        if resolve_base_lifecycle(holiday) != HOLIDAY:
            raise AssertionError('canonical lifecycle must report HOLIDAY')
        if get_market_period(holiday) != 'weekend':
            raise AssertionError('holiday must use the closed-market scheduling profile')
        status = get_operational_status(holiday)
        if status.get('market_hours') or status.get('collectors_active'):
            raise AssertionError('holiday must not report live market hours or active collectors')
        profile = get_collection_profile(holiday)
        if profile.get('run_scanner') or profile.get('run_india_collector'):
            raise AssertionError('holiday profile must not schedule India market collectors')
        if resolve_base_lifecycle(trading_day) != MARKET_ACTIVE:
            raise AssertionError('normal weekday market lifecycle changed')

    print('MARKET_HOURS_HOLIDAY_BRIDGE_54C_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
