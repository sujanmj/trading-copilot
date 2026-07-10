#!/usr/bin/env python3
"""Phase 4B.17A — Pattern board commands and denser candidate snapshots."""

from __future__ import annotations

import os
import subprocess
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
    print(f'PATTERN_BOARD_4B17A_FAIL: {msg}', file=sys.stderr)
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


def _candidate(ticker: str, *, score: int = 50, rank: int = 1) -> dict:
    return {
        'ticker': ticker,
        'score': score,
        'state': 'TOP_GAINER_CONFIRM',
        'gainer_bucket': 'large cap',
        'price': 100.0 + rank,
        'volume_ratio': 1.3,
        'scanner_row': {'price': 100.0 + rank, 'volume_ratio': 1.3},
    }


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


def _mock_universe(candidates: list[dict]) -> None:
    board = {'ranked_candidates': candidates, 'market_lifecycle': 'MARKET_ACTIVE', 'data_status': 'current'}
    patchers = [
        patch('backend.trading.pattern_board.get_tradecard_pattern_universe', return_value=(candidates, board, 'tradecards')),
        patch('backend.trading.pattern_board.refresh_board_snapshots', return_value=0),
    ]
    return patchers


def test_patterns_board_no_symbol() -> int:
    from backend.telegram.lazy_command_runner import run_patterns_only

    candidates = [_candidate('TEXRAIL', score=53, rank=1), _candidate('METROPOLIS', score=50, rank=2)]
    with _Env(), patch('backend.trading.pattern_board.get_tradecard_pattern_universe', return_value=(candidates, {}, 'tradecards')), \
         patch('backend.trading.pattern_board.refresh_board_snapshots', return_value=0), \
         patch('backend.trading.pattern_board._analyze_candidate', side_effect=lambda row, rank: {
             'symbol': row['ticker'], 'cap_bucket': 'Large cap', 'tradecard_rank': rank,
             'tradecard_score': row['score'], 'snapshots_count': 10, 'derived_candles_count': 6,
             'pattern_ready': True, 'best_pattern': {'label': 'Ascending triangle', 'status': 'near_breakout'},
             'pattern_status': 'near_breakout', 'breakout_level': 182.4, 'risk_flags': ['breakout not confirmed'],
         }):
        text = run_patterns_only('').get('text') or ''
    if 'PATTERNS — TRADECARD TOP 10' not in text:
        return _fail('/patterns board missing header')
    if 'TEXRAIL' not in text:
        return _fail('/patterns board must list candidates')
    return 0


def test_pattern_best_pick() -> int:
    from backend.telegram.lazy_command_runner import run_pattern_only

    board = {
        'entries': [
            {'symbol': 'TEXRAIL', 'cap_bucket': 'Small cap', 'pattern_ready': True, 'derived_candles_count': 7,
             'best_pattern': {'label': 'Ascending triangle', 'status': 'near_breakout'},
             'pattern_status': 'near_breakout', 'breakout_level': 182.4, 'risk_flags': ['breakout not confirmed'], 'pattern_score': 90, 'tradecard_rank': 3},
            {'symbol': 'METROPOLIS', 'cap_bucket': 'Mid cap', 'pattern_ready': False, 'derived_candles_count': 4},
        ],
        'scanned_count': 2,
    }
    pick = {'pick': board['entries'][0], 'valid': True, 'scanned_count': 2}
    with patch('backend.trading.pattern_board.build_pattern_board', return_value=board), \
         patch('backend.trading.pattern_board.select_best_pattern_candidate', return_value=pick):
        text = run_pattern_only('').get('text') or ''
    if 'PATTERN — BEST FROM TRADECARD TOP 10' not in text:
        return _fail('missing best pick header')
    if 'TEXRAIL' not in text:
        return _fail('best pick must name TEXRAIL')
    return 0


def test_pattern_no_valid_shows_closest() -> int:
    from backend.trading.pattern_board import format_single_pattern_pick, select_best_pattern_candidate

    board = {
        'entries': [
            {'symbol': 'METROPOLIS', 'derived_candles_count': 4, 'pattern_ready': False, 'tradecard_rank': 1},
            {'symbol': 'TEXRAIL', 'derived_candles_count': 3, 'pattern_ready': False, 'tradecard_rank': 2},
        ],
        'scanned_count': 2,
    }
    pick = select_best_pattern_candidate(board)
    text = format_single_pattern_pick(pick)
    if 'NO VALID ACTIVE PATTERN' not in text:
        return _fail('must not fake valid pattern')
    if 'METROPOLIS' not in text or 'TEXRAIL' not in text:
        return _fail('must show closest candidates')
    return 0


