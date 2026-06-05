#!/usr/bin/env python3
"""Unit tests for /memory outcome clarity when outcomes=0 (Stage 46J)."""

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
    print(f'MEMORY_OUTCOME_CLARITY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_memory_only

    zero_outcome_dashboard = {
        'ok': True,
        'stats': {'predictions': 12, 'outcomes': 0},
        'learning': {'overall': {'wins': 0, 'losses': 0, 'unresolved_predictions': 12}},
        'latest_outcomes': [],
    }

    with patch('backend.telegram.lazy_command_runner._load_json', return_value=zero_outcome_dashboard):
        result = run_memory_only()
    text = result.get('text') or ''
    if not result.get('ok', True):
        return _fail('run_memory_only failed for zero outcomes')

    for phrase in (
        'Predictions tracked: 12',
        'Outcomes resolved: 0',
        'Pending resolution: 12',
        'Reason: awaiting close-price/outcome resolver or next market session',
        'Source: cloud/runtime cache',
        'None resolved yet',
    ):
        if phrase not in text:
            return _fail(f'missing zero-outcome phrase: {phrase}')

    if 'Win rate:' in text:
        return _fail('zero outcomes should not show win rate line')

    resolved_dashboard = {
        'ok': True,
        'stats': {'predictions': 12, 'outcomes': 8},
        'learning': {'overall': {'wins': 5, 'losses': 3, 'win_rate': 0.625, 'unresolved_predictions': 4}},
        'latest_outcomes': [
            {'ticker': 'INFY', 'resolved_as': 'WIN', 'actual_move': 1.2},
        ],
    }
    with patch('backend.telegram.lazy_command_runner._load_json', return_value=resolved_dashboard):
        resolved = run_memory_only()
    resolved_text = resolved.get('text') or ''
    if 'Predictions tracked:' in resolved_text:
        return _fail('resolved outcomes should use standard summary lines')
    if 'Outcomes: 8' not in resolved_text:
        return _fail('resolved memory missing outcomes count')
    if 'INFY' not in resolved_text:
        return _fail('resolved memory missing latest outcome line')

    print('MEMORY_OUTCOME_CLARITY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
