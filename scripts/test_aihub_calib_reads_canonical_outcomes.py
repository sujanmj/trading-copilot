#!/usr/bin/env python3
"""Unit tests — /aihub calib reads canonical outcome store (Stage 49D)."""

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
    print(f'AIHUB_CALIB_READS_CANONICAL_OUTCOMES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.unified_decision_engine import calibration_render_lines, get_calibration_mode
    from backend.telegram.response_format import format_calibration_section_telegram

    ready_canonical = {
        'data_root': '/app/data',
        'resolved_total': 25,
        'pending_total': 165,
        'predictions_tracked': 190,
        'hit_rate': 0.56,
        'bullish_hit_rate': 0.62,
        'bearish_hit_rate': 0.48,
        'neutral': 3,
        'last_resolved_at': '2026-05-27T11:00:00',
    }
    zero_canonical = {
        'data_root': '/app/data',
        'resolved_total': 0,
        'pending_total': 190,
        'predictions_tracked': 190,
        'hit_rate': None,
        'bullish_hit_rate': None,
        'bearish_hit_rate': None,
        'neutral': 0,
        'last_resolved_at': None,
    }

    with patch('backend.analytics.unified_decision_engine._canonical_outcome_stats', return_value=ready_canonical):
        if get_calibration_mode() != 'ready':
            return _fail('resolved_total=25 must be ready mode')
        lines = calibration_render_lines()
        if 'Resolved outcomes: 25' not in lines:
            return _fail(f'ready calib missing resolved count: {lines!r}')
        if 'Hit rate: 56.0%' not in lines:
            return _fail(f'ready calib missing hit rate: {lines!r}')

    with patch('backend.analytics.unified_decision_engine._canonical_outcome_stats', return_value=zero_canonical):
        with patch(
            'backend.storage.outcome_resolver.format_outcome_resolver_status_lines',
            return_value=['Outcome resolver active — awaiting eligible close/reference price data.'],
        ):
            if get_calibration_mode() != 'unresolved':
                return _fail('resolved_total=0 must be unresolved mode')
            lines = calibration_render_lines()
            if 'Calibration unavailable — outcomes unresolved.' not in lines[0]:
                return _fail(f'unresolved calib unexpected: {lines!r}')
            calib_text = format_calibration_section_telegram()
            if 'Calibration unavailable' not in calib_text:
                return _fail('format_calibration_section_telegram must show unavailable when zero resolved')

    with patch('backend.analytics.unified_decision_engine._canonical_outcome_stats', return_value=ready_canonical):
        with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='ready'):
            calib_text = format_calibration_section_telegram()
            if 'Hit rate: 56.0%' not in calib_text:
                return _fail('ready calib telegram section missing hit rate')

    print('AIHUB_CALIB_READS_CANONICAL_OUTCOMES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
