#!/usr/bin/env python3
"""
Dry-run simulation for /action plan and /aihub brain full (Stage 45B3).

Prints TELEGRAM_ACTION_PLAN_TEST_OK on success.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
    '/action plan',
    '/aihub brain full',
    '/help',
)

FORBIDDEN_PHRASES = (
    'TELEGRAM_STAGE',
    'GUI_BUILD_STAGE',
    'BACKEND_STAGE',
    'Research only',
    'permanently disabled',
    'not trade execution',
)

FORBIDDEN_HELP = (
    '/action\n',
    '/action ',
    '/action_plan',
    '/brain full',
)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_ACTION_PLAN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import strip_stage_markers
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    for cmd in COMMANDS:
        results = handle_analysis_command(cmd, 'test_user', dry_run=True)
        if not results:
            return _fail(f'no response for {cmd}')
        text = strip_stage_markers(str(results[0].get('text') or ''))
        lower = text.lower()

        for phrase in FORBIDDEN_PHRASES:
            if phrase.lower() in lower:
                return _fail(f'forbidden phrase in {cmd}: {phrase!r}')

        if 'invest' in lower:
            return _fail(f'{cmd} must not say invest')

        if len(text.strip()) < 40:
            return _fail(f'response too short for {cmd}')

        if cmd == '/action plan':
            if 'AstraEdge Action Plan' not in text:
                return _fail('/action plan missing title')
            if 'Market state' not in text:
                return _fail('/action plan missing Market state')
            if 'Top candidate' not in text:
                return _fail('/action plan missing Top candidate')
            if 'No confirmed entry candidate' not in text and 'Ticker:' not in text:
                return _fail('/action plan missing candidate or no-entry message')
            if 'Why:' not in text:
                return _fail('/action plan missing Why')
            if 'Wait for:' not in text:
                return _fail('/action plan missing Wait for')
            if 'Avoid:' not in text:
                return _fail('/action plan missing Avoid')

        if cmd == '/aihub brain full':
            if 'AstraEdge Brain — Full' not in text:
                return _fail('/aihub brain full missing title')
            if 'Ranked candidates' not in text:
                return _fail('/aihub brain full missing Ranked candidates')

        if cmd == '/help':
            if '/action plan' not in text:
                return _fail('/help missing /action plan')
            if '/aihub brain full' not in text:
                return _fail('/help missing /aihub brain full')
            for bad in FORBIDDEN_HELP:
                if bad in text and bad != '/action plan':
                    if bad == '/action\n' and '/action plan' in text:
                        continue
                    if bad == '/action ' and '/action plan' in text:
                        continue
                    return _fail(f'/help must not include forbidden alias: {bad!r}')

    bare_action = handle_analysis_command('/action', 'test_user', dry_run=True)
    if not bare_action:
        return _fail('/action alone must return a response')
    bare_text = str(bare_action[0].get('text') or '')
    if 'AstraEdge Action Plan' not in bare_text:
        return _fail('/action alone must run /action plan (Stage 48J alias)')

    print('TELEGRAM_ACTION_PLAN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