def test_patterns_symbol_guidance() -> int:
    from backend.telegram.lazy_command_runner import run_patterns_only

    text = run_patterns_only('METROPOLIS').get('text') or ''
    if 'For a single stock, use: /pattern SYMBOL' not in text:
        return _fail('/patterns SYMBOL must guide to /pattern SYMBOL')
    if '/pattern METROPOLIS' not in text:
        return _fail('/patterns SYMBOL must show /pattern example')
    if 'PATTERN — METROPOLIS' in text:
        return _fail('/patterns SYMBOL must not run duplicate pattern check')
    return 0


def test_pattern_symbol_custom() -> int:
    from backend.telegram.lazy_command_runner import run_pattern_only

    with patch('backend.telegram.response_format.format_patterns_telegram', return_value='PATTERN — WIPRO'):
        text = run_pattern_only('WIPRO').get('text') or ''
    if 'WIPRO' not in text:
        return _fail('/pattern SYMBOL must use custom symbol formatter')
    return 0


def test_pattern_symbol_alias() -> int:
    from backend.telegram.telegram_analysis_bot import parse_command

    cmd, args = parse_command('/pattern METROPOLIS')
    if cmd != 'pattern' or args.upper() != 'METROPOLIS':
        return _fail('/pattern SYMBOL must route to pattern command')
    return 0


def test_board_does_not_scan_all_stocks() -> int:
    from backend.trading import pattern_board

    src = (PROJECT_ROOT / 'backend/trading/pattern_board.py').read_text(encoding='utf-8')
    if 'scan_all_market' in src:
        return _fail('pattern board must not scan all market')
    with patch('backend.trading.opening_rally_radar.build_opening_rally_board') as mock_board:
        mock_board.return_value = {'ranked_candidates': [_candidate('AAA')]}
        candidates, _, source = pattern_board.get_tradecard_pattern_universe(limit=10)
        if not candidates or mock_board.call_count != 1:
            return _fail('universe must come from tradecards board')
        if source != 'tradecards':
            return _fail(f'unexpected source {source!r}')
    return 0


def test_not_ready_reason() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot
    from backend.trading.pattern_board import _analyze_candidate

    with _Env():
        append_candle_snapshot('METROPOLIS', _partial('METROPOLIS', 1800, 0))
        append_candle_snapshot('METROPOLIS', _partial('METROPOLIS', 1801, 1))
        entry = _analyze_candidate(_candidate('METROPOLIS'), rank=1)
    if entry.get('pattern_ready'):
        return _fail('insufficient candles must not be ready')
    if int(entry.get('derived_candles_count') or 0) >= 5:
        return _fail('test setup must have <5 derived candles')
    if '5' not in str(entry.get('reason') or ''):
        return _fail('not-ready reason must mention minimum candles')
    return 0


def test_detect_when_ready() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot
    from backend.trading.pattern_board import _analyze_candidate

    with _Env():
        for i in range(6):
            append_candle_snapshot('TEXRAIL', _partial('TEXRAIL', 180 + i, i * 5))
        with patch('backend.trading.chart_patterns.detect_chart_patterns', return_value={
            'best_pattern': {'label': 'Ascending triangle', 'status': 'near_breakout', 'confidence': 70, 'pattern': 'ascending_triangle'},
        }):
            entry = _analyze_candidate(_candidate('TEXRAIL'), rank=1)
    if not entry.get('pattern_ready'):
        return _fail('expected pattern-ready with >=5 derived candles')
    if not entry.get('best_pattern'):
        return _fail('ready candidate must run detect_chart_patterns')
    return 0


def test_tie_break_pattern_score_then_rank() -> int:
    from backend.trading.pattern_board import select_best_pattern_candidate

    board = {
        'entries': [
            {'symbol': 'LOW', 'pattern_ready': True, 'best_pattern': {'pattern': 'ascending_triangle', 'status': 'forming', 'confidence': 60},
             'pattern_score': 74, 'tradecard_rank': 5, 'derived_candles_count': 6},
            {'symbol': 'HIGH', 'pattern_ready': True, 'best_pattern': {'pattern': 'ascending_triangle', 'status': 'near_breakout', 'confidence': 80},
             'pattern_score': 98, 'tradecard_rank': 2, 'derived_candles_count': 7},
        ],
        'scanned_count': 2,
    }
    pick = select_best_pattern_candidate(board)
    if not pick.get('valid'):
        return _fail('expected valid pick')
    if pick['pick'].get('symbol') != 'HIGH':
        return _fail('must tie-break by higher pattern score')
    return 0


