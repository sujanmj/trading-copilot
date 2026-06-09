#!/usr/bin/env python3
"""Unit tests — /aihub calib unresolved warnings as list (Stage 48R)."""

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


def _fail(msg: str) -> int:
    print(f'AIHUB_CALIB_UNRESOLVED_WARNING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import calibration_unresolved_message
    from backend.telegram.response_format import format_aihub_payload, format_calibration_section_telegram

    stats = {'predictions': 11, 'outcomes': 0}
    overall = {'total_predictions': 11, 'resolved_outcomes': 0}

    calib_lines = calibration_unresolved_message(stats, overall)
    if not isinstance(calib_lines, list):
        return _fail(f'calibration_unresolved_message must return list got {type(calib_lines)!r}')
    if len(calib_lines) < 2:
        return _fail(f'expected at least 2 calibration warning lines got {calib_lines!r}')
    if 'Calibration unavailable — outcomes unresolved.' not in calib_lines[0]:
        return _fail(f'unexpected first calibration line: {calib_lines[0]!r}')
    if 'Do not trust win-rate until outcome resolver completes.' not in ' '.join(calib_lines):
        return _fail('calibration warnings must caution against win-rate trust')

    if calibration_unresolved_message({'predictions': 3, 'outcomes': 2}) != []:
        return _fail('resolved outcomes must return empty calibration warning list')

    with patch(
        'backend.analytics.unified_decision_engine.calibration_unresolved_message',
        return_value=calib_lines,
    ):
        calib_text = format_calibration_section_telegram(
            summary={'live_resolved': 0, 'historical_resolved': 0},
        )
    for line in calib_lines:
        if line not in calib_text:
            return _fail(f'format_calibration_section_telegram missing {line!r}')

    calib_payload = {
        'source': 'cache',
        'cache_age_seconds': 90,
        'summary': {'live_resolved': 0, 'historical_resolved': 0},
        'items': [],
    }
    with patch(
        'backend.analytics.unified_decision_engine.calibration_unresolved_message',
        return_value=calib_lines,
    ):
        aihub_calib_text = format_aihub_payload('calib', calib_payload)
    for line in calib_lines:
        if line not in aihub_calib_text:
            return _fail(f'format_aihub_payload calib missing {line!r}')

    print('AIHUB_CALIB_UNRESOLVED_WARNING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
