#!/usr/bin/env python3
"""
Dry-run checks for Stage 45B5 Telegram final message polish.

Prints TELEGRAM_FINAL_POLISH_TEST_OK on success.
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
    '/action plan',
    '/aihub calib',
    '/aihub brain',
    '/aihub market',
    '/aihub global',
    '/aihub brain full',
)

MULTILINE = '/aihub brain\n/aihub govt\n/aihub scan'

FORBIDDEN_PHRASES = (
    "TELEGRAM_STAGE",
    "GUI_BUILD_STAGE",
    "BACKEND_STAGE",
    "QA_STAGE",
    "{'bucket'",
    '"bucket":',
    'undefined',
)

BRAIN_FULL_SECTIONS = (
    'Market read',
    'Actionability',
    'Top candidate',
    'Ranked candidates',
    'Reasons/supports',
    'Risks/blocks',
    'Calibration',
    'Memory learning',
    'Broker/external confluence',
    'Confirmation checklist',
)

DASH_ONLY_BULLET_RE = re.compile(r'^\s*[•\-]\s*[—–-]\s*$', re.MULTILINE)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_FINAL_POLISH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _check_text(label: str, text: str) -> int | None:
    lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lower:
            return _fail(f'{label} contains forbidden phrase: {phrase!r}')
    if 'none' in lower and re.search(r'\bnone\b.*bucket|bucket.*\bnone\b', lower):
        return _fail(f'{label} exposes None near bucket text')
    if DASH_ONLY_BULLET_RE.search(text):
        return _fail(f'{label} contains dash-only bullet')
    if len(text.strip()) < 20:
        return _fail(f'{label} response too short')
    return None


def main() -> int:
    from backend.telegram.response_format import strip_stage_markers
    from backend.telegram.telegram_analysis_bot import handle_analysis_command, handle_message

    def _no_refresh(*args, **kwargs):
        return {'ok': True}

    with patch('scripts.refresh_local_intelligence.run_refresh_scoped', side_effect=_no_refresh):
        for cmd in COMMANDS:
            results = handle_analysis_command(cmd, 'polish_test', dry_run=True)
            if not results:
                return _fail(f'no response for {cmd}')
            text = strip_stage_markers(str(results[0].get('text') or ''))
            err = _check_text(cmd, text)
            if err:
                return err

            if cmd == '/action plan':
                if 'Calibration:' in text and "{'bucket'" in text:
                    return _fail('/action plan still shows raw calibration dict')
                if 'AstraEdge Action Plan' not in text:
                    return _fail('/action plan missing title')

            if cmd == '/aihub calib':
                if 'Calibration' not in text:
                    return _fail('/aihub calib missing calibration header')
                if 'Live resolved:' not in text and 'No calibration data' not in text:
                    return _fail('/aihub calib missing live resolved or empty state')

            if cmd in ('/aihub brain', '/aihub market', '/aihub global'):
                if re.search(r'^\s*•\s*[—–-]\s*$', text, re.MULTILINE):
                    return _fail(f'{cmd} has dash-only bullet')

            if cmd == '/aihub brain full':
                for section in BRAIN_FULL_SECTIONS:
                    if section not in text:
                        return _fail(f'/aihub brain full missing section: {section}')

        multi_results = handle_message(MULTILINE, 'polish_test', dry_run=True)
        if len(multi_results) != 3:
            return _fail(f'multiline message expected 3 responses, got {len(multi_results)}')
        for idx, result in enumerate(multi_results, start=1):
            text = strip_stage_markers(str(result.get('text') or ''))
            if 'Unknown AI Hub tab' in text:
                return _fail(f'multiline response {idx} produced unknown tab error')
            err = _check_text(f'multiline/{idx}', text)
            if err:
                return err

        overflow = handle_message(
            '/aihub brain\n/aihub govt\n/aihub scan\n/aihub market',
            'polish_test',
            dry_run=True,
        )
        if len(overflow) != 1:
            return _fail('>3 multiline commands should return single guard message')
        guard = str(overflow[0].get('text') or '')
        if 'Multiple commands detected' not in guard:
            return _fail('>3 multiline commands missing guard message')

    print('TELEGRAM_FINAL_POLISH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
