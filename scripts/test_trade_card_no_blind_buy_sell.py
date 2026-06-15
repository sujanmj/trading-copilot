#!/usr/bin/env python3
"""Stage 50L — trade card output must not contain blind BUY/SELL or guaranteed language."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FORBIDDEN = re.compile(r'\b(guaranteed|99%|sure win|blind buy|blind sell)\b', re.IGNORECASE)
NAKED_BUY_SELL = re.compile(r'\bAction:\s*(BUY|SELL)\b', re.IGNORECASE)


def _fail(msg: str) -> int:
    print(f'TRADE_CARD_NO_BLIND_BUY_SELL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_intraday_anomaly_alert, format_tradecard_telegram

    fake_card = {
        'ok': True,
        'ticker': 'IXIGO',
        'status': 'VALID_ENTRY',
        'current_price': 420,
        'entry_zone': '418–422',
        'stop_loss': 410,
        'target_1': 430,
        'target_2': 440,
        'risk_reward': 2.1,
        'capital_plan': 'Paper only — manual entry if confirmed',
        'reason': 'Watch for confirmation',
        'invalid_if': 'Below 410',
        'exit_rule': 'Trim at T1',
        'confidence': 'MEDIUM',
        'paper_only': True,
    }
    with patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card):
        text = format_tradecard_telegram(explain=True)

    if FORBIDDEN.search(text):
        return _fail('tradecard contains forbidden guaranteed language')
    if NAKED_BUY_SELL.search(text):
        return _fail('tradecard contains naked BUY/SELL action')

    alert = format_intraday_anomaly_alert(
        {'ticker': 'IXIGO', 'change_percent': 3.2, 'volume_ratio': 1.5, 'direction': 'BULLISH'},
        confidence=0.7,
    )
    if NAKED_BUY_SELL.search(alert):
        return _fail('intraday alert contains naked BUY/SELL')

    engine_src = (PROJECT_ROOT / 'backend/trading/trade_card_engine.py').read_text(encoding='utf-8')
    if 'PAPER_ONLY = True' not in engine_src:
        return _fail('trade_card_engine must keep PAPER_ONLY true')

    print('TRADE_CARD_NO_BLIND_BUY_SELL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
