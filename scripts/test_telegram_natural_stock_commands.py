#!/usr/bin/env python3
"""Unit tests for natural stock command routing (Stage 48M)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_NATURAL_STOCK_COMMANDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_command_normalize import resolve_natural_command
    from backend.telegram.response_format import strip_stage_markers
    from backend.telegram.telegram_analysis_bot import handle_analysis_command
    from unittest.mock import patch

    cases = (
        ('Stocks to buy tomorrow?', 'tomorrow'),
        ('which stock to buy tomorrow', 'tomorrow'),
        ('stock for tomorrow', 'tomorrow'),
        ('stocks to buy today', 'today'),
        ('broker reliance', 'broker'),
    )
    for phrase, expected_cmd in cases:
        routed = resolve_natural_command(phrase)
        if not routed or routed[0] != expected_cmd:
            return _fail(f'expected {phrase!r} -> {expected_cmd}, got {routed!r}')

    with patch('backend.telegram.telegram_analysis_bot._handle_stock_decision_command', return_value='TOMORROW_PAYLOAD'):
        results = handle_analysis_command('Stocks to buy tomorrow?', 'test_user', dry_run=True)
    text = strip_stage_markers(str((results[0] if results else {}).get('text') or ''))
    if text != 'TOMORROW_PAYLOAD':
        return _fail('natural tomorrow question must route to tomorrow handler')
    if 'Unknown command: stocks' in text:
        return _fail('must not treat natural phrase as unknown stocks command')

    with patch('backend.telegram.telegram_analysis_bot._handle_stock_decision_command') as mock_tomorrow:
        mock_tomorrow.return_value = (
            '<b>AstraEdge — Tomorrow</b>\n\nTop candidate: RELIANCE — WATCH FOR ENTRY\n'
            '<i>Research only — confirm with price + volume.</i>'
        )
        results = handle_analysis_command('which stock to buy tomorrow', 'test_user', dry_run=True)
    out = strip_stage_markers(str((results[0] if results else {}).get('text') or '')).lower()
    if 'buy now' in out or 'guaranteed' in out:
        return _fail('natural tomorrow route must not use buy-now language')
    if 'watch for entry' not in out and 'watch_for_entry' not in out:
        return _fail('natural tomorrow route should preserve watch-for-entry wording')

    print('TELEGRAM_NATURAL_STOCK_COMMANDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
