#!/usr/bin/env python3
"""
Test runtime snapshot direction normalization without DB writes.

Usage:
  python scripts/test_runtime_prediction_direction_mapping.py

Prints exactly RUNTIME_DIRECTION_MAPPING_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

CASES = (
    ({'ticker': '__TEST__', 'recommendation': 'BUY'}, 'BULLISH'),
    ({'ticker': '__TEST__', 'action': 'Avoid'}, 'BEARISH'),
    ({'ticker': '__TEST__', 'stance': 'Watch'}, 'NEUTRAL'),
    (
        {'ticker': '__TEST__', 'reasoning': 'breakout with upside momentum'},
        'BULLISH',
    ),
    (
        {'ticker': '__TEST__', 'reasoning': 'breakdown and downside risk'},
        'BEARISH',
    ),
    (
        {
            'ticker': '__TEST__',
            'entry_price': 100,
            'target_price': 110,
            'stop_loss': 95,
        },
        'BULLISH',
    ),
    (
        {
            'ticker': '__TEST__',
            'entry_price': 100,
            'target_price': 90,
            'stop_loss': 105,
        },
        'BEARISH',
    ),
    (
        {
            'ticker': '__TEST__',
            'entry_price': 100,
            'target_price': 100,
        },
        None,
    ),
    (
        {
            'ticker': 'TEXRAIL',
            'entry_price': 118,
            'target_price': 135,
            'stop_loss': 112,
        },
        'BULLISH',
    ),
)


def _fail(msg: str) -> int:
    print(f'RUNTIME_DIRECTION_MAPPING_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.storage.market_memory_capture import normalize_prediction_payload

    for payload, expected in CASES:
        normalized = normalize_prediction_payload(payload)
        if normalized is None:
            return _fail(f'normalization returned None for {payload}')
        actual = normalized.get('direction')
        if actual != expected:
            return _fail(
                f'payload={payload!r} expected direction={expected!r} got {actual!r}'
            )

    print('RUNTIME_DIRECTION_MAPPING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
