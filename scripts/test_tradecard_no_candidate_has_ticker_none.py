#!/usr/bin/env python3
"""Stage 50Q — /tradecard with no candidate must show Ticker: NONE."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_NO_CANDIDATE_HAS_TICKER_NONE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _has_ticker_contract(text: str) -> bool:
    if 'Ticker: NONE' in text:
        return True
    if re.search(r'\bTop reviewed:\s*<b>[A-Z][A-Z0-9]{1,14}</b>', text):
        return True
    if re.search(r'<b>[A-Z][A-Z0-9]{1,14}</b>\s*·', text):
        return True
    return False


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    empty_card = {
        'ok': False,
        'ticker': '—',
        'status': 'NO_TRADE',
        'reason': 'No scanner candidate available for trade card.',
        'paper_only': True,
        'session_date': '2026-06-16',
        'generated_at': '2026-06-16T18:00:00+05:30',
    }

    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=empty_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_reviewed_fallback', return_value=('', '')), \
         patch('scripts.refresh_local_intelligence.run_refresh_scoped', return_value={'ok': True}):
        text = format_tradecard_telegram(explain=False)
        explain = format_tradecard_telegram(explain=True)
        today_result = run_tradecard_only('today')
        explain_result = run_tradecard_only('explain')
        for cmd in ('/tradecard', '/tradecard today', '/tradecard explain'):
            bot = handle_analysis_command(cmd, 'none_test', dry_run=True)
            if not bot:
                return _fail(f'no bot response for {cmd}')
            body = str(bot[0].get('text') or '')
            if not _has_ticker_contract(body):
                return _fail(f'{cmd} missing ticker symbol or Ticker: NONE')

    for label, payload in (
        ('format', text),
        ('explain', explain),
        ('runner today', today_result.get('text') or ''),
        ('runner explain', explain_result.get('text') or ''),
    ):
        if 'Ticker: NONE' not in payload:
            return _fail(f'{label} must include Ticker: NONE')
        if 'NO TRADE' not in payload.upper():
            return _fail(f'{label} must use NO TRADE header')
        if 'Entry zone:' in payload or 'Stop:' in payload:
            return _fail(f'{label} must not expose actionable entry/SL fields')

    print('TRADECARD_NO_CANDIDATE_HAS_TICKER_NONE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
