#!/usr/bin/env python3
"""Unit tests — /aihub calib real sample rendering (Stage 49A)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'AIHUB_CALIB_REAL_SAMPLE_RENDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import calibration_render_lines
    from backend.telegram.response_format import _aihub_full_calib_lines, format_calibration_section_telegram

    ready_lines = [
        'Resolved outcomes: 25',
        'Pending outcomes: 165',
        'Hit rate: 56.0%',
        'Bullish hit rate: 62.0%',
        'Bearish/rejection hit rate: 48.0%',
        'Neutral count: 3',
        'Last resolved: 2026-05-27T11:00:00',
    ]

    with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='ready'):
        with patch('backend.analytics.unified_decision_engine.calibration_ready_message', return_value=ready_lines):
            lines = calibration_render_lines({'outcomes': 25}, {'resolved_outcomes': 25})
            if 'Hit rate: 56.0%' not in lines:
                return _fail(f'ready calibration lines missing hit rate: {lines!r}')

            calib_text = format_calibration_section_telegram()
            if 'Calibration unavailable' in calib_text:
                return _fail('ready sample must not show unavailable')
            if 'Hit rate: 56.0%' not in calib_text:
                return _fail('format_calibration_section_telegram missing hit rate')

            full_lines = _aihub_full_calib_lines({}, {})
            joined = '\n'.join(full_lines)
            if 'Bullish hit rate: 62.0%' not in joined:
                return _fail('/aihub full calib missing bullish hit rate')

    print('AIHUB_CALIB_REAL_SAMPLE_RENDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
