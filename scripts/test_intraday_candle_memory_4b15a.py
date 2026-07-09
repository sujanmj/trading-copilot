#!/usr/bin/env python3
"""Phase 4B.15A — Intraday candle memory for chart pattern detection."""

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
    print(f'INTRADAY_CANDLE_MEMORY_4B15A_FAIL: {msg}', file=sys.stderr)
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


def _full_snapshot(symbol: str, close: float, *, minute: int = 0) -> dict:
    dt = datetime(2026, 7, 5, 9, 15 + minute, tzinfo=IST)
    return {
        'created_at': dt.replace(microsecond=0).isoformat(),
        'session_date': '2026-07-05',
        'symbol': symbol,
        'open': close - 1.0,
        'high': close + 1.0,
        'low': close - 2.0,
        'close': close,
        'volume': 1000 + minute * 10,
        'source': 'test',
        'timeframe': 'snapshot',
        'source_quality': 'full',
    }


def test_append_candle_snapshot() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot, load_recent_candles

    with _CandleEnv():
        append_candle_snapshot('WIPRO', _full_snapshot('WIPRO', 180.0))
        rows = load_recent_candles('WIPRO')
        if not rows:
            return _fail('expected stored snapshot')
        if rows[0].get('close') != 180.0:
            return _fail(f'expected close 180 got {rows[0].get("close")!r}')
    return 0


def test_load_recent_candles_symbol_specific() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot, load_recent_candles

    with _CandleEnv():
        append_candle_snapshot('WIPRO', _full_snapshot('WIPRO', 180.0))
        append_candle_snapshot('INFY', _full_snapshot('INFY', 1500.0))
        wipro = load_recent_candles('WIPRO')
        if len(wipro) != 1 or wipro[0].get('symbol') != 'WIPRO':
            return _fail('load_recent_candles must filter by symbol')
    return 0


def test_old_session_ignored_by_date() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot, load_recent_candles

    with _CandleEnv():
        old = _full_snapshot('WIPRO', 170.0)
        old['session_date'] = '2026-06-01'
        append_candle_snapshot('WIPRO', old)
        append_candle_snapshot('WIPRO', _full_snapshot('WIPRO', 180.0))
        today = load_recent_candles('WIPRO', session_date='2026-07-05')
        if len(today) != 1 or today[0].get('close') != 180.0:
            return _fail('session_date filter must ignore old candles')
    return 0


def test_partial_snapshot_no_fake_ohlcv() -> int:
    from backend.trading.intraday_candle_memory import (
        append_candle_snapshot,
        build_ohlcv_from_snapshots,
        quote_snapshot_from_row,
    )

    with _CandleEnv():
        partial = quote_snapshot_from_row('WIPRO', {'price': 180.0}, source='scanner')
        if not partial or partial.get('source_quality') != 'partial':
            return _fail('price-only row must be partial')
        if 'open' in partial or 'high' in partial:
            return _fail('partial snapshot must not fake open/high/low')
        append_candle_snapshot('WIPRO', partial)
        candles = build_ohlcv_from_snapshots('WIPRO', timeframe='snapshot')
        if candles:
            return _fail('partial snapshots must not produce OHLCV candles')
    return 0


def test_build_ohlcv_from_snapshots() -> int:
    from backend.trading.intraday_candle_memory import append_candle_snapshot, build_ohlcv_from_snapshots

    with _CandleEnv():
        for i in range(15):
            append_candle_snapshot('WIPRO', _full_snapshot('WIPRO', 170.0 + i, minute=i))
        candles = build_ohlcv_from_snapshots('WIPRO', timeframe='snapshot')
        if len(candles) < 12:
            return _fail(f'expected >=12 candles got {len(candles)}')
        if candles[-1].get('close') != 184.0:
            return _fail(f'expected last close 184 got {candles[-1].get("close")!r}')
    return 0


