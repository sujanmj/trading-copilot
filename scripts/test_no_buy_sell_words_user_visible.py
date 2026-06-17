#!/usr/bin/env python3
"""Stage 50U — user-visible Telegram output must not contain BUY/SELL."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BUY_SELL = re.compile(r'\b(BUY|SELL)\b', re.IGNORECASE)


def _fail(msg: str) -> int:
    print(f'NO_BUY_SELL_WORDS_USER_VISIBLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import format_catalyst_radar_telegram
    from backend.telegram.response_format import user_text_has_naked_buy_sell

    with patch('backend.intelligence.stock_catalyst_radar.get_clean_catalyst_radar', return_value={
        'priority_list': [{
            'ticker': 'GNFC',
            'side': 'BULLISH',
            'catalyst_type': 'ORDER_WIN',
            'freshness_label': 'today',
            'price_display': 'unavailable',
            'volume_display': 'unavailable',
            'priority': 'MEDIUM',
            'trade_status': 'WAIT FOR LIVE DATA',
        }],
    }):
        catalyst_text = format_catalyst_radar_telegram(today_only=False)

    if BUY_SELL.search(catalyst_text):
        return _fail('/catalysts footer or body must not contain BUY or SELL')
    if 'Research only — confirm manually' not in catalyst_text:
        return _fail('/catalysts footer must use research-only confirm wording')
    if user_text_has_naked_buy_sell(catalyst_text):
        return _fail('catalyst output failed user_text_has_naked_buy_sell guard')

    print('NO_BUY_SELL_WORDS_USER_VISIBLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
