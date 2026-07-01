#!/usr/bin/env python3
"""
Dry-run simulation for clean Telegram output (Stage 50O).

Prints TELEGRAM_OUTPUT_CLEAN_TEST_OK on success.
"""

from __future__ import annotations

import os
import re
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
    '/myfeed list',
    '/tradecard',
    '/catalysts',
)

FORBIDDEN_PHRASES = (
    'Research only. You decide and place trades manually.',
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
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_SEQUENCE
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51C':
        return _fail(f'expected AstraEdge 51C got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    if len(FULL_SNAPSHOT_SEQUENCE) != 34:
        return _fail(f'/full must remain 34 read-only steps, got {len(FULL_SNAPSHOT_SEQUENCE)}')
    if '/aihub reddit' in FULL_SNAPSHOT_SEQUENCE:
        return _fail('/full must not include removed Reddit step')

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
                        if cmd == '/broker' and 'Research only. You decide' in phrase:
                            continue
                        return _fail(f'forbidden phrase in {cmd}: {phrase!r}')

            if cmd == '/buy TATA':
                if text.strip() != BLOCKED_RESPONSE:
                    return _fail(f'/buy must return clean blocked response: {text!r}')
                continue

            if cmd == '/help':
                for needle in (
                    '/feed',
                    '/myfeed list',
                    '/myfeed today',
                    '/myfeed scan',
                    'market news text',
                    '<b>Catalyst Radar:</b>',
                    '/catalysts — stock-specific catalyst radar',
                    '/catalysts today',
                    '/catalysts explain',
                    '<b>Trade Card:</b>',
                    '/tradecard — one-stock paper trade card',
                    '/tradecard today',
                    '/tradecard explain',
                ):
                    if needle.lower() not in text.lower() and needle not in text:
                        return _fail(f'/help missing My Feed text-only command marker {needle!r}')
                if 'reddit' in text.lower():
                    return _fail('/help must not mention Reddit')
                if 'screenshot' in text.lower() or 'groq vision' in text.lower():
                    return _fail('/help must not advertise image/OCR My Feed intake')
                continue

            if cmd == '/myfeed list':
                if 'my feed' not in text.lower():
                    return _fail('/myfeed list must return My Feed list header/body')
                if 'reddit' in text.lower():
                    return _fail('/myfeed list must not mention Reddit')
                continue

            if cmd == '/catalysts':
                lower = text.lower()
                if 'catalyst' not in lower:
                    return _fail('/catalysts must return catalyst radar output')
                if re.search(r'\bAction:\s*(BUY|SELL)\b', text, re.I):
                    return _fail('/catalysts must not contain naked BUY/SELL action labels')
                continue

            if cmd == '/tradecard':
                lower = text.lower()
                if 'trade card' not in lower:
                    return _fail('/tradecard must return trade card header')
                if 'paper only' not in lower and 'no trade' not in lower:
                    return _fail('/tradecard must label paper-only or no-trade state')
                if re.search(r'\bAction:\s*(BUY|SELL)\b', text, re.I):
                    return _fail('/tradecard must not contain naked BUY/SELL action labels')
                continue

            if cmd in ('/aihub full', '/aihub all'):
                for section in AIHUB_FULL_SECTIONS:
                    if section not in text:
                        return _fail(f'{cmd} missing section {section!r}')
                if '🗞 My Feed' in text or 'My Feed</b>' in text:
                    return _fail(f'{cmd} must not embed My Feed after Stage 50H')
                if '🤖 Reddit' in text or 'Reddit /' in text:
                    return _fail(f'{cmd} must not include removed Reddit section')
                if 'Use /today or /tomorrow for the short action list.' not in text:
                    return _fail(f'{cmd} missing action list hint')
                continue

            if cmd in ('/today', '/tomorrow'):
                if 'invest' in text.lower():
                    return _fail(f'{cmd} must not say invest')
                if 'Decision Engine is pending' in text or 'Stock Decision Engine is pending' in text:
                    return _fail(f'{cmd} must use stock decision engine, not pending wording')
                if not any(
                    marker in text
                    for marker in (
                        'AstraEdge',
                        'No decision available',
                        'No clean candidate',
                        'Top watch-for-entry',
                        '📋 Today',
                        '📋 Tomorrow',
                    )
                ):
                    return _fail(f'{cmd} must return engine formatted message')
                continue

            if cmd == '/why TATA':
                if 'why' not in text.lower() and 'No decision data' not in text:
                    return _fail('/why TATA must explain or report missing ticker')

    print('TELEGRAM_OUTPUT_CLEAN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
