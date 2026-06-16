#!/usr/bin/env python3
"""Stage 50Q — /tradecard Telegram command wiring and ticker contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FORBIDDEN = re.compile(r'\b(guaranteed|99%)\b', re.IGNORECASE)
NAKED_BUY_SELL = re.compile(r'\bAction:\s*(BUY|SELL)\b', re.IGNORECASE)


def _has_ticker_contract(text: str) -> bool:
    if 'Ticker: NONE' in text:
        return True
    if re.search(r'\bTop reviewed:\s*<b>[A-Z][A-Z0-9]{1,14}</b>', text):
        return True
    if re.search(r'<b>[A-Z][A-Z0-9]{1,14}</b>\s*·', text):
        return True
    return False


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_TELEGRAM_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    fake_card = {
        'ok': True,
        'ticker': 'IXIGO',
        'status': 'VALID_ENTRY',
        'current_price': 420,
        'entry_zone': '418–422',
        'stop_loss': 410,
        'target_1': 430,
        'target_2': 440,
        'risk_reward': 2.1,
        'capital_plan': 'Paper only',
        'reason': 'Aligned setup',
        'invalid_if': 'Below 410',
        'exit_rule': 'Trim at T1',
        'confidence': 'MEDIUM',
        'paper_only': True,
        'session_date': '2026-06-16',
        'generated_at': '2026-06-16T10:00:00+05:30',
    }
    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('scripts.refresh_local_intelligence.run_refresh_scoped', return_value={'ok': True}):
        text = format_tradecard_telegram(explain=False)
        explain = format_tradecard_telegram(explain=True)
        today_result = run_tradecard_only('today')
        explain_result = run_tradecard_only('explain')
        for cmd in ('/tradecard', '/tradecard today', '/tradecard explain'):
            bot = handle_analysis_command(cmd, 'tradecard_test', dry_run=True)
            if not bot:
                return _fail(f'no bot response for {cmd}')
            body = str(bot[0].get('text') or '')
            if FORBIDDEN.search(body) or NAKED_BUY_SELL.search(body):
                return _fail(f'forbidden wording in {cmd}')
            if not _has_ticker_contract(body):
                return _fail(f'missing ticker or Ticker: NONE in {cmd}')

    if 'TRADE CARD' not in text or 'paper only' not in text.lower():
        return _fail('format_tradecard_telegram missing header/paper note')
    if not _has_ticker_contract(text):
        return _fail('missing ticker in tradecard text')
    if 'Explain' not in explain:
        return _fail('explain mode missing Explain section')
    if today_result.get('scope') != 'tradecard':
        return _fail(f'run_tradecard_only today wrong scope {today_result.get("scope")!r}')
    if explain_result.get('scope') != 'tradecard':
        return _fail(f'run_tradecard_only explain wrong scope {explain_result.get("scope")!r}')
    if 'IXIGO' not in (explain_result.get('text') or ''):
        return _fail('runner missing tradecard body')

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if "cmd == 'tradecard'" not in bot_src:
        return _fail('telegram_analysis_bot missing tradecard handler')
    if '<b>Trade Card:</b>' not in bot_src:
        return _fail('HELP_TEXT missing Trade Card section')

    print('TRADE_CARD_TELEGRAM_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
