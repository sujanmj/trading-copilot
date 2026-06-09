#!/usr/bin/env python3
"""Unit tests — /memory resolver-active zero-resolved wording (Stage 49B)."""

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
    print(f'MEMORY_RESOLVER_ACTIVE_ZERO_RESOLVED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_memory_only

    zero_dashboard = {
        'ok': True,
        'stats': {'predictions': 190, 'outcomes': 0},
        'learning': {'overall': {'total_predictions': 190, 'resolved_outcomes': 0, 'unresolved_predictions': 190}},
        'latest_outcomes': [],
    }

    canonical_zero = {
        'predictions_tracked': 190,
        'resolved_total': 0,
        'pending_total': 190,
    }

    with patch('backend.telegram.lazy_command_runner._load_json', return_value=zero_dashboard):
        with patch('backend.storage.outcome_resolver.get_canonical_outcome_stats', return_value=canonical_zero):
            with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='unresolved'):
                with patch(
                    'backend.storage.outcome_resolver.format_outcome_resolver_status_lines',
                    return_value=['Outcome resolver active — awaiting eligible close/reference price data.'],
                ):
                    text = run_memory_only().get('text') or ''

    if 'not active yet' in text.lower():
        return _fail('/memory must not say not active yet when resolver exists')
    if 'Outcome resolver active — awaiting eligible close/reference price data.' not in text:
        return _fail('/memory missing resolver active awaiting message')
    if 'Outcomes resolved: 0' not in text:
        return _fail('/memory missing Outcomes resolved: 0')
    if 'Pending resolution: 190' not in text:
        return _fail('/memory missing pending count')
    if 'Do not trust win-rate/calibration until outcomes resolve.' not in text:
        return _fail('/memory missing calibration trust warning')

    print('MEMORY_RESOLVER_ACTIVE_ZERO_RESOLVED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
