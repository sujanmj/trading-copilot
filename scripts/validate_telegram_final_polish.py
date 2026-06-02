#!/usr/bin/env python3
"""
Validate Stage 45B5 Telegram final message polish wiring.

Prints TELEGRAM_FINAL_POLISH_OK on success.
Marker: TELEGRAM_STAGE_45B5_FINAL_MESSAGE_POLISH
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

MARKER = 'TELEGRAM_STAGE_45B5_FINAL_MESSAGE_POLISH'


def _fail(msg: str) -> int:
    print(f'TELEGRAM_FINAL_POLISH_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    fmt_path = PROJECT_ROOT / 'backend/telegram/response_format.py'
    bot_path = PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py'
    fmt_src = fmt_path.read_text(encoding='utf-8')
    bot_src = bot_path.read_text(encoding='utf-8')

    if MARKER not in fmt_src:
        return _fail(f'missing stage marker {MARKER} in response_format.py')

    required_helpers = (
        'format_calibration_rec_readable',
        'format_calibration_section_telegram',
        'filter_empty_bullets',
        'format_aihub_brain_full',
    )
    for name in required_helpers:
        if f'def {name}' not in fmt_src:
            return _fail(f'response_format missing {name}')

    if 'def handle_message' not in bot_src:
        return _fail('telegram_analysis_bot missing handle_message')
    if '_split_multiline_commands' not in bot_src:
        return _fail('telegram_analysis_bot missing multiline command guard')
    if 'handle_message(msg_text, from_user)' not in bot_src:
        return _fail('listener must route through handle_message')

    test_path = PROJECT_ROOT / 'scripts/test_telegram_final_polish.py'
    if not test_path.is_file():
        return _fail('missing scripts/test_telegram_final_polish.py')

    from backend.telegram.response_format import (
        FINAL_POLISH_STAGE_MARKER,
        format_calibration_rec_readable,
        format_calibration_section_telegram,
        strip_stage_markers,
    )

    if FINAL_POLISH_STAGE_MARKER != MARKER:
        return _fail('FINAL_POLISH_STAGE_MARKER mismatch')

    sample = format_calibration_rec_readable(
        {
            'bucket': '20-29',
            'type': 'increase_score',
            'strength': 'weak',
            'win_rate': 1.0,
            'expected_win_rate': 0.2618,
            'rationale': 'Realized win rate exceeds score-implied expectation.',
        }
    )
    if not sample or '20-29 bucket' not in sample:
        return _fail('format_calibration_rec_readable sample failed')
    if '{' in sample:
        return _fail('format_calibration_rec_readable must not emit raw JSON')

    section = strip_stage_markers(
        format_calibration_section_telegram(
            {
                'summary': {'live_resolved': 24, 'historical_resolved': 62},
                'recommendations': [
                    {
                        'bucket': '20-29',
                        'type': 'increase_score',
                        'strength': 'weak',
                        'win_rate': 1.0,
                        'expected_win_rate': 0.2618,
                        'rationale': 'calibration gap detected',
                    }
                ],
            },
            {'watch': 3, 'avoid': 2},
        )
    )
    for token in ("{'bucket'", '"bucket":', MARKER):
        if token in section:
            return _fail(f'calibration section leaked forbidden token: {token}')
    if 'Live resolved: 24' not in section:
        return _fail('calibration section missing live resolved')
    if 'Recommendations:' not in section:
        return _fail('calibration section missing recommendations header')

    print(MARKER)
    print('TELEGRAM_FINAL_POLISH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
