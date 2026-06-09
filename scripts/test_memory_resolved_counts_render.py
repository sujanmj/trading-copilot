#!/usr/bin/env python3
"""Unit tests — /memory resolved count rendering (Stage 49A)."""

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
    print(f'MEMORY_RESOLVED_COUNTS_RENDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_memory_only

    zero_cache = {
        'ok': True,
        'stats': {'predictions': 12, 'outcomes': 0},
        'learning': {'overall': {'total_predictions': 12, 'resolved_outcomes': 0, 'unresolved_predictions': 12}},
        'latest_outcomes': [],
    }
    warmup_cache = {
        'ok': True,
        'stats': {'predictions': 30, 'outcomes': 8},
        'learning': {'overall': {'total_predictions': 30, 'resolved_outcomes': 8, 'wins': 5, 'losses': 2}},
        'latest_outcomes': [{'ticker': 'ABC', 'resolved_as': 'WIN'}],
    }
    ready_cache = {
        'ok': True,
        'stats': {'predictions': 200, 'outcomes': 25},
        'learning': {'overall': {'total_predictions': 200, 'resolved_outcomes': 25, 'wins': 14, 'losses': 8}},
        'latest_outcomes': [{'ticker': 'XYZ', 'resolved_as': 'LOSS'}],
    }

    sq_warmup = {'resolved': 8, 'pending': 22, 'hit_rate': 0.6, 'bullish_hit_rate': 0.7, 'bearish_hit_rate': 0.4, 'neutral': 1, 'last_resolved_at': '2026-05-27T10:00:00'}
    sq_ready = {'resolved': 25, 'pending': 175, 'hit_rate': 0.56, 'bullish_hit_rate': 0.62, 'bearish_hit_rate': 0.48, 'neutral': 3, 'last_resolved_at': '2026-05-27T11:00:00'}

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / 'market_memory_dashboard_cache.json'
        cache_path.write_text(json.dumps(zero_cache), encoding='utf-8')
        with patch('backend.telegram.lazy_command_runner.MEMORY_CACHE_FILE', cache_path):
            text = run_memory_only().get('text', '')
        if 'Outcomes resolved: 0' not in text:
            return _fail('zero outcomes must keep unresolved warning')
        if 'Calibration warming up' in text:
            return _fail('zero outcomes must not show warmup')

        cache_path.write_text(json.dumps(warmup_cache), encoding='utf-8')
        with patch('backend.telegram.lazy_command_runner.MEMORY_CACHE_FILE', cache_path):
            with patch('backend.storage.outcome_resolver.compute_signal_quality_metrics', return_value=sq_warmup):
                with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='warmup'):
                    text = run_memory_only().get('text', '')
        if 'Calibration warming up — sample too small.' not in text:
            return _fail('warmup sample must show warming up message')
        if 'do not trust yet' not in text.lower():
            return _fail('warmup must warn not to trust hit rate')

        cache_path.write_text(json.dumps(ready_cache), encoding='utf-8')
        with patch('backend.telegram.lazy_command_runner.MEMORY_CACHE_FILE', cache_path):
            with patch('backend.storage.outcome_resolver.compute_signal_quality_metrics', return_value=sq_ready):
                with patch('backend.analytics.unified_decision_engine.get_calibration_mode', return_value='ready'):
                    text = run_memory_only().get('text', '')
        for needle in ('Resolved outcomes: 25', 'Bullish hit rate:', 'Avoid/rejection hit rate:', 'Last resolved:'):
            if needle not in text:
                return _fail(f'ready sample missing {needle!r} in {text[:400]!r}')

    print('MEMORY_RESOLVED_COUNTS_RENDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