def test_intraday_alert_snapshot() -> int:
    from backend.trading.intraday_candle_memory import capture_snapshot_from_alert_signal, load_recent_candles

    with _Env():
        ev = {'signal': {'ticker': 'METROPOLIS', 'price': 1800.0, 'change_percent': 2.1}}
        if not capture_snapshot_from_alert_signal(ev):
            return _fail('intraday alert must capture snapshot')
        rows = load_recent_candles('METROPOLIS')
        if not rows:
            return _fail('alert snapshot must persist')
    return 0


def test_intraday_batch_snapshots() -> int:
    from backend.trading.intraday_candle_memory import capture_intraday_batch_snapshots, load_recent_candles

    with _Env():
        partition = {
            'new': [{'signal': {'ticker': 'TEXRAIL', 'price': 182.0}}],
            'changed': [{'signal': {'ticker': 'METROPOLIS', 'price': 1800.0}}],
        }
        count = capture_intraday_batch_snapshots(partition)
        if count < 2:
            return _fail('batch path must capture multiple snapshots')
        if not load_recent_candles('TEXRAIL') or not load_recent_candles('METROPOLIS'):
            return _fail('batch snapshots must persist')
    return 0


def test_patterns_board_refreshes_snapshots() -> int:
    from backend.trading.pattern_board import build_pattern_board

    candidates = [_candidate('AAA'), _candidate('BBB', rank=2)]
    with patch('backend.trading.pattern_board.get_tradecard_pattern_universe', return_value=(candidates, {}, 'tradecards')), \
         patch('backend.trading.pattern_board.refresh_board_snapshots') as mock_refresh, \
         patch('backend.trading.pattern_board._analyze_candidate', side_effect=lambda row, rank: {'symbol': row['ticker'], 'tradecard_rank': rank}):
        build_pattern_board(refresh_snapshots=True)
        if not mock_refresh.called:
            return _fail('pattern board must refresh snapshots')
    return 0


def test_min_readiness_still_five() -> int:
    from backend.trading.intraday_candle_memory import MIN_DERIVED_CANDLES

    if MIN_DERIVED_CANDLES != 5:
        return _fail('minimum derived candles must remain 5')
    return 0


def test_help_chart_patterns_section() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    for needle in (
        '/patterns — scan chart patterns for /tradecards top 10',
        '/pattern — best chart-pattern candidate from /tradecards top 10',
        '/pattern SYMBOL — check chart pattern for one stock',
        '/candles SYMBOL — debug candle snapshots and pattern readiness',
    ):
        if needle not in HELP_TEXT:
            return _fail(f'help missing {needle!r}')
    if '/patterns SYMBOL' in HELP_TEXT:
        return _fail('help must not list duplicate /patterns SYMBOL')
    return 0


def test_build_label_51x() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52M' or ASTRAEDGE_BUILD_STAGE != '52M':
        return _fail(f'expected AstraEdge 52M got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def _run_script(name: str) -> int:
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / name)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return _fail(f'{name} failed with code {proc.returncode}')
    return 0


def test_regression_prior_phases() -> int:
    from backend.qa.smoke_mode import should_skip_nested_regression

    if should_skip_nested_regression():
        print('SKIP: test_regression_prior_phases (ASTRAEDGE_QA_SMOKE=1)')
        return 0
    for script in (
        'test_ohlcv_candidate_capture_4b17.py',
        'test_qa_command_4b16.py',
        'test_help_chart_patterns_4b15b.py',
        'test_intraday_candle_memory_4b15a.py',
        'test_chart_patterns_4b15.py',
    ):
        rc = _run_script(script)
        if rc:
            return rc
    return 0


def main() -> int:
    tests = [
        test_patterns_board_no_symbol,
        test_pattern_best_pick,
        test_pattern_no_valid_shows_closest,
        test_patterns_symbol_guidance,
        test_pattern_symbol_custom,
        test_pattern_symbol_alias,
        test_board_does_not_scan_all_stocks,
        test_not_ready_reason,
        test_detect_when_ready,
        test_tie_break_pattern_score_then_rank,
        test_intraday_alert_snapshot,
        test_intraday_batch_snapshots,
        test_patterns_board_refreshes_snapshots,
        test_min_readiness_still_five,
        test_help_chart_patterns_section,
        test_build_label_51x,
        test_regression_prior_phases,
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
    print(f'ALL {len(tests)} PATTERN_BOARD_4B17A TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
