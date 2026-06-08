#!/usr/bin/env python3
"""Unit tests for Telegram India mode lock (Stage 48K)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_INDIA_MODE_LOCK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.india_mode_lock import (
        explicit_usa_mode_configured,
        resolve_telegram_market_mode,
    )

    locked = resolve_telegram_market_mode(
        payload_mode='USA_MODE',
        router_mode='USA_MODE',
        active_mode='USA_MODE',
    )
    if locked == 'USA_MODE':
        return _fail('USA_MODE must not appear without explicit config')

    if locked not in ('INDIA_MODE', 'RESEARCH_MODE'):
        return _fail(f'unexpected locked mode: {locked}')

    with patch.dict(os.environ, {'TELEGRAM_ALLOW_USA_MODE': '1'}, clear=False):
        if not explicit_usa_mode_configured():
            return _fail('explicit USA config should be detected')
        allowed = resolve_telegram_market_mode(payload_mode='USA_MODE')
        if allowed != 'USA_MODE':
            return _fail('USA_MODE allowed only with explicit config')

    weekend_info = {'mode_code': 'RESEARCH_MODE', 'market_mode': 'Weekend — Research'}
    with patch(
        'backend.telegram.india_mode_lock.get_india_telegram_mode',
        return_value=weekend_info,
    ):
        with patch(
            'backend.telegram.india_mode_lock.is_weekend_holiday_research_telegram_mode',
            return_value=True,
        ):
            research = resolve_telegram_market_mode(payload_mode='USA_MODE')
    if research != 'RESEARCH_MODE':
        return _fail(f'weekend must force RESEARCH_MODE, got {research}')

    print('TELEGRAM_INDIA_MODE_LOCK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
