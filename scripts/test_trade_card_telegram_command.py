#!/usr/bin/env python3
"""Stage 50R hotfix — /tradecard Telegram command wiring, ticker + explain contract."""

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
EXPLAIN_FIELDS = ('Reason:', 'Entry logic:', 'Risk logic:', 'Next action:')


def _has_ticker_contract(text: str) -> bool:
    if 'Ticker: NONE' in text:
        return True
    if re.search(r'\bTop reviewed:\s*<b>[A-Z][A-Z0-9]{1,14}</b>', text):
        return True
    if re.search(r'<b>[A-Z][A-Z0-9]{1,14}</b>\s*·', text):
        return True
    return False


def _has_explain_section(text: str) -> bool:
    if 'Explain' not in text:
        return False
    return all(field in text for field in EXPLAIN_FIELDS)


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_TELEGRAM_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.telegram.telegram_analysis_bot import handle_analysis_command
    from scripts._test_runtime_isolation import isolated_ai_usage_log

    with isolated_ai_usage_log():
        return _main_isolated(run_tradecard_only, format_tradecard_telegram, handle_analysis_command)


def _main_isolated(run_tradecard_only, format_tradecard_telegram, handle_analysis_command) -> int:
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
    missed_card = {
        'ok': True,
        'ticker': 'DEVYANI',
        'status': 'ENTRY_MISSED',
        'entry_zone': 'NO ACTIVE ENTRY',
        'reason': 'Strong move, but do not chase.',
        'paper_only': True,
    }
    sync_stub = {
        'tradecards_best': 'IXIGO',
        'selected': 'IXIGO',
        'source': 'radar',
        'reason': 'test',
        'status_override': '',
        'state': 'TRADECARD_CANDIDATE',
        'score': 80,
        'board': {},
    }
    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value=sync_stub), \
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
            if cmd == '/tradecard explain' and not _has_explain_section(body):
                return _fail(f'explain mode missing Explain section in {cmd}')

    if 'TRADE CARD' not in text or 'paper only' not in text.lower():
        return _fail('format_tradecard_telegram missing header/paper note')
    if not _has_ticker_contract(text):
        return _fail('missing ticker in tradecard text')
    if not _has_explain_section(explain):
        return _fail('explain mode missing Explain section')
    if 'Explain' in text:
        return _fail('plain tradecard must not include Explain section')

    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=missed_card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('DEVYANI', 'ENTRY_MISSED')), \
         patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value={
             'tradecards_best': 'DEVYANI',
             'selected': 'DEVYANI',
             'source': 'radar',
             'reason': 'test',
             'status_override': '',
             'state': 'CHASE_RISK',
             'score': 50,
             'board': {},
         }):
        missed_explain = format_tradecard_telegram(explain=True)
    if not _has_explain_section(missed_explain):
        return _fail('ENTRY_MISSED explain missing Explain section')
    if 'Ref entry:' in missed_explain or 'Ref SL:' in missed_explain:
        return _fail('ENTRY_MISSED explain must not show ref entry/SL/targets')
    if 'no active entry because entry is missed' not in missed_explain.lower():
        return _fail('ENTRY_MISSED explain missing entry logic wording')

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
