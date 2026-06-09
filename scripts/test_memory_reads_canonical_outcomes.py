#!/usr/bin/env python3
"""Unit tests — /memory reads canonical outcome store (Stage 49D)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'MEMORY_READS_CANONICAL_OUTCOMES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_memory_only

    stale_cache = {
        'ok': True,
        'stats': {'predictions': 210, 'outcomes': 0},
        'learning': {'overall': {'total_predictions': 210, 'resolved_outcomes': 0, 'unresolved_predictions': 210}},
        'latest_outcomes': [],
    }
    canonical = {
        'data_root': '/app/data',
        'predictions_tracked': 177,
        'resolved_total': 114,
        'pending_total': 63,
        'hit_rate': 0.56,
        'bullish_hit_rate': 0.62,
        'bearish_hit_rate': 0.48,
        'neutral': 2,
        'last_resolved_at': '2026-06-09T15:30:00+00:00',
    }

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / 'market_memory_dashboard_cache.json'
        cache_path.write_text(json.dumps(stale_cache), encoding='utf-8')
        with patch('backend.telegram.lazy_command_runner.MEMORY_CACHE_FILE', cache_path):
            with patch('backend.storage.outcome_resolver.get_canonical_outcome_stats', return_value=canonical):
                with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='ready'):
                    text = run_memory_only().get('text', '')

    if 'Outcomes resolved: 0' in text:
        return _fail('/memory must not show 0 when canonical resolved_total=114')
    if 'Resolved outcomes: 114' not in text:
        return _fail('/memory must show canonical resolved_total=114')
    if 'Pending outcomes: 63' not in text:
        return _fail('/memory must show canonical pending_total=63')
    if 'Predictions tracked: 177' not in text:
        return _fail('/memory must show canonical predictions_tracked=177')

    print('MEMORY_READS_CANONICAL_OUTCOMES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
