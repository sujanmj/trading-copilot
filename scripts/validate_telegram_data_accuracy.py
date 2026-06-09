#!/usr/bin/env python3
"""
Validate Telegram data accuracy wiring (Stage 45B4).

Prints TELEGRAM_DATA_ACCURACY_OK on success.
Marker: TELEGRAM_STAGE_45B4_DATA_ACCURACY_ACTION_PLAN
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

MARKER = 'TELEGRAM_STAGE_45B4_DATA_ACCURACY_ACTION_PLAN'


def _fail(msg: str) -> int:
    print(f'TELEGRAM_DATA_ACCURACY_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    fmt_path = PROJECT_ROOT / 'backend' / 'telegram' / 'response_format.py'
    lazy_path = PROJECT_ROOT / 'backend' / 'telegram' / 'lazy_command_runner.py'
    broker_path = PROJECT_ROOT / 'backend' / 'analytics' / 'broker_prediction_intelligence.py'
    aihub_path = PROJECT_ROOT / 'backend' / 'analytics' / 'aihub_tab_payloads.py'
    test_path = PROJECT_ROOT / 'scripts' / 'test_telegram_data_accuracy.py'

    for path in (fmt_path, lazy_path, broker_path, aihub_path, test_path):
        if not path.is_file():
            return _fail(f'missing file: {path.relative_to(PROJECT_ROOT)}')

    fmt_src = fmt_path.read_text(encoding='utf-8')
    lazy_src = lazy_path.read_text(encoding='utf-8')
    broker_src = broker_path.read_text(encoding='utf-8')
    aihub_src = aihub_path.read_text(encoding='utf-8')

    required_symbols = (
        ('format_memory_win_rate', fmt_src),
        ('format_memory_outcome_line', fmt_src),
        ('format_cache_age_label', fmt_src),
        ('resolve_global_risk_text', fmt_src),
        ('DATA_ACCURACY_STAGE_MARKER', fmt_src),
        ('get_top_broker_display_candidates', broker_src),
        ('_derive_global_risk_summary', aihub_src),
        ("'global_risk': global_risk", aihub_src),
        ('format_memory_outcome_line', lazy_src),
        ('get_top_broker_display_candidates', lazy_src),
    )
    for symbol, src in required_symbols:
        if symbol not in src:
            return _fail(f'missing symbol: {symbol}')

    if MARKER not in fmt_src:
        return _fail(f'response_format missing marker {MARKER}')

    from backend.metrics.canonical_metrics import format_win_rate_display
    from backend.telegram.response_format import (
        DATA_ACCURACY_STAGE_MARKER,
        format_cache_age_label,
        format_memory_outcome_line,
        format_memory_win_rate,
        resolve_global_risk_text,
    )

    if DATA_ACCURACY_STAGE_MARKER != MARKER:
        return _fail('DATA_ACCURACY_STAGE_MARKER mismatch')

    wr = format_win_rate_display(8, 16, min_sample=1)
    if wr.get('win_rate_display') != '33.3%':
        return _fail(f'expected 33.3% win rate display, got {wr.get("win_rate_display")!r}')

    overall_wr = format_memory_win_rate({'wins': 8, 'losses': 16, 'win_rate': 0.3333})
    if overall_wr != '33.3%':
        return _fail(f'format_memory_win_rate expected 33.3%, got {overall_wr!r}')

    outcome = format_memory_outcome_line(
        {'ticker': 'TEXRAIL', 'resolved_as': 'LOSS', 'actual_move': -11.550847457627114}
    )
    if 'TEXRAIL — LOSS — -11.55%' not in outcome:
        return _fail(f'unexpected outcome line: {outcome!r}')

    fresh = format_cache_age_label(15)
    if fresh != 'fresh · 15m':
        return _fail(f'expected fresh · 15m, got {fresh!r}')

    mid = format_cache_age_label(120)
    if mid != 'stale · 2h':
        return _fail(f'expected stale · 2h, got {mid!r}')

    old = format_cache_age_label(4379, timestamp='2026-06-01T08:00:00+00:00')
    if '4379m' in old:
        return _fail('cache age formatter must not emit huge minute values')
    if not old.startswith('stale ·'):
        return _fail(f'cache age formatter must use stale label for old caches, got {old!r}')

    risk = resolve_global_risk_text({'summary': {}, 'items': []})
    if risk in ('—', '-', ''):
        return _fail('resolve_global_risk_text must never return empty dash')

    print(MARKER)
    print('TELEGRAM_DATA_ACCURACY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
