#!/usr/bin/env python3
"""Stage 50O — /tradecard explain uses same ticker as /tradecard."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_EXPLAIN_SAME_TICKER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_tradecard_telegram

    fake = {
        'ok': True,
        'ticker': 'IXIGO',
        'status': 'VALID_ENTRY',
        'current_price': 420,
        'entry_zone': '418–422',
        'stop_loss': 416,
        'target_1': 424,
        'target_2': 427,
        'risk_reward': 2.0,
        'capital_plan': 'Paper only',
        'reason': 'setup aligned',
        'invalid_if': 'below 416',
        'exit_rule': 'trim T1',
        'confidence': 'MEDIUM',
        'paper_only': True,
        'session_date': '2026-05-27',
        'generated_at': '2026-05-27T10:00:00+05:30',
    }
    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('IXIGO', 'VALID_ENTRY')):
        normal = format_tradecard_telegram(explain=False)
        explain = format_tradecard_telegram(explain=True)

    if 'IXIGO' not in normal or 'IXIGO' not in explain:
        return _fail('both outputs must include IXIGO')
    if normal.count('IXIGO') >= 1 and explain.count('IXIGO') >= 1:
        pass
    else:
        return _fail('ticker mismatch between normal and explain')

    print('TRADECARD_EXPLAIN_SAME_TICKER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
