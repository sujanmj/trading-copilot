#!/usr/bin/env python3
"""Phase 4B.17 — OHLCV candidate capture and derived intraday candles."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
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
    print(f'OHLCV_CANDIDATE_CAPTURE_4B17_FAIL: {msg}', file=sys.stderr)
    return 1


class _CandleEnv:
    def __init__(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / 'intraday_candles.jsonl'

    def __enter__(self) -> Path:
        os.environ['INTRADAY_CANDLES_FILE'] = str(self.path)
        return self.path

    def __exit__(self, *args: object) -> None:
        os.environ.pop('INTRADAY_CANDLES_FILE', None)
        self.tmpdir.cleanup()


def _partial_snapshot(symbol: str, close: float, *, minute: int = 0) -> dict:
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


def test_extract_maps_price_to_close() -> int:
    from backend.trading.ohlcv_candidate_adapter import extract_candidate_ohlcv

    snap = extract_candidate_ohlcv({'ticker': 'METROPOLIS', 'ltp': 1800.5})
    if not snap or snap.get('close') != 1800.5:
        return _fail('ltp/current_price must map to close')
    return 0


def test_does_not_fake_missing_ohlc() -> int:
    from backend.trading.ohlcv_candidate_adapter import extract_candidate_ohlcv

    snap = extract_candidate_ohlcv({'ticker': 'METROPOLIS', 'price': 1800.0})
    if not snap:
        return _fail('expected partial snapshot')
    if any(k in snap for k in ('open', 'high', 'low')):
        return _fail('must not fake open/high/low when missing')
    if snap.get('source_quality') != 'partial':
        return _fail('missing OHLC must be partial')
    return 0


def test_full_candidate_usable() -> int:
    from backend.trading.ohlcv_candidate_adapter import is_usable_ohlcv_snapshot, normalize_ohlcv_snapshot

    snap = normalize_ohlcv_snapshot(
        'METROPOLIS',
        {'price': 1800, 'open': 1790, 'high': 1810, 'low': 1785, 'volume': 12000},
    )
    if snap.get('source_quality') != 'full':
        return _fail('full OHLCV must be full quality')
    if not is_usable_ohlcv_snapshot(snap):
        return _fail('full snapshot must be usable')
    return 0


def test_partial_snapshot_stored_not_pattern_ready_alone() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot, get_candle_readiness

    with _CandleEnv():
        append_candle_snapshot('METROPOLIS', _partial_snapshot('METROPOLIS', 1800.0))
        info = get_candle_readiness('METROPOLIS')
        if int(info.get('snapshot_count') or 0) != 1:
            return _fail('partial snapshot should store')
        if info.get('pattern_ready'):
            return _fail('single partial snapshot must not be pattern-ready')
    return 0


def test_repeated_snapshots_build_derived_candles() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot, build_ohlcv_from_snapshots

    with _CandleEnv():
        for idx in range(6):
            append_candle_snapshot('METROPOLIS', _partial_snapshot('METROPOLIS', 1800 + idx, minute=idx * 5))
        candles = build_ohlcv_from_snapshots('METROPOLIS', timeframe='5m')
        if len(candles) < 5:
            return _fail(f'expected >=5 derived candles got {len(candles)}')
        if not all(c.get('derived_from_snapshots') for c in candles):
            return _fail('partial snapshots should derive candles')
    return 0


def test_candles_command_output() -> int:
    from backend.telegram.lazy_command_runner import run_candles_only
    from backend.trading.intraday_candle_memory import append_candle_snapshot

    with _CandleEnv():
        append_candle_snapshot('METROPOLIS', _partial_snapshot('METROPOLIS', 1800.0))
        text = run_candles_only('METROPOLIS').get('text') or ''
    for needle in ('CANDLES — METROPOLIS', 'Snapshots:', 'Derived candles:', 'Pattern-ready:'):
        if needle not in text:
            return _fail(f'/candles output missing {needle!r}')
    return 0


def test_patterns_not_enough_bars_message() -> int:
    from backend.telegram.lazy_command_runner import run_pattern_only
    from backend.trading.intraday_candle_memory import append_candle_snapshot

    with _CandleEnv():
        append_candle_snapshot('METROPOLIS', _partial_snapshot('METROPOLIS', 1800.0, minute=0))
        append_candle_snapshot('METROPOLIS', _partial_snapshot('METROPOLIS', 1801.0, minute=1))
        text = run_pattern_only('METROPOLIS').get('text') or ''
    if 'not enough bars yet' not in text.lower():
        return _fail('/pattern must say not enough bars when candles < 5')
    if 'Snapshots:' not in text:
        return _fail('/pattern must show snapshot count')
    return 0


def test_patterns_runs_when_enough_derived_candles() -> int:
    from backend.telegram.lazy_command_runner import run_pattern_only
    from backend.trading.intraday_candle_memory import append_candle_snapshot

    with _CandleEnv():
        for idx in range(6):
            append_candle_snapshot('METROPOLIS', _partial_snapshot('METROPOLIS', 1800 + idx, minute=idx * 5))
        text = run_pattern_only('METROPOLIS').get('text') or ''
    if 'No candle snapshots available' in text:
        return _fail('/pattern should not say no snapshots when history exists')
    if 'not enough bars yet' in text.lower():
        return _fail('/pattern should run when derived candles >= 5')
    if 'PATTERN — METROPOLIS' not in text:
        return _fail('/pattern must run pattern header when ready')
    return 0


def test_pattern_alias() -> int:
    from backend.telegram.telegram_analysis_bot import parse_command

    cmd, args = parse_command('/pattern METROPOLIS')
    if cmd != 'pattern' or args.upper() != 'METROPOLIS':
        return _fail('/pattern alias must route to pattern command')
    return 0


def test_radar_candidate_capture() -> int:
    from backend.trading.intraday_candle_memory import capture_snapshot_from_candidate, load_recent_candles

    with _CandleEnv():
        candidate = {
            'ticker': 'METROPOLIS',
            'price': 1800.0,
            'scanner_row': {'volume_ratio': 1.4},
        }
        captured = capture_snapshot_from_candidate(candidate, source='radar')
        if not captured:
            return _fail('radar candidate with price must capture snapshot')
        rows = load_recent_candles('METROPOLIS')
        if not rows:
            return _fail('radar capture must persist snapshot')
    return 0


def test_pattern_alone_not_tradecard_eligible() -> int:
    from backend.trading.chart_patterns import has_live_radar_confirmation

    row = {'pattern_detected': True, 'score': 80, 'state': 'TOP_GAINER_CONFIRM'}
    if has_live_radar_confirmation(row):
        return _fail('pattern alone must not count as live radar confirmation')
    return 0


def test_build_label_51w() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52H' or ASTRAEDGE_BUILD_STAGE != '52H':
        return _fail(f'expected AstraEdge 52H got {ASTRAEDGE_TELEGRAM_BUILD!r}')
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
        test_extract_maps_price_to_close,
        test_does_not_fake_missing_ohlc,
        test_full_candidate_usable,
        test_partial_snapshot_stored_not_pattern_ready_alone,
        test_repeated_snapshots_build_derived_candles,
        test_candles_command_output,
        test_patterns_not_enough_bars_message,
        test_patterns_runs_when_enough_derived_candles,
        test_pattern_alias,
        test_radar_candidate_capture,
        test_pattern_alone_not_tradecard_eligible,
        test_build_label_51w,
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
    print(f'ALL {len(tests)} OHLCV_CANDIDATE_CAPTURE_4B17 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
