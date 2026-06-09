#!/usr/bin/env python3
"""Unit tests — live memory outcomes=0 calibration warnings (Stage 48S)."""

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
    print(f'AIHUB_CALIB_OUTCOMES_UNRESOLVED_LIVE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        calibration_outcomes_unresolved,
        calibration_unresolved_message,
    )
    from backend.telegram.response_format import format_aihub_payload, format_calibration_section_telegram

    zero_dashboard = {
        'ok': True,
        'stats': {'predictions': 0, 'outcomes': 0},
        'learning': {'overall': {'total_predictions': 0, 'resolved_outcomes': 0}},
    }

    with patch(
        'backend.analytics.unified_decision_engine._load_memory_calibration_stats',
        return_value=(zero_dashboard['stats'], zero_dashboard['learning']['overall'], True),
    ):
        if not calibration_outcomes_unresolved():
            return _fail('outcomes=0 memory must mark calibration unresolved')
        calib_lines = calibration_unresolved_message()
        if len(calib_lines) < 2:
            return _fail(f'expected calibration warning lines got {calib_lines!r}')

        calib_text = format_calibration_section_telegram()
        if 'No calibration data cached' in calib_text:
            return _fail('calib must not say No calibration data cached when outcomes unresolved')
        for line in calib_lines:
            if line not in calib_text:
                return _fail(f'format_calibration_section_telegram missing {line!r}')
        if 'Live resolved: 0' not in calib_text or 'Historical resolved: 0' not in calib_text:
            return _fail('calib must show live/historical resolved 0')

        calib_payload = {
            'source': 'cache',
            'cache_age_seconds': 30,
            'summary': {},
            'items': [],
        }
        aihub_calib = format_aihub_payload('calib', calib_payload)
        if 'No calibration data cached' in aihub_calib:
            return _fail('/aihub calib must not say No calibration data cached')
        for line in calib_lines:
            if line not in aihub_calib:
                return _fail(f'format_aihub_payload calib missing {line!r}')

    resolved_stats = {'predictions': 4, 'outcomes': 2}
    if calibration_outcomes_unresolved(resolved_stats, {'resolved_outcomes': 2}):
        return _fail('resolved outcomes must not be unresolved')

    print('AIHUB_CALIB_OUTCOMES_UNRESOLVED_LIVE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
