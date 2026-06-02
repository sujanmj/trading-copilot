#!/usr/bin/env python3
"""
Validate Telegram Analysis Bot user-facing safety wording (Stage 45TG4).

Prints TELEGRAM_ANALYSIS_BOT_WORDING_OK on success.
Marker: TELEGRAM_STAGE_45TG4_USER_FRIENDLY_SAFETY_WORDING
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

MARKER = 'TELEGRAM_STAGE_45TG4_USER_FRIENDLY_SAFETY_WORDING'
RESEARCH_FOOTER = 'Research only. You decide and place trades manually.'
FORBIDDEN_USER_PHRASES = (
    'permanently disabled',
    'Blocked forever',
    'not trade execution',
    'Shadow mode only',
)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')
os.environ.setdefault('TELEGRAM_ALLOW_CLAUDE', '0')
os.environ.setdefault('TELEGRAM_TRADE_COMMANDS_ENABLED', '0')
os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_ANALYSIS_BOT_WORDING_FAIL: {msg}', file=sys.stderr)
    return 1


def _env_disabled(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('0', 'false', 'no', 'off', '')


def main() -> int:
    fmt_path = PROJECT_ROOT / 'backend' / 'telegram' / 'response_format.py'
    bot_path = PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_analysis_bot.py'
    lazy_path = PROJECT_ROOT / 'backend' / 'telegram' / 'lazy_command_runner.py'

    fmt_src = fmt_path.read_text(encoding='utf-8')
    bot_src = bot_path.read_text(encoding='utf-8')
    lazy_src = lazy_path.read_text(encoding='utf-8')

    if MARKER not in lazy_src or MARKER not in bot_src:
        return _fail(f'missing marker {MARKER}')

    if RESEARCH_FOOTER not in fmt_src:
        return _fail('missing research footer constant')
    if 'AstraEdge does not place orders' not in fmt_src:
        return _fail('missing blocked trade user message')
    if 'Trading: <b>manual by user</b>' not in fmt_src:
        return _fail('status must show manual trading by user')

    for phrase in FORBIDDEN_USER_PHRASES:
        if phrase in fmt_src:
            return _fail(f'forbidden phrase in response_format: {phrase!r}')

    if 'Order commands are not supported' not in bot_src:
        return _fail('help must list unsupported order commands')

    if not _env_disabled('TELEGRAM_TRADE_COMMANDS_ENABLED'):
        return _fail('TELEGRAM_TRADE_COMMANDS_ENABLED must be off (0)')
    if os.environ.get('DISABLE_TRADE_EXECUTION', '').strip().lower() not in ('1', 'true', 'yes', 'on'):
        return _fail('DISABLE_TRADE_EXECUTION must be 1')

    from backend.telegram.lazy_command_runner import STAGE_MARKER
    from backend.telegram.response_format import (
        BLOCKED_TRADE_RESPONSE,
        RESEARCH_FOOTER as RF,
        TRADE_EXECUTION_PERMANENTLY_DISABLED,
    )
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    if STAGE_MARKER != MARKER:
        return _fail('STAGE_MARKER mismatch')
    if RF != RESEARCH_FOOTER:
        return _fail('RESEARCH_FOOTER mismatch')
    if not TRADE_EXECUTION_PERMANENTLY_DISABLED:
        return _fail('TRADE_EXECUTION_PERMANENTLY_DISABLED must be True')

    order_tokens = ('place_order', 'execute_trade', 'submit_order', 'broker.place')
    for token in order_tokens:
        if token in bot_src and 'BLOCKED_TRADE' not in bot_src:
            return _fail(f'possible order placement path: {token}')

    def _no_refresh(*args, **kwargs):
        return {'ok': True}

    samples = (
        '/start',
        '/status',
        '/buy TATA',
        '/sell RELIANCE',
    )
    with patch('scripts.refresh_local_intelligence.run_refresh_scoped', side_effect=_no_refresh):
        for cmd in samples:
            results = handle_analysis_command(cmd, 'wording_test', dry_run=True)
            if not results:
                return _fail(f'no response for {cmd}')
            text = str(results[0].get('text') or '')
            if RESEARCH_FOOTER.lower() not in text.lower():
                return _fail(f'missing research footer for {cmd}')
            for phrase in FORBIDDEN_USER_PHRASES:
                if phrase.lower() in text.lower():
                    return _fail(f'forbidden phrase in response for {cmd}: {phrase!r}')

            if cmd == '/buy TATA':
                if "I don't place orders" not in text:
                    return _fail('/buy TATA must explain orders are not placed')
                if 'TATA' not in text:
                    return _fail('/buy TATA must reference symbol in analysis hints')
            if cmd == '/sell RELIANCE':
                if "I don't place orders" not in text:
                    return _fail('/sell RELIANCE must explain orders are not placed')
                if 'RELIANCE' not in text:
                    return _fail('/sell RELIANCE must reference symbol in analysis hints')

            if cmd == '/status' and 'manual by user' not in text.lower():
                return _fail('/status must show manual trading by user')

    blocked_only = handle_analysis_command('/execute', 'wording_test', dry_run=True)
    if blocked_only:
        bt = str(blocked_only[0].get('text') or '')
        if BLOCKED_TRADE_RESPONSE not in bt:
            return _fail('/execute must return blocked trade response')

    print(MARKER)
    print('TELEGRAM_ANALYSIS_BOT_WORDING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
