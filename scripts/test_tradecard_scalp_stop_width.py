#!/usr/bin/env python3
"""Stage 50O — scalp stop width blocks VALID_ENTRY."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_SCALP_STOP_WIDTH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.trade_card_engine import SCALP_MAX_SL_PCT, _compute_plan, detect_entry_missed

    row = {'price': 100.0, 'change_percent': 0.5, 'volume_ratio': 2.0}
    plan = _compute_plan(row)
    if plan['sl_pct'] > SCALP_MAX_SL_PCT:
        return _fail(f'scalp plan sl_pct {plan["sl_pct"]} should be <= {SCALP_MAX_SL_PCT}')

    missed, reasons = detect_entry_missed(
        price=100.0,
        change_pct=0.5,
        volume_ratio=2.0,
        sl_pct=1.5,
        risk_reward=2.0,
    )
    if not missed or not any('stop too wide' in r for r in reasons):
        return _fail('sl > 1.2% must trigger entry missed / block valid entry')

    print('TRADECARD_SCALP_STOP_WIDTH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
