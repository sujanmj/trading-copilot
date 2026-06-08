#!/usr/bin/env python3
"""
Dry-run simulation for Telegram Analysis Bot (Stage 45TG5).

Prints TELEGRAM_ANALYSIS_BOT_TEST_OK on success.
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

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')
os.environ.setdefault('TELEGRAM_ALLOW_CLAUDE', '0')
os.environ.setdefault('TELEGRAM_TRADE_COMMANDS_ENABLED', '0')
os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')

COMMANDS = [
    '/start',
    '/help',
    '/status',
    '/memory',
    '/broker',
    '/aihub',
    '/aihub brain',
    '/aihub govt',
    '/aihub scan',
    '/aihub market',
    '/aihub global',
    '/aihub news',
    '/aihub calib',
    '/aihub journal',
    '/aihub full',
    '/news',
    '/qa',
    '/morning',
    '/close',
    '/today',
    '/tomorrow',
    '/why TATA',
    '/ask ai what changed overnight?',
    '/buy TATA',
    '/sell RELIANCE',
]

FORBIDDEN_USER_PHRASES = (
    'permanently disabled',
    'Blocked forever',
    'not trade execution',
    'Shadow mode only',
    'Research only',
    'TELEGRAM_STAGE',
)

BLOCKED_RESPONSE = (
    "I can't place orders. Try /today, /tomorrow, /aihub scan, or /ask ai <question>."
)

REFRESH_CALLS: list[str] = []
AI_CALLS: list[str] = []


def _fail(msg: str) -> int:
    print(f'TELEGRAM_ANALYSIS_BOT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _track_refresh(scope: str, *, dry_run: bool = False) -> dict:
    REFRESH_CALLS.append(scope)
    return {'ok': True, 'scope': scope, 'dry_run': dry_run}


def main() -> int:
    from backend.telegram.ai_usage_guard import allow_claude, is_llm_command, llm_allowed
    from backend.telegram.lazy_command_runner import STAGE_MARKER
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    if allow_claude():
        return _fail('Claude must be disabled by default (TELEGRAM_ALLOW_CLAUDE=0)')

    def _fake_ask(*args, **kwargs):
        AI_CALLS.append(kwargs.get('use_case') or 'ask')
        return {'success': True, 'text': 'simulated', 'provider': 'groq', 'used_llm': True}

    with patch('scripts.refresh_local_intelligence.run_refresh_scoped', side_effect=_track_refresh):
        with patch('backend.telegram.ai_usage_guard.guarded_ask_ai', side_effect=lambda *a, **k: _fake_ask(*a, **k)):
            for cmd in COMMANDS:
                results = handle_analysis_command(cmd, 'test_user', dry_run=True)
                if not results:
                    return _fail(f'no response for {cmd}')
                text = str(results[0].get('text') or '')

                if cmd not in ('/buy TATA', '/sell RELIANCE'):
                    for phrase in FORBIDDEN_USER_PHRASES:
                        if phrase.lower() in text.lower():
                            if cmd == '/broker' and phrase == 'Research only':
                                continue
                            return _fail(f'forbidden phrase in {cmd}: {phrase!r}')

                if len(text.strip()) < 20 and cmd not in ('/buy TATA', '/sell RELIANCE'):
                    return _fail(f'response too short for {cmd}')

                if cmd in ('/buy TATA', '/sell RELIANCE'):
                    if text.strip() != BLOCKED_RESPONSE:
                        return _fail(f'{cmd} must return clean blocked response')

                if cmd == '/status' and 'manual by user' in text.lower():
                    return _fail('/status must not show manual trading by user')

                if cmd == '/ask ai what changed overnight?':
                    if not llm_allowed('ask', 'ai what changed overnight?'):
                        return _fail('/ask ai must allow LLM')
                elif is_llm_command('ask', 'ai what changed overnight?') and cmd != '/ask ai what changed overnight?':
                    pass
                elif cmd.startswith('/ask'):
                    pass
                elif 'used_llm' in text:
                    return _fail(f'unexpected LLM marker in {cmd}')

    if 'news' not in REFRESH_CALLS:
        return _fail('/news must call scoped news refresh')
    if any(scope == 'all' for scope in REFRESH_CALLS):
        return _fail('must not call full/all refresh scope')
    if 'run_local' in ' '.join(REFRESH_CALLS):
        return _fail('must not call run_local')

    non_ask_ai = [c for c in COMMANDS if not c.startswith('/ask ai')]
    if AI_CALLS and len(AI_CALLS) > 1:
        return _fail('only /ask ai should invoke AI path')

    bot_src = (PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_analysis_bot.py').read_text(encoding='utf-8')
    if 'run_local.main' in bot_src or 'import run_local' in bot_src:
        return _fail('telegram_analysis_bot must not reference run_local')
    if STAGE_MARKER not in bot_src:
        return _fail('stage marker missing from bot module')
    if STAGE_MARKER != 'TELEGRAM_STAGE_45TG5_OUTPUT_CLEAN_AIHUB_FULL':
        return _fail('unexpected stage marker')

    print('TELEGRAM_ANALYSIS_BOT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
