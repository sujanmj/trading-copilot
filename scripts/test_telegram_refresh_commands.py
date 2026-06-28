#!/usr/bin/env python3
"""Unit tests for Telegram refresh/schedule/health commands (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_REFRESH_COMMANDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_refresh(scope: str, *, dry_run: bool = False) -> dict:
    return {'ok': True, 'scope': scope, 'runtime': 'ok', 'news': 'ok', 'daily_pack': 'ok'}


def main() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')

    if '/notify test' in HELP_TEXT.lower() or 'notify test' in bot_src.lower():
        return _fail('/notify test must be removed')
    if 'Trading Copilot Commands' in HELP_TEXT:
        return _fail('old Trading Copilot menu must not appear')

    for cmd in ('/refresh', '/refresh quick', '/refresh full', '/schedule', '/health', '/premarket'):
        if cmd.replace('/', '') not in HELP_TEXT.lower() and cmd not in HELP_TEXT:
            if cmd == '/premarket':
                if '/premarket' not in HELP_TEXT:
                    return _fail(f'{cmd} missing from help')

    forbidden = ('railway restart', ' redeploy', 'reset db', 'delete /app/data', 'DROP TABLE')
    for phrase in forbidden:
        if phrase.lower() in bot_src.lower():
            # Allow explicit safety notes that redeploy is NOT performed
            if phrase.strip() == 'redeploy' and 'no restart or redeploy' in bot_src.lower():
                continue
            return _fail(f'forbidden phrase in bot: {phrase.strip()}')

    with patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_mock_refresh):
        for cmd in ('/refresh', '/refresh quick', '/refresh full'):
            results = handle_analysis_command(cmd, 'test', dry_run=True)
            text = str(results[0].get('text', '')) if results else ''
            if len(text) < 20:
                return _fail(f'{cmd} response too short')
            if 'restart' in text.lower() and 'no restart' not in text.lower():
                return _fail(f'{cmd} mentions restart without safety note')

    sched = handle_analysis_command('/schedule', 'test', dry_run=True)
    if '07:45' not in str(sched[0].get('text', '')):
        return _fail('/schedule missing 07:45')

    health = handle_analysis_command('/health', 'test', dry_run=True)
    if 'AstraEdge 51A' not in str(health[0].get('text', '')):
        return _fail('/health missing AstraEdge 51A')

    status = handle_analysis_command('/status', 'test', dry_run=True)
    if 'AstraEdge 51A' not in str(status[0].get('text', '')):
        return _fail('/status missing AstraEdge 51A build line')

    print('TELEGRAM_REFRESH_COMMANDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
