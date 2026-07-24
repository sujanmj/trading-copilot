#!/usr/bin/env python3
"""Stage 50Z hotfix - /tradecard explain explains latest audit-only card."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_journal, isolated_tradecard_latest


def _fail(msg: str) -> int:
    print(f'TRADECARD_EXPLAIN_LATEST_NO_ACTIVE_ENTRY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.telegram.response_format import user_text_has_naked_buy_sell
    from backend.trading.tradecard_journal import summarize_today_outcomes
    from backend.trading.tradecard_latest import load_latest_tradecard

    card = {
        'ok': True,
        'ticker': 'SCHAEFFLER',
        'levels_source_ticker': 'SCHAEFFLER',
        'status': 'NEXT_SESSION_WATCH',
        'entry_zone': 'NO ACTIVE ENTRY',
        'reason': 'market closed/after-hours',
        'after_hours': True,
        'source_label': 'Source: scanner-confirmed',
        'paper_only': True,
    }
    meta = {
        'quote_refreshed_now': True,
        'scanner_refreshed_now': True,
        'refresh_failed': False,
    }
    chat_id = 'latest-no-active-entry'

    from scripts._test_runtime_isolation import synced_tradecard_stub

    sync = synced_tradecard_stub('SCHAEFFLER', state='NO_ACTIVE_ENTRY', status_override='NO_ACTIVE_ENTRY')
    with isolated_tradecard_latest(), isolated_tradecard_journal():
        with patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value=meta), \
             patch('backend.trading.trade_card_engine.get_trade_card', return_value=card), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
             patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('SCHAEFFLER', 'NO_ACTIVE_ENTRY')), \
             patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''), \
             patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync):
            plain = run_tradecard_only('', chat_id=chat_id)

        plain_text = plain.get('text') or ''
        if 'SCHAEFFLER' not in plain_text or 'NO ACTIVE ENTRY' not in plain_text:
            return _fail('/tradecard must show SCHAEFFLER no-active card')

        latest = load_latest_tradecard(chat_id)
        if not latest or latest.get('ticker') != 'SCHAEFFLER':
            return _fail('latest audit card was not stored for chat')
        if latest.get('record_type') != 'latest_tradecard_audit' or latest.get('audit_only') is not True:
            return _fail('latest no-active card must be audit-only')

        counts = summarize_today_outcomes().get('counts') or {}
        if int(counts.get('generated') or 0) != 0:
            return _fail('audit-only card must not count as generated active tradecard')

        with patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value=meta), \
             patch('backend.trading.trade_card_engine.get_trade_card', return_value={**card, 'ticker': 'OTHER'}), \
             patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
             patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
             patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync):
            explain = run_tradecard_only('explain', chat_id=chat_id)

    text = explain.get('text') or ''
    required = (
        'TRADE CARD',
        'SCHAEFFLER',
        'NO ACTIVE ENTRY',
        'Explain',
        'Entry logic: no active entry generated',
        'Risk logic: wait for next session confirmation after 09:20',
        'Next action: watch only; no paper entry until fresh market-hours confirmation',
        'Source: scanner-confirmed',
        'Paper only.',
    )
    for needle in required:
        if needle not in text:
            return _fail(f'/tradecard explain missing {needle!r}')
    if 'No active/latest tradecard found' in text:
        return _fail('/tradecard explain must not report missing latest audit')
    if 'OTHER' in text:
        return _fail('/tradecard explain must use latest audit ticker, not reselect')
    if user_text_has_naked_buy_sell(text):
        return _fail('/tradecard explain contains forbidden action wording')

    print('TRADECARD_EXPLAIN_LATEST_NO_ACTIVE_ENTRY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
