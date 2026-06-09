#!/usr/bin/env python3
"""Unit tests for broker Telegram commands (Stage 48L)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'BROKER_TELEGRAM_COMMANDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _text(cmd: str) -> str:
    from backend.telegram.response_format import strip_stage_markers
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    results = handle_analysis_command(cmd, 'test_user', dry_run=True)
    if not results:
        return ''
    return strip_stage_markers(str(results[0].get('text') or ''))


def main() -> int:
    from unittest.mock import patch

    from backend.analytics.broker_intelligence import format_broker_ticker_telegram, handle_broker_command

    overview = handle_broker_command('')
    for needle in ('Broker Intelligence', 'Freshness', 'Research only'):
        if needle not in overview:
            return _fail(f'overview missing {needle!r}')

    with patch('backend.analytics.broker_intelligence.get_broker_intel_ticker', return_value={
        'ok': True,
        'cache_missing': False,
        'found': True,
        'watchlist_only': True,
        'has_broker_consensus': False,
        'ticker': 'BHARTIARTL',
        'market_mentions': [{
            'source': 'LiveMint',
            'headline': 'Stocks to watch: Bharti Airtel',
        }],
    }):
        bharti = format_broker_ticker_telegram('BHARTIARTL')
    if 'not a broker rating' not in bharti.lower():
        return _fail('BHARTIARTL watchlist drilldown must say not a broker rating')

    with patch('backend.telegram.lazy_command_runner._scoped_refresh', return_value={'ok': True}):
        for cmd in ('/broker', 'broker', '/broker RELIANCE', 'broker RELIANCE', '/broker refresh', 'broker refresh'):
            text = _text(cmd)
            if 'Unknown command' in text:
                return _fail(f'{cmd} returned unknown command')
            if 'Broker' not in text:
                return _fail(f'{cmd} missing broker header')

    if 'buy now' in overview.lower() or 'guaranteed' in overview.lower():
        return _fail('forbidden language in overview')

    print('BROKER_TELEGRAM_COMMANDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
