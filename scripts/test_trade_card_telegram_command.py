#!/usr/bin/env python3
"""Stage 50L — /tradecard Telegram command wiring."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_TELEGRAM_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.telegram.response_format import format_tradecard_telegram

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
    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card):
        text = format_tradecard_telegram(explain=False)
        explain = format_tradecard_telegram(explain=True)
        result = run_tradecard_only('explain')

    if 'TRADE CARD' not in text or 'paper only' not in text.lower():
        return _fail('format_tradecard_telegram missing header/paper note')
    if 'IXIGO' not in text:
        return _fail('missing ticker in tradecard text')
    if 'Explain' not in explain:
        return _fail('explain mode missing Explain section')
    if result.get('scope') != 'tradecard':
        return _fail(f'run_tradecard_only wrong scope key {result.get("scope")!r}')
    if 'IXIGO' not in (result.get('text') or ''):
        return _fail('runner missing tradecard body')

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if "cmd == 'tradecard'" not in bot_src:
        return _fail('telegram_analysis_bot missing tradecard handler')

    print('TRADE_CARD_TELEGRAM_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
