#!/usr/bin/env python3
"""
Dry-run simulation for clean Telegram output (Stage 45TG5).

Prints TELEGRAM_OUTPUT_CLEAN_TEST_OK on success.
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

COMMANDS = (
    '/help',
    '/status',
    '/memory',
    '/broker',
    '/aihub',
    '/aihub full',
    '/aihub all',
    '/aihub scan',
    '/today',
    '/tomorrow',
    '/why TATA',
    '/buy TATA',
)

FORBIDDEN_PHRASES = (
    'Research only',
    'Shadow mode',
    'not trade execution',
    'permanently disabled',
    'Blocked forever',
    'TELEGRAM_STAGE',
    'GUI_BUILD_STAGE',
    'BACKEND_STAGE',
    'QA_STAGE',
)

AIHUB_FULL_SECTIONS = (
    '🧠 Brain',
    '🏛 Govt',
    '📈 Scan',
    '📊 Market',
    '🌐 Global',
    '📰 News',
    '📺 TV',
    '🗞 My Feed',
    '📊 Calib',
    '📜 Journal',
)

BLOCKED_RESPONSE = (
    "I can't place orders. Try /today, /tomorrow, /aihub scan, or /ask ai <question>."
)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_OUTPUT_CLEAN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    def _no_refresh(*args, **kwargs):
        return {'ok': True}

    with patch('scripts.refresh_local_intelligence.run_refresh_scoped', side_effect=_no_refresh):
        for cmd in COMMANDS:
            results = handle_analysis_command(cmd, 'clean_test', dry_run=True)
            if not results:
                return _fail(f'no response for {cmd}')
            text = str(results[0].get('text') or '')

            if cmd != '/buy TATA':
                for phrase in FORBIDDEN_PHRASES:
                    if phrase.lower() in text.lower():
                        if cmd == '/broker' and phrase == 'Research only':
                            continue
                        return _fail(f'forbidden phrase in {cmd}: {phrase!r}')

            if cmd == '/buy TATA':
                if text.strip() != BLOCKED_RESPONSE:
                    return _fail(f'/buy must return clean blocked response: {text!r}')
                continue

            if cmd in ('/aihub full', '/aihub all'):
                for section in AIHUB_FULL_SECTIONS:
                    if section not in text:
                        return _fail(f'{cmd} missing section {section!r}')
                if '🤖 Reddit' in text or 'Reddit /' in text:
                    return _fail(f'{cmd} must not include removed Reddit section')
                if 'Use /today or /tomorrow for the short action list.' not in text:
                    return _fail(f'{cmd} missing action list hint')

            if cmd in ('/today', '/tomorrow'):
                if 'invest' in text.lower():
                    return _fail(f'{cmd} must not say invest')
                if 'Decision Engine is pending' in text or 'Stock Decision Engine is pending' in text:
                    return _fail(f'{cmd} must use stock decision engine, not pending wording')
                if 'AstraEdge' not in text and 'No decision available' not in text and 'No clean candidate' not in text:
                    return _fail(f'{cmd} must return engine formatted message')

            if cmd == '/why TATA':
                if 'why' not in text.lower() and 'No decision data' not in text:
                    return _fail('/why TATA must explain or report missing ticker')

    print('TELEGRAM_OUTPUT_CLEAN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
