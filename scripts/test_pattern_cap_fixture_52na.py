#!/usr/bin/env python3
"""AstraEdge 52N-A — pattern + cap-bucket test fixture cleanup."""

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
    print(f'PATTERN_CAP_FIXTURE_52NA_FAIL: {msg}', file=sys.stderr)
    return 1


def test_live_overlay_bypasses_auto_refresh() -> int:
    from backend.telegram.response_format import _opening_board_for_display
    from scripts.test_board_fixtures import apply_live_board_overlay, quality_ranked_candidate

    board = apply_live_board_overlay({
        'ranked_candidates': [quality_ranked_candidate(ticker='WIPRO', score=72)],
    })
    with patch(
        'backend.trading.live_scanner_autorefresh_guard.prepare_board_for_live_command',
    ) as mock_prepare:
        data = _opening_board_for_display(board, command='tradecards')
        mock_prepare.assert_not_called()
    if data.get('quality_tradecard_blocked'):
        return _fail('live overlay must not block quality tradecards')
    if data.get('scanner_freshness_status') != 'CURRENT':
        return _fail('live overlay must mark scanner CURRENT')
    return 0


def test_tradecards_pattern_and_cap_with_fixture() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from scripts.test_board_fixtures import apply_live_board_overlay, quality_ranked_candidate

    board = apply_live_board_overlay({
        'ranked_candidates': [
            quality_ranked_candidate(
                ticker='WIPRO',
                score=74,
                why=['ascending triangle near breakout'],
                gainer_bucket='large cap',
            ),
        ],
        'time_ist': '09:30',
    })
    with patch('backend.telegram.response_format._persist_tradecards_decision_memory'):
        text = format_tradecards_telegram(board=board)
    if 'ascending triangle' not in text.lower():
        return _fail('pattern phrase missing from tradecards reason')
    if '— Large cap —' not in text:
        return _fail('cap bucket missing from tradecards line')
    if 'NO QUALITY TRADECARD' in text:
        return _fail('quality candidate must render on CURRENT scanner fixture')
    return 0


def test_unknown_cap_requires_quality_score() -> int:
    from backend.telegram.response_format import format_tradecards_telegram
    from scripts.test_board_fixtures import apply_live_board_overlay, quality_ranked_candidate

    board = apply_live_board_overlay({
        'ranked_candidates': [
            quality_ranked_candidate(ticker='MYSTERY', score=62, state='RADAR_ARMED'),
        ],
        'time_ist': '09:20',
    })
    with patch('backend.trading.all_cap_gainers._screener_cap_bucket_exact', return_value=''), \
         patch('backend.telegram.response_format._persist_tradecards_decision_memory'):
        text = format_tradecards_telegram(board=board)
    if 'Unknown cap' not in text:
        return _fail('missing bucket must render Unknown cap for quality candidate')
    return 0


def test_build_board_live_fixture_scores() -> int:
    from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard
    from scripts.test_board_fixtures import apply_live_board_overlay

    def _row(ticker: str, chg: float, price: float) -> dict:
        return {
            'ticker': ticker,
            'change_percent': chg,
            'volume_ratio': 1.1,
            'price': price,
            'open_price': price - 20,
            'vwap': price - 10,
            'direction': 'BULLISH',
            'volume': 200000,
        }

    now = datetime(2026, 7, 1, 9, 25, tzinfo=IST)
    scanner = {
        'session_date': '2026-07-01',
        'top_signals': [
            _row('PERSISTENT', 3.8, 4800),
            _row('COFORGE', 4.5, 5200),
        ],
    }
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        board = apply_live_board_overlay(
            build_opening_rally_board(now=now, catalyst_payload={}, scanner_payload=scanner),
        )
    best, score, _ = pick_best_opening_tradecard(board)
    if not best or score <= 0:
        return _fail('live board fixture must still pick a best tradecard')
    return 0


def test_canonical_build_label() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    return assert_canonical_build(_fail)


def main() -> int:
    tests = (
        test_live_overlay_bypasses_auto_refresh,
        test_tradecards_pattern_and_cap_with_fixture,
        test_unknown_cap_requires_quality_score,
        test_build_board_live_fixture_scores,
        test_canonical_build_label,
    )
    for test in tests:
        err = test()
        if err:
            return err
        print(f'OK: {test.__name__}')
    print('PATTERN_CAP_FIXTURE_52NA_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
