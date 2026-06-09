#!/usr/bin/env python3
"""Unit tests — /aihub full Calib warning when outcomes unresolved (Stage 48S)."""

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
    print(f'AIHUB_FULL_CALIB_WARNING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_aihub_full

    zero_stats = {'predictions': 0, 'outcomes': 0}
    zero_overall = {'total_predictions': 0, 'resolved_outcomes': 0}
    calib_payload = {
        'source': 'cache',
        'cache_age_seconds': 30,
        'summary': {},
        'items': [],
    }

    with patch(
        'backend.analytics.unified_decision_engine._load_memory_calibration_stats',
        return_value=(zero_stats, zero_overall, True),
    ):
        full_text = format_aihub_full({'calib': calib_payload})
        lower = full_text.lower()
        if 'no calibration warnings' in lower:
            return _fail('/aihub full must not say no calibration warnings when unresolved')
        if 'calibration unavailable — outcomes unresolved' not in lower:
            return _fail('/aihub full missing calibration unavailable line')
        if '- live resolved: 0' not in full_text:
            return _fail('/aihub full missing live resolved: 0')
        if '- historical resolved: 0' not in full_text:
            return _fail('/aihub full missing historical resolved: 0')

    print('AIHUB_FULL_CALIB_WARNING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
