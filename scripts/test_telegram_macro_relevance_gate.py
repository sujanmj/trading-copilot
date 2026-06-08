#!/usr/bin/env python3
"""Unit tests for scheduled emergency macro relevance gate (Stage 48G)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_MACRO_RELEVANCE_GATE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_quality_filters import (
        EMERGENCY_STATE_FILE,
        evaluate_emergency_macro,
        is_scheduled_macro_noise,
        record_emergency_macro_sent,
    )

    try:
        if EMERGENCY_STATE_FILE.is_file():
            EMERGENCY_STATE_FILE.unlink()
    except OSError:
        pass

    quote = 'Quote of the day: discipline beats motivation in markets'
    noise, reason = is_scheduled_macro_noise(quote)
    if not noise or reason != 'quote_noise':
        return _fail('quote of the day should be scheduled noise')
    ok_q, reason_q, _ = evaluate_emergency_macro(quote, 0.9, scheduled=True)
    if ok_q:
        return _fail('quote of the day must not pass scheduled gate')

    spacex = 'SpaceX IPO filing sends crypto tokens surging overnight'
    ok_s, reason_s, _ = evaluate_emergency_macro(spacex, 0.88, scheduled=True)
    if ok_s:
        return _fail('SpaceX IPO crypto headline should be suppressed')

    gold = 'Gold price hits record high as silver rallies in global commodity surge'
    ok_g, reason_g, _ = evaluate_emergency_macro(gold, 0.85, scheduled=True)
    if ok_g:
        return _fail('broad commodity without India linkage should be suppressed')

    india_crude = (
        'US-Iran war escalates crude oil shock; India INR and Nifty face import cost surge'
    )
    ok_c, reason_c, theme_c = evaluate_emergency_macro(india_crude, 0.9, scheduled=True)
    if not ok_c:
        return _fail(f'India-linked crude shock should pass scheduled gate, got {reason_c}')
    record_emergency_macro_sent(india_crude, 0.9, theme_c)
    ok_dup, reason_dup, _ = evaluate_emergency_macro(india_crude, 0.91, scheduled=True)
    if ok_dup:
        return _fail('duplicate headline should be suppressed on scheduled path')

    print('TELEGRAM_MACRO_RELEVANCE_GATE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
