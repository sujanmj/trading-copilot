#!/usr/bin/env python3
"""Unit tests — /aihub calib warmup rendering (Stage 49A)."""

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
    print(f'AIHUB_CALIB_WARMUP_RENDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import calibration_render_lines, get_calibration_mode
    from backend.telegram.response_format import _aihub_full_calib_lines, format_calibration_section_telegram

    stats = {'predictions': 40, 'outcomes': 8}
    overall = {'resolved_outcomes': 8}

    with patch('backend.analytics.unified_decision_engine.get_calibration_resolved_count', return_value=8):
        with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='warmup'):
            with patch(
                'backend.analytics.unified_decision_engine.calibration_warmup_message',
                return_value=[
                    'Calibration warming up — sample too small.',
                    'Resolved outcomes: 8',
                    'Pending outcomes: 32',
                    'Do not trust win-rate yet.',
                ],
            ):
                lines = calibration_render_lines(stats, overall)
                if 'Do not trust win-rate yet.' not in lines[-1]:
                    return _fail(f'warmup lines missing trust warning: {lines!r}')

                calib_text = format_calibration_section_telegram()
                if 'no calibration warnings' in calib_text.lower():
                    return _fail('warmup must not say no calibration warnings')
                if 'Calibration warming up' not in calib_text:
                    return _fail('format_calibration_section_telegram missing warmup')

                full_lines = _aihub_full_calib_lines({}, {})
                joined = '\n'.join(full_lines)
                if 'no calibration warnings' in joined.lower():
                    return _fail('/aihub full calib must not say no calibration warnings during warmup')

    print('AIHUB_CALIB_WARMUP_RENDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