def test_patterns_uses_candle_memory() -> int:
    from backend.telegram.response_format import format_patterns_telegram
    from backend.trading.intraday_candle_memory import append_candle_snapshot

    with _CandleEnv():
        for i in range(15):
            append_candle_snapshot('WIPRO', _full_snapshot('WIPRO', 170.0 + i, minute=i))
        text = format_patterns_telegram('WIPRO')
        if 'No candle snapshots available' in text:
            return _fail('patterns must use intraday candle memory when available')
        if 'PATTERN — WIPRO' not in text:
            return _fail(f'unexpected patterns output: {text!r}')
    return 0


def test_patterns_missing_history_message() -> int:
    from backend.telegram.response_format import format_patterns_telegram

    with _CandleEnv():
        text = format_patterns_telegram('WIPRO')
        if 'No candle snapshots available for WIPRO yet' not in text:
            return _fail(f'expected missing history message got {text!r}')
        if '/radar or /tradecards' not in text:
            return _fail('message must mention /radar or /tradecards')
    return 0


def test_pattern_boost_only_with_candles() -> int:
    from backend.trading.chart_patterns import apply_pattern_evidence_to_row
    from scripts.test_chart_patterns_4b15 import _ascending_triangle_candles

    base = {
        'ticker': 'TEST',
        'score': 70,
        'state': 'TRADECARD_CANDIDATE',
        'why': [],
        'volume_ratio': 1.5,
        'has_catalyst': True,
    }
    without = apply_pattern_evidence_to_row(dict(base))
    if without.get('pattern_detected'):
        return _fail('pattern must not attach without candles')

    candles = _ascending_triangle_candles(breakout=True)
    with_candles = apply_pattern_evidence_to_row(dict(base), candles=candles)
    if not with_candles.get('pattern_detected'):
        return _fail('pattern must attach when enough candles exist')
    return 0


def test_pattern_alone_not_tradecard_eligible() -> int:
    from backend.trading.chart_patterns import apply_pattern_evidence_to_row
    from backend.trading.opening_rally_radar import _opening_tradecard_eligible
    from scripts.test_chart_patterns_4b15 import _ascending_triangle_candles

    row = {
        'ticker': 'TEST',
        'score': 70,
        'state': 'TRADECARD_CANDIDATE',
        'why': [],
        'volume_ratio': 0.5,
        'has_catalyst': False,
        'themes': [],
    }
    updated = apply_pattern_evidence_to_row(row, candles=_ascending_triangle_candles(breakout=True))
    updated['pattern_boost'] = 12
    if _opening_tradecard_eligible(updated):
        return _fail('pattern-only boost must not create tradecard eligibility')
    return 0


def test_gitignore_covers_intraday_jsonl() -> int:
    gitignore = (PROJECT_ROOT / '.gitignore').read_text(encoding='utf-8')
    if 'data/intraday_candles.jsonl' not in gitignore:
        return _fail('gitignore must exclude data/intraday_candles.jsonl')
    return 0


def test_build_label_51w() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52G' or ASTRAEDGE_BUILD_STAGE != '52G':
        return _fail(f'expected AstraEdge 52G got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def _run_regression(script: str) -> int:
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return _fail(f'{script} failed with code {proc.returncode}')
    return 0


def test_regression_prior_phases() -> int:
    from backend.qa.smoke_mode import should_skip_nested_regression

    if should_skip_nested_regression():
        print('SKIP: test_regression_prior_phases (ASTRAEDGE_QA_SMOKE=1)')
        return 0
    for script in (
        'test_chart_patterns_4b15.py',
        'test_screener_longterm_polish_4b14b.py',
        'test_screener_import_attachment_4b14a.py',
        'test_tradecard_memory_4b13.py',
    ):
        rc = _run_regression(script)
        if rc:
            return rc
    return 0


def main() -> int:
    tests = [
        test_append_candle_snapshot,
        test_load_recent_candles_symbol_specific,
        test_old_session_ignored_by_date,
        test_partial_snapshot_no_fake_ohlcv,
        test_build_ohlcv_from_snapshots,
        test_patterns_uses_candle_memory,
        test_patterns_missing_history_message,
        test_pattern_boost_only_with_candles,
        test_pattern_alone_not_tradecard_eligible,
        test_gitignore_covers_intraday_jsonl,
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
    print(f'ALL {len(tests)} INTRADAY_CANDLE_MEMORY_4B15A TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
