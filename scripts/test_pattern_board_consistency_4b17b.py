#!/usr/bin/env python3
"""Phase 4B.17B — Pattern board consistency, tradecard score preservation, output wording."""

from __future__ import annotations

import os
import sys
import tempfile
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
    print(f'PATTERN_BOARD_4B17B_FAIL: {msg}', file=sys.stderr)
    return 1


class _Env:
    def __init__(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.candle_path = Path(self.tmpdir.name) / 'intraday_candles.jsonl'
        self.heartbeat_path = Path(self.tmpdir.name) / 'candidate_heartbeat.json'

    def __enter__(self) -> tuple[Path, Path]:
        os.environ['INTRADAY_CANDLES_FILE'] = str(self.candle_path)
        os.environ['CANDIDATE_HEARTBEAT_FILE'] = str(self.heartbeat_path)
        return self.candle_path, self.heartbeat_path

    def __exit__(self, *args: object) -> None:
        os.environ.pop('INTRADAY_CANDLES_FILE', None)
        os.environ.pop('CANDIDATE_HEARTBEAT_FILE', None)
        self.tmpdir.cleanup()


def _candidate(ticker: str, *, score: int = 50, rank: int = 1, **extra: object) -> dict:
    row = {
        'ticker': ticker,
        'score': score,
        'tradecard_score': score,
        'tradecard_rank': rank,
        'state': 'TOP_GAINER_CONFIRM',
        'gainer_bucket': 'large cap',
        'price': 100.0 + rank,
        'volume_ratio': 1.3,
        'scanner_row': {'price': 100.0 + rank, 'volume_ratio': 1.3},
    }
    row.update(extra)
    return row


def _partial(symbol: str, close: float, minute: int) -> dict:
    dt = datetime(2026, 7, 6, 9, 15 + minute, tzinfo=IST)
    return {
        'created_at': dt.replace(microsecond=0).isoformat(),
        'session_date': '2026-07-06',
        'symbol': symbol,
        'close': close,
        'source': 'test',
        'timeframe': 'snapshot',
        'source_quality': 'partial',
    }


def test_ready_never_shows_need_five_candles() -> int:
    from backend.trading.pattern_board import build_pattern_board, format_patterns_board

    candidates = [_candidate('GODREJPROP', score=56, rank=8)]
    board = {'ranked_candidates': candidates, 'market_lifecycle': 'MARKET_ACTIVE'}
    with patch('backend.trading.pattern_board.get_tradecard_pattern_universe', return_value=(candidates, board, 'tradecards')), \
         patch('backend.trading.pattern_board.refresh_board_snapshots', return_value=0), \
         patch('backend.trading.pattern_board._analyze_candidate', return_value={
             'symbol': 'GODREJPROP', 'cap_bucket': 'Large cap', 'tradecard_rank': 8,
             'tradecard_score': 56, 'snapshots_count': 30, 'derived_candles_count': 30,
             'pattern_ready': True, 'reason': '', 'best_pattern': None, 'pattern_score': 0,
         }):
        text = format_patterns_board(build_pattern_board(refresh_snapshots=False))
    if 'need at least 5 derived candles' in text.lower():
        return _fail('READY candidate must not show need-at-least-5 reason')
    return 0


def test_not_ready_shows_readiness_reason() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot
    from backend.trading.pattern_board import _analyze_candidate, format_patterns_board

    with _Env():
        append_candle_snapshot('INFY', _partial('INFY', 1500, 0))
        entry = _analyze_candidate(_candidate('INFY', score=62, rank=1), rank=1)
        text = format_patterns_board({'board': {}, 'entries': [entry]})
    if entry.get('pattern_ready'):
        return _fail('expected NOT READY')
    if 'Reason:' not in text:
        return _fail('NOT READY must include Reason line')
    lowered = text.lower()
    if not any(needle in lowered for needle in ('need at least', 'no snapshots', 'candles', 'snapshot')):
        return _fail('NOT READY must show readiness reason')
    return 0


def test_preserves_tradecard_score() -> int:
    from backend.trading.pattern_board import _analyze_candidate

    row = _candidate('HTMEDIA', score=54, rank=4)
    with patch('backend.trading.pattern_board._resolve_best_pattern', return_value={
        'label': 'Descending triangle', 'pattern': 'descending_triangle', 'status': 'forming', 'confidence': 80,
    }), patch('backend.trading.intraday_candle_memory.get_candle_readiness', return_value={
        'pattern_ready': True, 'snapshot_count': 20, 'derived_count': 20, 'reason': '',
    }):
        entry = _analyze_candidate(row, rank=4)
    if int(entry.get('tradecard_score') or 0) != 54:
        return _fail(f'board must preserve tradecard score 54 got {entry.get("tradecard_score")!r}')
    return 0


def test_preserves_tradecard_rank() -> int:
    from backend.trading.pattern_board import _analyze_candidate

    row = _candidate('HTMEDIA', score=54, rank=7)
    with patch('backend.trading.pattern_board._resolve_best_pattern', return_value=None), \
         patch('backend.trading.intraday_candle_memory.get_candle_readiness', return_value={
             'pattern_ready': True, 'snapshot_count': 10, 'derived_count': 10, 'reason': '',
         }):
        entry = _analyze_candidate(row, rank=99)
    if int(entry.get('tradecard_rank') or 0) != 7:
        return _fail(f'board must preserve tradecard rank 7 got {entry.get("tradecard_rank")!r}')
    return 0


def test_existing_ascending_triangle_evidence_displayed() -> int:
    from backend.trading.pattern_board import _analyze_candidate, format_patterns_board

    row = _candidate('GODREJPROP', score=56, rank=8, chart_pattern='Ascending triangle',
                     pattern_status='near_breakout', best_pattern={
                         'label': 'Ascending triangle', 'pattern': 'ascending_triangle',
                         'status': 'near_breakout', 'confidence': 72,
                     })
    with patch('backend.trading.intraday_candle_memory.get_candle_readiness', return_value={
        'pattern_ready': True, 'snapshot_count': 30, 'derived_count': 30, 'reason': '',
    }), patch('backend.trading.pattern_board._resolve_best_pattern', side_effect=lambda *a, **kw: {
        'label': 'Ascending triangle', 'pattern': 'ascending_triangle', 'status': 'near_breakout', 'confidence': 72,
    }):
        entry = _analyze_candidate(row, rank=8)
        text = format_patterns_board({'board': {}, 'entries': [entry]})
    if 'Ascending triangle near breakout' not in text:
        return _fail('board must display existing ascending triangle evidence')
    return 0


def test_pattern_does_not_pick_descending_caution() -> int:
    from backend.trading.pattern_board import select_best_pattern_candidate

    board = {
        'entries': [
            {'symbol': 'CAUT', 'pattern_ready': True, 'derived_candles_count': 10, 'tradecard_rank': 1,
             'best_pattern': {'pattern': 'descending_triangle', 'status': 'forming', 'confidence': 90},
             'pattern_score': 90},
            {'symbol': 'GOOD', 'pattern_ready': True, 'derived_candles_count': 8, 'tradecard_rank': 2,
             'best_pattern': {'pattern': 'ascending_triangle', 'status': 'near_breakout', 'confidence': 70},
             'pattern_score': 88},
        ],
    }
    pick = select_best_pattern_candidate(board)
    if not pick.get('valid'):
        return _fail('expected valid bullish pick')
    if pick['pick'].get('symbol') != 'GOOD':
        return _fail('must not select descending triangle caution as best bullish pattern')
    return 0


def test_closest_ready_no_pattern_label() -> int:
    from backend.trading.pattern_board import format_single_pattern_pick, select_best_pattern_candidate

    board = {
        'entries': [
            {'symbol': 'METROPOLIS', 'pattern_ready': True, 'derived_candles_count': 34,
             'tradecard_rank': 3, 'best_pattern': None},
        ],
    }
    pick = select_best_pattern_candidate(board)
    text = format_single_pattern_pick(pick)
    if 'ready, no active bullish pattern' not in text:
        return _fail('closest must say ready, no active bullish pattern')
    if 'candles 34/5' in text:
        return _fail('closest must not use candles X/5 as primary reason when ready')
    return 0


def test_closest_descending_caution_label() -> int:
    from backend.trading.pattern_board import format_single_pattern_pick, select_best_pattern_candidate

    board = {
        'entries': [
            {'symbol': 'RISK', 'pattern_ready': True, 'derived_candles_count': 12, 'tradecard_rank': 1,
             'best_pattern': {'pattern': 'descending_triangle', 'status': 'forming', 'confidence': 75}},
        ],
    }
    pick = select_best_pattern_candidate(board)
    text = format_single_pattern_pick(pick)
    if 'descending triangle caution' not in text:
        return _fail('closest must show descending triangle caution')
    return 0


def test_ready_no_pattern_board_wording() -> int:
    from backend.trading.pattern_board import format_patterns_board

    entry = {
        'symbol': 'METROPOLIS', 'cap_bucket': 'Mid cap', 'tradecard_rank': 3, 'tradecard_score': 55,
        'snapshots_count': 33, 'derived_candles_count': 33, 'pattern_ready': True, 'reason': '',
        'best_pattern': None, 'pattern_score': 0,
    }
    text = format_patterns_board({'board': {}, 'entries': [entry]})
    if 'Pattern: no active pattern detected' not in text:
        return _fail('ready/no-pattern must show no active pattern detected')
    if 'Reason:' in text:
        return _fail('ready/no-pattern must not show Reason line')
    if 'Tradecard score: 55' not in text:
        return _fail('must show Tradecard score label')
    return 0


def test_build_label_51x() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD
    from backend.trading.pattern_board import STAGE

    if STAGE != '4B.17B':
        return _fail(f'expected STAGE 4B.17B got {STAGE!r}')
    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51Z' or ASTRAEDGE_BUILD_STAGE != '51Z':
        return _fail(f'expected AstraEdge 51Z got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_ready_never_shows_need_five_candles,
        test_not_ready_shows_readiness_reason,
        test_preserves_tradecard_score,
        test_preserves_tradecard_rank,
        test_existing_ascending_triangle_evidence_displayed,
        test_pattern_does_not_pick_descending_caution,
        test_closest_ready_no_pattern_label,
        test_closest_descending_caution_label,
        test_ready_no_pattern_board_wording,
        test_build_label_51x,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print(f'ALL {len(tests)} PATTERN_BOARD_4B17B TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
