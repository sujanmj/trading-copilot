#!/usr/bin/env python3
"""Unit tests — /aihub calib resolver-active zero-resolved wording (Stage 49B)."""

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
    print(f'AIHUB_CALIB_RESOLVER_ACTIVE_ZERO_RESOLVED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import calibration_unresolved_message
    from backend.telegram.response_format import format_calibration_section_telegram

    stats = {'predictions': 190, 'outcomes': 0}
    overall = {'total_predictions': 190, 'resolved_outcomes': 0}

    with patch(
        'backend.storage.outcome_resolver.format_outcome_resolver_status_lines',
        return_value=['Outcome resolver active — awaiting eligible close/reference price data.'],
    ):
        lines = calibration_unresolved_message(stats, overall)

    if 'Calibration unavailable — outcomes unresolved.' not in lines[0]:
        return _fail(f'unexpected first line: {lines!r}')
    if 'Outcome resolver active — awaiting eligible close/reference price data.' not in lines:
        return _fail('calib unresolved must include resolver active awaiting line')
    if 'Do not trust win-rate until outcome resolver completes.' not in lines[-1]:
        return _fail('calib unresolved must include trust warning')

    with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='unresolved'):
        with patch('backend.analytics.unified_decision_engine.calibration_render_lines', return_value=lines):
            calib_text = format_calibration_section_telegram()
    for line in lines:
        if line not in calib_text:
            return _fail(f'format_calibration_section_telegram missing {line!r}')

    print('AIHUB_CALIB_RESOLVER_ACTIVE_ZERO_RESOLVED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
