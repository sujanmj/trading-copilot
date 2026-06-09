#!/usr/bin/env python3
"""Unit tests for Telegram AI provider masking (Stage 48M)."""

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
    print(f'TELEGRAM_AI_PROVIDER_MASKING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if '({provider})' in bot_src:
        return _fail('telegram_analysis_bot must not format provider in AI answer header')
    for provider in ('groq', 'gemini', 'claude', 'anthropic'):
        if f'AI answer</b> ({provider})' in bot_src.lower():
            return _fail(f'must not expose provider {provider} in AI answer header')

    from backend.telegram.telegram_analysis_bot import _handle_ask

    with patch('backend.telegram.telegram_analysis_bot.guarded_ask_ai', return_value={
        'success': True,
        'text': 'Sample answer',
        'provider': 'groq',
    }):
        with patch('backend.ai.ask_context_builder.build_ask_prompt', return_value='prompt'):
            text = _handle_ask('ai what changed overnight?')

    if 'groq' in text.lower() or 'gemini' in text.lower() or 'claude' in text.lower():
        return _fail('Telegram AI answer must not expose provider names')
    if '🤖 AI answer' not in text:
        return _fail('Telegram AI answer must use masked header')

    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    dry = handle_analysis_command('/ask ai test question', 'test_user', dry_run=True)
    dry_text = str((dry[0] if dry else {}).get('text') or '')
    if 'groq' in dry_text.lower():
        return _fail('dry_run ask must not expose groq')

    print('TELEGRAM_AI_PROVIDER_MASKING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
