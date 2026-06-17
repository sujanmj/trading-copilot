#!/usr/bin/env python3
"""Stage 50V — refresh failure + stale cache yields DATA STALE / NO ACTIVE ENTRY."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VALID_ENTRY = re.compile(r'\bVALID_ENTRY\b|·\s*<code>VALID_ENTRY</code>')


def _fail(msg: str) -> int:
    print(f'TRADECARD_REFRESH_FAILURE_SAFE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    os.environ['TRADECARD_MAX_CACHE_AGE_SECONDS'] = '60'

    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.tradecard_refresh import is_tradecard_data_stale

    stale_meta = {
        'quote_age_seconds': 180,
        'scanner_age_seconds': 200,
        'quote_refreshed_now': False,
        'scanner_refreshed_now': False,
        'refresh_failed': True,
        'cooldown_reused': False,
        'data_stale': True,
    }

    if not is_tradecard_data_stale(stale_meta):
        return _fail('is_tradecard_data_stale must be true when refresh failed and cache > max age')

    fake_card = {
        'ok': True,
        'session_date': '2099-01-01',
        'ticker': 'KPIL',
        'levels_source_ticker': 'KPIL',
        'status': 'VALID_ENTRY',
        'current_price': 500.0,
        'entry_zone': '498–502',
        'stop_loss': 494.0,
        'target_1': 505.0,
        'target_2': 508.0,
        'risk_reward': 2.0,
        'volume_ratio': 1.5,
        'reason': 'Price/volume/structure align for paper watch entry',
        'paper_only': True,
    }

    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'VALID_ENTRY')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        text = format_tradecard_telegram(explain=False, freshness_meta=stale_meta)

    if 'DATA STALE' not in text:
        return _fail('/tradecard must show DATA STALE header on stale refresh failure')
    if 'NO ACTIVE ENTRY' not in text:
        return _fail('/tradecard must show NO ACTIVE ENTRY on stale refresh failure')
    if VALID_ENTRY.search(text):
        return _fail('stale refresh failure must not expose VALID_ENTRY')

    def _fail_scoped(scope: str, *, dry_run: bool = False):
        return {'ok': False, 'scope': scope, scope: 'failed', 'prices': 'failed', 'scanner': 'failed'}

    from backend.trading.tradecard_refresh import reset_tradecard_cooldown_state, refresh_tradecard_market_data

    reset_tradecard_cooldown_state()
    with patch('backend.trading.tradecard_refresh.is_live_market_hours_phase', return_value=True), \
         patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_fail_scoped), \
         patch('backend.trading.tradecard_refresh._file_age_seconds', return_value=120), \
         patch('backend.trading.tradecard_refresh._rebuild_unified_and_card'):
        meta = refresh_tradecard_market_data('stale-fail-chat', force=True)

    if not meta.get('refresh_failed'):
        return _fail('refresh must report failure when scoped refresh fails')
    if not meta.get('data_stale'):
        return _fail('refresh must mark data_stale when cache exceeds max age')

    from backend.telegram.lazy_command_runner import run_tradecard_only

    with patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value=meta), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'VALID_ENTRY')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        result = run_tradecard_only('fresh', chat_id='stale-fail-chat')

    runner_text = result.get('text') or ''
    if 'DATA STALE' not in runner_text or VALID_ENTRY.search(runner_text):
        return _fail('run_tradecard_only must block VALID_ENTRY on stale refresh failure')

    print('TRADECARD_REFRESH_FAILURE_SAFE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
