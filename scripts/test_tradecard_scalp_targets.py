#!/usr/bin/env python3
"""Stage 50O — scalp targets in 0.8–2.0% range."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_SCALP_TARGETS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.trade_card_engine import _compute_plan

    price = 500.0
    plan = _compute_plan({'price': price, 'change_percent': 1.0, 'volume_ratio': 1.5})
    t1_pct = (plan['target_1'] - price) / price * 100
    t2_pct = (plan['target_2'] - price) / price * 100
    if t1_pct < 0.8 or t1_pct > 1.2:
        return _fail(f'T1 should be 0.8-1.2% got {t1_pct:.2f}%')
    if t2_pct < 1.3 or t2_pct > 2.0:
        return _fail(f'T2 should be 1.3-2.0% got {t2_pct:.2f}%')
    if t1_pct > 5 or t2_pct > 5:
        return _fail('targets must not be 10% scalp style')

    print('TRADECARD_SCALP_TARGETS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
