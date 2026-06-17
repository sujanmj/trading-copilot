#!/usr/bin/env python3
"""Stage 50T — Telegram decision surfaces must not use BUY/SELL wording."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'NO_BUY_SELL_WORDING_GLOBAL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_action_plan_telegram, user_text_has_naked_buy_sell

    with patch('backend.analytics.stock_decision_engine.build_stock_decision', return_value={
        'ok': True,
        'decision': 'WATCH_FOR_ENTRY',
        'top_pick': {'ticker': 'SUNDRMFAST', 'action': 'WATCH_FOR_ENTRY', 'score': 70, 'confidence': 'MEDIUM', 'why': ['scanner']},
        'ranked_candidates': [],
        'avoid': [],
    }), patch('backend.analytics.railway_decision_bootstrap.repair_decision_for_telegram', return_value=({}, False, False)), \
         patch('backend.analytics.railway_decision_bootstrap.load_cached_stock_decision', return_value=None), \
         patch('backend.analytics.aihub_tab_payloads.build_brain_payload', return_value={'ok': True, 'actionable_candidates': {}}), \
         patch('backend.analytics.aihub_tab_payloads.build_market_payload', return_value={'ok': True}), \
         patch('backend.analytics.aihub_tab_payloads.build_global_payload', return_value={'ok': True}), \
         patch('backend.telegram.lazy_command_runner._load_json', return_value={}), \
         patch('backend.telegram.lazy_command_runner.DAILY_PACK_FILE', PROJECT_ROOT / 'data' / 'daily_report_pack.json'):
        text = format_action_plan_telegram()

    if 'No confirmed BUY candidate' in text:
        return _fail('/action plan still contains BUY candidate wording')
    if user_text_has_naked_buy_sell(text):
        return _fail('/action plan contains forbidden BUY/SELL wording')
    if 'No confirmed entry candidate' not in text and 'ENTRY CANDIDATE' not in text and 'Ticker:' not in text:
        return _fail('/action plan missing safe candidate wording')

    from backend.trading.unified_live_priority_engine import format_today_unified, user_action_label

    if user_action_label('BUY_CANDIDATE') != 'ENTRY CANDIDATE':
        return _fail('user_action_label must map BUY_CANDIDATE to ENTRY CANDIDATE')

    payload = {
        'decision': 'BUY_CANDIDATE',
        'top_pick': {'ticker': 'SUNDRMFAST', 'action': 'BUY_CANDIDATE', 'unified_score': 80, 'why': [], 'risk': []},
        'ranked_candidates': [],
    }
    with patch('backend.trading.unified_live_priority_engine._is_postmarket_mode', return_value=False), \
         patch('backend.trading.unified_live_priority_engine.decision_source_label', return_value='Source: scanner-confirmed'):
        today = format_today_unified(payload)
    if user_text_has_naked_buy_sell(today):
        return _fail('/today unified text contains BUY/SELL wording')
    if 'BUY CANDIDATE' in today:
        return _fail('/today must not show BUY CANDIDATE label')

    print('NO_BUY_SELL_WORDING_GLOBAL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
