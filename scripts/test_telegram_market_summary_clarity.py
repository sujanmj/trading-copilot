#!/usr/bin/env python3
"""
Dry-run checks for Stage 45B6 Telegram /aihub market summary clarity.

Prints TELEGRAM_MARKET_SUMMARY_CLARITY_TEST_OK on success.
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

FORBIDDEN_PHRASES = (
    'TELEGRAM_STAGE',
    'GUI_BUILD_STAGE',
    'BACKEND_STAGE',
    'QA_STAGE',
    "{'bucket'",
    '"bucket":',
    'undefined',
)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_MARKET_SUMMARY_CLARITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _check_text(label: str, text: str) -> int | None:
    lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lower:
            return _fail(f'{label} contains forbidden phrase: {phrase!r}')
    if text.strip().startswith('{') or text.strip().startswith('['):
        return _fail(f'{label} looks like raw JSON')
    if len(text.strip()) < 20:
        return _fail(f'{label} response too short')
    return None


def main() -> int:
    from backend.telegram.response_format import (
        format_aihub_market_section,
        format_aihub_payload,
        strip_stage_markers,
    )
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    stale_payload = {
        'source': 'cache',
        'cache_age_seconds': 7200,
        'market_mode': 'INDIA_MODE',
        'summary': {},
        'items': [],
        'warnings': ['market_data_stale', 'underlying_market_data_stale'],
    }
    stale_text = strip_stage_markers(format_aihub_payload('market', stale_payload))
    err = _check_text('stale_payload', stale_text)
    if err:
        return err
    if re.search(r'Mode:.*·\s*fresh|·\s*fresh\b', stale_text, re.IGNORECASE):
        return _fail('stale payload must not show fresh mode label')
    if 'Status: stale market snapshot' not in stale_text:
        return _fail('stale payload missing stale status line')
    if 'Reason: underlying market data is old' not in stale_text:
        return _fail('stale payload missing reason line')
    if 'No useful cached item found' in stale_text:
        return _fail('stale payload must not show empty cached item message')

    fallback_lines = format_aihub_market_section({
        'market_mode': 'INDIA_MODE',
        'summary': {},
        'items': [],
        'warnings': ['market_data_stale'],
    })
    fallback_joined = '\n'.join(fallback_lines)
    if 'Status: stale market snapshot' not in fallback_joined:
        return _fail('format_aihub_market_section stale branch missing status')
    if ' · fresh' in fallback_joined:
        return _fail('format_aihub_market_section stale branch shows fresh suffix')

    empty_lines = format_aihub_market_section({
        'market_mode': 'RESEARCH_MODE',
        'summary': {},
        'items': [],
        'warnings': [],
    })
    empty_joined = '\n'.join(empty_lines)
    if 'No useful cached item found' in empty_joined:
        return _fail('empty market must not use legacy empty message')
    has_fallback = (
        'Watch:' in empty_joined
        or 'Top watch:' in empty_joined
        or 'Market payload limited' in empty_joined
    )
    if not has_fallback:
        return _fail('empty market missing fallback or limited message')

    def _no_refresh(*args, **kwargs):
        return {'ok': True}

    with patch('scripts.refresh_local_intelligence.run_refresh_scoped', side_effect=_no_refresh):
        results = handle_analysis_command('/aihub market', 'market_clarity_test', dry_run=True)
        if not results:
            return _fail('no response for /aihub market')
        live_text = strip_stage_markers(str(results[0].get('text') or ''))
        err = _check_text('/aihub market', live_text)
        if err:
            return err
        if 'No useful cached item found' in live_text:
            return _fail('/aihub market still shows legacy empty message')
        if re.search(r'Mode:.*·\s*fresh', live_text, re.IGNORECASE) and re.search(
            r'market_data_stale|underlying_market_data_stale|stale market snapshot',
            live_text,
            re.IGNORECASE,
        ):
            return _fail('/aihub market shows fresh alongside stale signals')
        if 'Warnings: market_data_stale' in live_text or 'Warnings: underlying_market_data_stale' in live_text:
            return _fail('/aihub market must not repeat stale warning codes when formatted')
        has_live_fallback = (
            'Watch:' in live_text
            or 'Top watch:' in live_text
            or 'Market payload limited' in live_text
            or 'stale market snapshot' in live_text
        )
        if not has_live_fallback:
            return _fail('/aihub market missing fallback or stale clarity content')

    print('TELEGRAM_MARKET_SUMMARY_CLARITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
