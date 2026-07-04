#!/usr/bin/env python3
"""Phase 4B.8 — /tradecard evidence matrix includes opening radar / all-cap gainer context."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')


def _fail(msg: str) -> int:
    print(f'TRADECARD_OPENING_EVIDENCE_4B8_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 4, hour, minute, tzinfo=IST)


def _persistent_board_row() -> dict:
    return {
        'ticker': 'PERSISTENT',
        'state': 'TOP_GAINER_CONFIRM',
        'score': 72,
        'why': [
            'top large cap gainer',
            'it digital india theme',
            'above open',
            'above VWAP',
            'IT sector breadth confirmation: COFORGE/PERSISTENT',
            'dip-buying rebound',
        ],
        'has_catalyst': False,
        'volume_ratio': 1.1,
        'change_percent': 3.8,
        'gainer_promoted': True,
        'gainer_bucket': 'large cap',
        'gainer_rank': 2,
        'sector_breadth': {'sector': 'IT', 'symbols': ['COFORGE', 'PERSISTENT'], 'boost': 8},
        'previous_mover': True,
        'themes': ['it_digital_india'],
    }


def _persistent_board() -> dict:
    row = _persistent_board_row()
    return {
        'ranked_candidates': [row, {'ticker': 'COFORGE', 'state': 'TOP_GAINER_CONFIRM', 'score': 63, 'why': []}],
        'gainer_scan': {'promoted': ['PERSISTENT', 'COFORGE'], 'total': 2},
        'time_ist': '18:30',
        'phase': 'AFTER',
    }


def _persistent_card() -> dict:
    return {
        'ok': True,
        'ticker': 'PERSISTENT',
        'status': 'NO_ACTIVE_ENTRY',
        'after_hours': True,
        'current_price': 4800,
        'entry_zone': 'NO ACTIVE ENTRY',
        'stop_loss': 4700,
        'target_1': 4900,
        'target_2': 5000,
        'risk_reward': 1.5,
        'capital_plan': 'Paper only',
        'reason': 'aligned with /tradecards best pick',
        'invalid_if': 'Below 4700',
        'confidence': 'MEDIUM',
        'paper_only': True,
    }


def test_tradecards_best_persistent_syncs_tradecard() -> int:
    from backend.trading.opening_rally_radar import select_synced_tradecard

    board = _persistent_board()
    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=('PERSISTENT', 72, ['COFORGE'])):
        sync = select_synced_tradecard(legacy_ticker='MAPMYINDIA', board=board)
    if sync.get('selected') != 'PERSISTENT':
        return _fail(f'/tradecard sync must select PERSISTENT got {sync.get("selected")!r}')
    if sync.get('tradecards_best') != 'PERSISTENT':
        return _fail(f'tradecards_best must be PERSISTENT got {sync.get("tradecards_best")!r}')
    return 0


def test_evidence_includes_all_cap_gainer_and_breadth() -> int:
    from backend.trading.tradecard_evidence import build_tradecard_evidence_matrix

    opening = {
        'ticker': 'PERSISTENT',
        'board_row': _persistent_board_row(),
        'why': _persistent_board_row()['why'],
        'gainer_promoted': True,
        'gainer_bucket': 'large cap',
        'gainer_rank': 2,
        'sector_breadth': {'sector': 'IT', 'symbols': ['COFORGE', 'PERSISTENT'], 'boost': 8},
        'previous_mover': True,
        'themes': ['it_digital_india'],
        'tradecards_best': True,
        'from_board': True,
    }
    context = {
        'scanner': {
            'top_signals': [{
                'ticker': 'PERSISTENT',
                'change_percent': 3.8,
                'volume_ratio': 1.1,
                'direction': 'BULLISH',
            }],
        },
        'opening_radar': opening,
        'market_mode': 'AFTER_HOURS',
    }
    matrix = build_tradecard_evidence_matrix('PERSISTENT', context=context)
    direct_modules = {str(i.get('module')) for i in (matrix.get('direct_confirms') or [])}
    indirect_modules = {str(i.get('module')) for i in (matrix.get('indirect_confirms') or [])}
    if 'all_cap_gainer' not in direct_modules:
        return _fail(f'direct confirms must include all_cap_gainer got {direct_modules}')
    if 'sector_breadth' not in direct_modules:
        return _fail(f'direct confirms must include sector_breadth got {direct_modules}')
    if 'previous_session_mover' not in indirect_modules:
        return _fail(f'indirect confirms must include previous_session_mover got {indirect_modules}')
    if 'dip_buying_rebound' not in indirect_modules:
        return _fail(f'indirect confirms must include dip_buying_rebound got {indirect_modules}')
    final = str(matrix.get('final_reason') or '').lower()
    if 'all-cap gainer strength' not in final and 'top ranked watch candidate' not in final:
        return _fail(f'final reason must explain tradecards selection got {final!r}')
    return 0


def test_after_hours_next_session_watch_no_active_entry() -> int:
    from backend.telegram.response_format import format_tradecard_telegram
    from backend.trading.tradecard_evidence import build_tradecard_evidence_matrix

    opening = {
        'ticker': 'PERSISTENT',
        'board_row': _persistent_board_row(),
        'why': _persistent_board_row()['why'],
        'gainer_promoted': True,
        'sector_breadth': {'sector': 'IT', 'symbols': ['COFORGE', 'PERSISTENT'], 'boost': 8},
        'tradecards_best': True,
        'from_board': True,
    }
    matrix = build_tradecard_evidence_matrix(
        'PERSISTENT',
        context={
            'scanner': {'top_signals': [{'ticker': 'PERSISTENT', 'change_percent': 3.8, 'volume_ratio': 1.1}]},
            'opening_radar': opening,
            'market_mode': 'AFTER_HOURS',
        },
    )
    if matrix.get('decision') != 'NEXT-SESSION WATCH':
        return _fail(f'after-hours strong opening context must be NEXT-SESSION WATCH got {matrix.get("decision")!r}')

    board = _persistent_board()
    card = _persistent_card()
    card['_opening_radar_context'] = opening
    with patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value={
        'selected': 'PERSISTENT',
        'tradecards_best': 'PERSISTENT',
        'board': board,
        'reason': 'aligned with /tradecards best pick',
        'status_override': '',
    }), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value='Market closed/after-hours'):
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='4b8-test')
    upper = text.upper()
    if 'NO ACTIVE ENTRY' not in upper and 'NEXT-SESSION WATCH' not in upper:
        return _fail('/tradecard after-hours must show NO ACTIVE ENTRY or NEXT-SESSION WATCH')
    if 'VALID_ENTRY' in upper and 'NO VALID' not in upper:
        return _fail('/tradecard after-hours must not create active entry')
    if 'all-cap top gainer' not in text.lower() and 'all_cap_gainer' not in text.lower():
        return _fail('/tradecard evidence must mention all-cap top gainer')
    return 0


def test_no_stale_unrelated_symbol_selected() -> int:
    from backend.telegram.response_format import format_tradecard_telegram

    board = _persistent_board()
    card = _persistent_card()
    with patch('backend.trading.opening_rally_radar.select_synced_tradecard', return_value={
        'selected': 'PERSISTENT',
        'tradecards_best': 'PERSISTENT',
        'board': board,
        'reason': 'aligned with /tradecards best pick',
    }), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value={
             'ok': True,
             'ticker': 'MAPMYINDIA',
             'status': 'NO_TRADE',
             'reason': 'legacy',
             'paper_only': True,
         }), \
         patch('backend.trading.trade_card_engine.build_trade_card', return_value=card), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.trading.tradecard_refresh.is_tradecard_data_stale', return_value=False), \
         patch('backend.trading.tradecard_refresh.refresh_tradecard_market_data', return_value={}), \
         patch('backend.telegram.response_format._tradecard_postmarket_line', return_value=''):
        text = format_tradecard_telegram(explain=False, freshness_meta={}, chat_id='4b8-stale')
    if 'MAPMYINDIA' in text:
        return _fail('/tradecard must not keep stale unrelated MAPMYINDIA when PERSISTENT is tradecards best')
    if 'PERSISTENT' not in text:
        return _fail('/tradecard must show PERSISTENT from tradecards sync')
    return 0


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51O':
        return _fail(f'expected AstraEdge 51O got {ASTRAEDGE_TELEGRAM_BUILD!r}')

    tests = (
        test_tradecards_best_persistent_syncs_tradecard,
        test_evidence_includes_all_cap_gainer_and_breadth,
        test_after_hours_next_session_watch_no_active_entry,
        test_no_stale_unrelated_symbol_selected,
    )
    for test_fn in tests:
        rc = test_fn()
        if rc:
            return rc
    print('TRADECARD_OPENING_EVIDENCE_4B8_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
