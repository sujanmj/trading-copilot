#!/usr/bin/env python3
"""Phase 4B.6 — /opening aliases removed; /radar only for opening rally."""

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

REDIRECT = 'Use /radar for opening rally candidates.'


def _fail(msg: str) -> int:
    print(f'TELEGRAM_OPENING_RADAR_ROUTING_4B6_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.lazy_command_runner import format_canonical_health_text
    from backend.telegram.premarket_scheduler import format_schedule_text
    from backend.telegram.telegram_analysis_bot import (
        HELP_TEXT,
        TELEGRAM_BOT_COMMANDS,
        handle_analysis_command,
        parse_command,
    )
    from backend.telegram.telegram_command_normalize import (
        REMOVED_OPENING_ALIAS_MESSAGE,
        normalize_parsed_command,
    )

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51G':
        return _fail(f'expected AstraEdge 51G got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    if REMOVED_OPENING_ALIAS_MESSAGE != REDIRECT:
        return _fail('redirect message mismatch')

    for text, expected_cmd in (
        ('/opening', 'removed_opening_alias'),
        ('/opening radar', 'removed_opening_alias'),
        ('/opening  radar', 'removed_opening_alias'),
    ):
        cmd, args = normalize_parsed_command(*parse_command(text))
        if cmd != expected_cmd:
            return _fail(f'{text!r} must parse to {expected_cmd!r} got {cmd!r}')

    cmd_radar, _ = normalize_parsed_command(*parse_command('/radar'))
    if cmd_radar != 'radar':
        return _fail('/radar must parse to radar')

    radar_board = '<b>Opening Rally Radar — 09:20 IST</b>\n1. RAILTEL'
    with patch('backend.telegram.lazy_command_runner.run_radar_only', return_value={'text': radar_board}) as mock_radar:
        radar_results = handle_analysis_command('/radar', 'test', dry_run=True)
        mock_radar.assert_called_once()
    if 'Opening Rally Radar' not in str(radar_results[0].get('text', '')):
        return _fail('/radar must return opening rally radar')

    with patch('backend.telegram.lazy_command_runner.run_radar_only') as mock_radar:
        opening_results = handle_analysis_command('/opening', 'test', dry_run=True)
        mock_radar.assert_not_called()
    if REDIRECT not in str(opening_results[0].get('text', '')):
        return _fail('/opening must return redirect to /radar')

    with patch('backend.telegram.lazy_command_runner.run_radar_only') as mock_radar:
        opening_radar_results = handle_analysis_command('/opening radar', 'test', dry_run=True)
        mock_radar.assert_not_called()
    if REDIRECT not in str(opening_radar_results[0].get('text', '')):
        return _fail('/opening radar must return redirect to /radar')

    help_results = handle_analysis_command('/help', 'test', dry_run=True)
    help_text = str(help_results[0].get('text', ''))
    if help_text != HELP_TEXT:
        return _fail('/help must return HELP_TEXT')
    if '/opening' in help_text.lower() and 'same as /radar' in help_text.lower():
        return _fail('/help must not list /opening alias')
    if '/radar' not in help_text:
        return _fail('/help must list /radar')

    schedule_results = handle_analysis_command('/schedule', 'test', dry_run=True)
    schedule_text = str(schedule_results[0].get('text', ''))
    if schedule_text != format_schedule_text():
        return _fail('/schedule must return format_schedule_text()')
    if '/opening' in schedule_text.lower():
        return _fail('/schedule must not mention /opening')
    if '/radar' not in schedule_text:
        return _fail('/schedule must mention /radar')

    health_text = format_canonical_health_text()
    if 'AstraEdge 51G' not in health_text:
        return _fail('/health must show AstraEdge 51G')

    cmd_names = {row.get('command') for row in TELEGRAM_BOT_COMMANDS}
    if 'opening' in cmd_names:
        return _fail('TELEGRAM_BOT_COMMANDS must not register opening')
    if 'radar' not in cmd_names:
        return _fail('TELEGRAM_BOT_COMMANDS must register radar')

    print('TELEGRAM_OPENING_RADAR_ROUTING_4B6_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
