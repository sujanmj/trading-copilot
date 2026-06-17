#!/usr/bin/env python3
"""Stage 50V — freshness line appears in /tradecard and /tradecard explain."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_FRESHNESS_LINE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.tradecard_refresh import format_freshness_line

    meta = {
        'quote_refreshed_now': True,
        'scanner_age_seconds': 12,
        'scanner_refreshed_now': False,
        'refresh_failed': False,
        'cooldown_reused': False,
    }
    line = format_freshness_line(meta)
    if not line.startswith('Freshness:'):
        return _fail(f'format_freshness_line must start with Freshness: got {line!r}')
    if 'quote refreshed now' not in line or 'scanner 12s old' not in line:
        return _fail(f'unexpected freshness formatting: {line!r}')

    fake_card = {
        'ok': True,
        'session_date': '2099-01-01',
        'ticker': 'KPIL',
        'levels_source_ticker': 'KPIL',
        'status': 'NO_ACTIVE_ENTRY',
        'entry_zone': 'NO ACTIVE ENTRY',
        'reason': 'extended move',
        'paper_only': True,
    }

    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'NO_ACTIVE_ENTRY')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        plain = format_tradecard_telegram(explain=False, freshness_meta=meta)
        explain = format_tradecard_telegram(explain=True, freshness_meta=meta)

    for label, text in (('plain', plain), ('explain', explain)):
        if 'Freshness:' not in text:
            return _fail(f'{label} /tradecard must include Freshness line')
        if 'quote refreshed now' not in text:
            return _fail(f'{label} must show quote refreshed now')
        if 'Explain' not in text and label == 'explain':
            return _fail('explain variant must include Explain block')

    from backend.telegram.lazy_command_runner import run_tradecard_only

    with patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value=meta), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('KPIL', 'NO_ACTIVE_ENTRY')), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        runner = run_tradecard_only('explain', chat_id='freshness-line')

    if 'Freshness:' not in (runner.get('text') or ''):
        return _fail('run_tradecard_only explain must include freshness line')

    print('TRADECARD_FRESHNESS_LINE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
