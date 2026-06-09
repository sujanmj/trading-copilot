#!/usr/bin/env python3
"""Unit tests — memory/calib outcome warnings when unresolved (Stage 48Q)."""

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
    print(f'MEMORY_OUTCOME_WARNING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import (
        calibration_unresolved_message,
        memory_outcome_warning,
    )
    from backend.telegram.lazy_command_runner import run_memory_only
    from backend.telegram.response_format import format_aihub_payload

    stats = {'predictions': 9, 'outcomes': 0}
    overall = {'total_predictions': 9, 'resolved_outcomes': 0}

    warn = memory_outcome_warning(stats, overall)
    if not warn or 'Outcome resolver not active yet' not in warn:
        return _fail(f'unexpected memory_outcome_warning: {warn!r}')
    if 'Do not trust win-rate/calibration until outcomes resolve' not in warn:
        return _fail('memory warning must caution against calibration trust')

    calib = calibration_unresolved_message(stats, overall)
    if calib != 'Calibration unavailable — outcomes unresolved.':
        return _fail(f'unexpected calibration_unresolved_message: {calib!r}')

    if memory_outcome_warning({'predictions': 4, 'outcomes': 2}, {}) is not None:
        return _fail('resolved outcomes must not emit memory warning')
    if calibration_unresolved_message({'predictions': 4, 'outcomes': 2}) is not None:
        return _fail('resolved outcomes must not emit calibration warning')

    zero_dashboard = {
        'ok': True,
        'stats': stats,
        'learning': {'overall': overall},
        'latest_outcomes': [],
    }
    with patch('backend.telegram.lazy_command_runner._load_json', return_value=zero_dashboard):
        memory_text = run_memory_only().get('text') or ''
    if warn not in memory_text:
        return _fail('/memory must surface memory_outcome_warning text')

    from backend.telegram.response_format import format_calibration_section_telegram

    with patch(
        'backend.analytics.unified_decision_engine.calibration_unresolved_message',
        return_value=calib,
    ):
        calib_text = format_calibration_section_telegram(
            summary={'live_resolved': 0, 'historical_resolved': 0},
        )
    if calib not in calib_text:
        return _fail('/aihub calib must surface calibration_unresolved_message')

    calib_payload = {
        'source': 'cache',
        'cache_age_seconds': 60,
        'summary': {'live_resolved': 0, 'historical_resolved': 0},
        'items': [],
    }
    with patch(
        'backend.analytics.unified_decision_engine.calibration_unresolved_message',
        return_value=calib,
    ):
        aihub_calib_text = format_aihub_payload('calib', calib_payload)
    if calib not in aihub_calib_text:
        return _fail('format_aihub_payload calib must surface calibration_unresolved_message')

    print('MEMORY_OUTCOME_WARNING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
