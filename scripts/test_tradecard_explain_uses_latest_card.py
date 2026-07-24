#!/usr/bin/env python3
"""Stage 50Z addendum — /tradecard explain uses last card, not fresh selection."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_latest


def _fail(msg: str) -> int:
    print(f'TRADECARD_EXPLAIN_USES_LATEST_CARD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.trading.tradecard_latest import load_latest_tradecard

    amber = {
        'ok': True,
        'session_date': '2099-01-01',
        'ticker': 'AMBER',
        'levels_source_ticker': 'AMBER',
        'status': 'VALID_ENTRY',
        'current_price': 420.5,
        'entry_zone': '418–422',
        'stop_loss': 416,
        'target_1': 424,
        'target_2': 427,
        'risk_reward': 2.0,
        'capital_plan': 'Paper only',
        'reason': 'scanner aligned',
        'invalid_if': 'below 416',
        'exit_rule': 'trim T1',
        'confidence': 'MEDIUM',
        'paper_only': True,
        'generated_at': '2099-01-01T10:00:00+05:30',
    }
    bataindia = {
        **amber,
        'ticker': 'BATAINDIA',
        'levels_source_ticker': 'BATAINDIA',
        'current_price': 760.9,
        'entry_zone': '758–762',
        'stop_loss': 755,
        'target_1': 768,
        'target_2': 775,
        'reason': 'different top pick',
    }
    meta = {'quote_refreshed_now': True, 'scanner_refreshed_now': True, 'refresh_failed': False}
    chat_id = 'explain-latest-card'

    from scripts._test_runtime_isolation import synced_tradecard_stub

    amber_sync = synced_tradecard_stub('AMBER')
    with isolated_tradecard_latest():
        with patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value=meta), \
             patch('backend.trading.trade_card_engine.get_trade_card', return_value=amber), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('AMBER', 'VALID_ENTRY')), \
             patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
             patch('backend.trading.tradecard_journal.get_active_valid_entry', return_value=None), \
             patch('backend.trading.tradecard_journal.persist_tradecard_generation', return_value={'id': 'x'}), \
             patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=amber_sync):
            first = run_tradecard_only('', chat_id=chat_id)

        if 'AMBER' not in (first.get('text') or ''):
            return _fail('/tradecard must show AMBER first')
        latest = load_latest_tradecard(chat_id)
        if not latest or latest.get('ticker') != 'AMBER':
            return _fail('latest_tradecard must store AMBER after /tradecard')

        with patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value=meta), \
             patch('backend.trading.trade_card_engine.get_trade_card', return_value=bataindia), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('BATAINDIA', 'VALID_ENTRY')), \
             patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False):
            explain = run_tradecard_only('explain', chat_id=chat_id)

    text = explain.get('text') or ''
    if 'AMBER' not in text:
        return _fail('/tradecard explain must keep AMBER from latest card')
    if 'BATAINDIA' in text:
        return _fail('/tradecard explain must not re-select BATAINDIA')
    if 'Explain' not in text:
        return _fail('/tradecard explain must include Explain block')

    print('TRADECARD_EXPLAIN_USES_LATEST_CARD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
