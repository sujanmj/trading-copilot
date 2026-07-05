#!/usr/bin/env python3
"""Phase 4B.15 — Chart pattern detection for tradecards."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'CHART_PATTERNS_4B15_FAIL: {msg}', file=sys.stderr)
    return 1


def _candle(i: int, *, low: float, high: float, close: float, volume: float = 1000) -> dict:
    return {
        'timestamp': f'2026-01-{i+1:02d}',
        'open': (low + close) / 2,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }


def _ascending_triangle_candles(*, breakout: bool = False) -> list[dict]:
    candles = []
    resistance = 100.0
    for i in range(24):
        low = 90.0 + i * 0.35
        high = resistance + 0.05
        close = low + (resistance - low) * 0.82
        candles.append(_candle(i, low=low, high=high, close=close, volume=1000 + i * 15))
    if breakout:
        candles[-1] = _candle(23, low=99.0, high=101.2, close=100.6, volume=5000)
        candles[-2] = _candle(22, low=98.5, high=100.8, close=100.2, volume=4500)
        candles[-3] = _candle(21, low=98.0, high=100.5, close=99.8, volume=4200)
    else:
        candles[-1] = _candle(23, low=98.5, high=100.1, close=99.7, volume=3000)
    return candles


def _descending_triangle_candles(*, breakdown: bool = False) -> list[dict]:
    candles = []
    support = 90.0
    for i in range(24):
        high = 110.0 - i * 0.8
        low = support + 0.05
        close = high - (high - support) * 0.75
        candles.append(_candle(i, low=low, high=high, close=close, volume=1200))
    if breakdown:
        candles[-1] = _candle(23, low=88.5, high=91.0, close=89.2, volume=3500)
    return candles


def _symmetrical_triangle_candles() -> list[dict]:
    candles = []
    for i in range(24):
        span = 12.0 - i * 0.35
        mid = 100.0
        low = mid - span / 2
        high = mid + span / 2
        close = mid - span * 0.1
        candles.append(_candle(i, low=low, high=high, close=close, volume=1000 + i * 10))
    return candles


def _breakout_retest_candles() -> list[dict]:
    candles = []
    resistance = 100.0
    for i in range(18):
        candles.append(_candle(i, low=95.0, high=99.5, close=98.0, volume=1000))
    candles.append(_candle(18, low=99.0, high=101.5, close=101.0, volume=4000))
    candles.append(_candle(19, low=100.2, high=102.0, close=101.5, volume=3800))
    candles.append(_candle(20, low=99.8, high=101.0, close=100.4, volume=3600))
    candles.append(_candle(21, low=99.9, high=101.2, close=100.6, volume=3400))
    candles.append(_candle(22, low=100.0, high=101.0, close=100.5, volume=3200))
    candles.append(_candle(23, low=100.1, high=101.3, close=100.8, volume=3000))
    return candles


def _failed_breakout_candles() -> list[dict]:
    candles = []
    for i in range(20):
        candles.append(_candle(i, low=95.0, high=99.5, close=98.0, volume=1000))
    candles.append(_candle(20, low=99.0, high=101.5, close=101.2, volume=4000))
    candles.append(_candle(21, low=100.5, high=102.0, close=101.5, volume=3800))
    candles.append(_candle(22, low=99.0, high=100.5, close=99.5, volume=3200))
    candles.append(_candle(23, low=97.5, high=99.5, close=98.8, volume=3000))
    return candles


def test_ascending_triangle_detected() -> int:
    from backend.trading.chart_patterns import detect_chart_patterns

    result = detect_chart_patterns('TEST', _ascending_triangle_candles())
    patterns = [p.get('pattern') for p in result.get('patterns') or []]
    if 'ascending_triangle' not in patterns:
        return _fail(f'expected ascending_triangle got {patterns}')
    return 0


def test_descending_triangle_detected() -> int:
    from backend.trading.chart_patterns import detect_chart_patterns

    result = detect_chart_patterns('TEST', _descending_triangle_candles())
    patterns = [p.get('pattern') for p in result.get('patterns') or []]
    if 'descending_triangle' not in patterns:
        return _fail(f'expected descending_triangle got {patterns}')
    return 0


def test_symmetrical_triangle_detected() -> int:
    from backend.trading.chart_patterns import detect_chart_patterns

    result = detect_chart_patterns('TEST', _symmetrical_triangle_candles())
    patterns = [p.get('pattern') for p in result.get('patterns') or []]
    if 'symmetrical_triangle' not in patterns:
        return _fail(f'expected symmetrical_triangle got {patterns}')
    return 0


def test_breakout_confirmed_with_volume() -> int:
    from backend.trading.chart_patterns import detect_chart_patterns

    result = detect_chart_patterns('TEST', _ascending_triangle_candles(breakout=True))
    patterns = result.get('patterns') or []
    asc = next((p for p in patterns if p.get('pattern') == 'ascending_triangle'), None)
    if not asc:
        return _fail(f'expected ascending_triangle in {patterns!r}')
    if asc.get('status') not in ('breakout_confirmed', 'near_breakout'):
        return _fail(f'expected breakout status got {asc.get("status")!r}')
    if not asc.get('volume_confirmed'):
        return _fail('expected volume confirmation on breakout')
    return 0


def test_failed_breakout_risk() -> int:
    from backend.trading.chart_patterns import detect_chart_patterns, pattern_score_delta

    result = detect_chart_patterns('TEST', _failed_breakout_candles())
    best = result.get('best_pattern') or {}
    if str(best.get('status') or '') != 'failed_breakout':
        return _fail(f'expected failed_breakout status got {best.get("status")!r}')
    boost, _, _ = pattern_score_delta(best, live_confirmed=True)
    if boost >= 0:
        return _fail(f'failed breakout must apply negative boost got {boost}')
    return 0


def test_retest_confirmed() -> int:
    from backend.trading.chart_patterns import detect_chart_patterns

    result = detect_chart_patterns('TEST', _breakout_retest_candles())
    patterns = result.get('patterns') or []
    retest = next((p for p in patterns if p.get('pattern') == 'breakout_retest'), None)
    if not retest or not retest.get('retest_confirmed'):
        return _fail(f'expected retest confirmed got {patterns!r}')
    return 0


def test_missing_candles_no_crash() -> int:
    from backend.trading.chart_patterns import apply_pattern_evidence_to_row, detect_chart_patterns

    result = detect_chart_patterns('TEST', [])
    if result.get('patterns'):
        return _fail('empty candles must return no patterns')
    row = apply_pattern_evidence_to_row({'ticker': 'TEST', 'score': 50, 'state': 'RADAR_ARMED', 'why': []})
    if row.get('chart_pattern'):
        return _fail('missing candles must not attach pattern')
    return 0


def test_pattern_alone_not_tradecard_eligible() -> int:
    from backend.trading.chart_patterns import apply_pattern_evidence_to_row
    from backend.trading.opening_rally_radar import _opening_tradecard_eligible

    candles = _ascending_triangle_candles(breakout=True)
    row = {
        'ticker': 'TEST',
        'score': 70,
        'state': 'TRADECARD_CANDIDATE',
        'why': [],
        'volume_ratio': 0.5,
        'has_catalyst': False,
        'themes': [],
        'previous_mover': False,
    }
    updated = apply_pattern_evidence_to_row(row, candles=candles)
    if int(updated.get('pattern_boost') or 0) > 0:
        return _fail('pattern alone must not add positive boost without live confirmation')
    updated['pattern_boost'] = 12
    if _opening_tradecard_eligible(updated):
        return _fail('pattern-only boost must not make row tradecard eligible')
    return 0


def test_pattern_boost_capped() -> int:
    from backend.trading.chart_patterns import PATTERN_BOOST_CAP, pattern_score_delta

    best = {
        'pattern': 'ascending_triangle',
        'label': 'Ascending triangle',
        'status': 'breakout_confirmed',
        'volume_confirmed': True,
        'vwap_confirmed': True,
        'retest_confirmed': True,
    }
    boost, _, _ = pattern_score_delta(best, live_confirmed=True)
    if boost > PATTERN_BOOST_CAP:
        return _fail(f'boost {boost} exceeds cap {PATTERN_BOOST_CAP}')
    return 0


def test_tradecard_pattern_section_when_present() -> int:
    from backend.telegram.response_format import _append_tradecard_pattern_section

    lines: list[str] = []
    row = {
        'chart_pattern': 'Ascending triangle',
        'pattern_status': 'near_breakout',
        'breakout_level': 178.2,
        'best_pattern': {
            'support_level': 171.4,
            'volume_confirmed': True,
            'vwap_confirmed': False,
            'risk_flags': ['breakout not confirmed yet'],
        },
    }
    _append_tradecard_pattern_section(lines, None, row=row)
    text = '\n'.join(lines)
    if 'Pattern:' not in text or 'Ascending triangle' not in text:
        return _fail('tradecard pattern section missing')
    if '178.2' not in text:
        return _fail('breakout level missing from pattern section')
    return 0


def test_tradecard_pattern_section_hidden_when_absent() -> int:
    from backend.telegram.response_format import _append_tradecard_pattern_section

    lines: list[str] = ['line1']
    _append_tradecard_pattern_section(lines, None, row={})
    if len(lines) != 1:
        return _fail('empty pattern must not add section')
    return 0


def test_tradecards_reason_includes_pattern_phrase() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    board = {
        'ranked_candidates': [{
            'ticker': 'WIPRO',
            'score': 74,
            'state': 'TRADECARD_CANDIDATE',
            'why': ['ascending triangle near breakout', 'above VWAP'],
            'gainer_bucket': 'large cap',
        }],
        'session_date': '2026-07-04',
        'generated_at': '2026-07-04T09:30:00+05:30',
    }
    with patch('backend.telegram.response_format._persist_tradecards_decision_memory'):
        text = format_tradecards_telegram(board=board)
    if 'ascending triangle' not in text.lower():
        return _fail('tradecards must include pattern phrase in reason')
    return 0


def test_tradecard_memory_stores_pattern_fields() -> int:
    from backend.trading.tradecard_memory import append_tradecard_memory, build_memory_record, load_tradecard_memory

    with tempfile.NamedTemporaryFile(delete=False, suffix='.jsonl') as tmp:
        path = Path(tmp.name)
    os.environ['TRADECARD_MEMORY_FILE'] = str(path)
    try:
        row = {
            'ticker': 'WIPRO',
            'score': 74,
            'state': 'TRADECARD_CANDIDATE',
            'why': ['ascending triangle near breakout'],
            'pattern_detected': True,
            'chart_pattern': 'Ascending triangle',
            'pattern_status': 'near_breakout',
            'breakout_level': 178.2,
            'pattern_confidence': 68,
            'pattern_reasons': ['price near triangle resistance'],
            'pattern_risks': ['breakout not confirmed yet'],
        }
        record = build_memory_record(command_source='/tradecards', board={}, symbol='WIPRO', row=row, rank=1)
        append_tradecard_memory(record)
        loaded = load_tradecard_memory(symbol='WIPRO', limit=1)
        if not loaded or loaded[0].get('chart_pattern') != 'Ascending triangle':
            return _fail('memory must store chart_pattern')
        if loaded[0].get('pattern_status') != 'near_breakout':
            return _fail('memory must store pattern_status')
    finally:
        os.environ.pop('TRADECARD_MEMORY_FILE', None)
        path.unlink(missing_ok=True)
    return 0


def test_memory_stock_shows_pattern_memory() -> int:
    from backend.telegram.response_format import format_tradecard_memory_stock_telegram
    from backend.trading.tradecard_memory import append_tradecard_memory, build_memory_record

    with tempfile.NamedTemporaryFile(delete=False, suffix='.jsonl') as tmp:
        path = Path(tmp.name)
    os.environ['TRADECARD_MEMORY_FILE'] = str(path)
    try:
        row = {
            'score': 74,
            'state': 'TRADECARD_CANDIDATE',
            'why': ['ascending triangle near breakout'],
            'pattern_detected': True,
            'chart_pattern': 'Ascending triangle',
            'pattern_status': 'near_breakout',
            'breakout_level': 178.2,
            'pattern_confidence': 68,
        }
        append_tradecard_memory(build_memory_record(
            command_source='/tradecards', board={}, symbol='WIPRO', row=row, rank=1,
        ))
        text = format_tradecard_memory_stock_telegram('WIPRO')
        if 'Pattern memory:' not in text:
            return _fail('memory stock must show pattern memory section')
        if '178.2' not in text:
            return _fail('pattern breakout level missing from memory stock')
    finally:
        os.environ.pop('TRADECARD_MEMORY_FILE', None)
        path.unlink(missing_ok=True)
    return 0


def test_patterns_command() -> int:
    from backend.telegram.response_format import format_patterns_telegram

    missing = format_patterns_telegram('WIPRO')
    if 'No candle history available' not in missing:
        return _fail(f'expected missing candle message got {missing!r}')

    candles = _ascending_triangle_candles()
    with patch('backend.trading.chart_patterns.load_candles_for_symbol', return_value=candles):
        text = format_patterns_telegram('WIPRO')
    if 'PATTERN — WIPRO' not in text:
        return _fail('patterns command must render header')
    return 0


def test_build_label_51t() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51T' or ASTRAEDGE_BUILD_STAGE != '51T':
        return _fail(f'expected AstraEdge 51T got {ASTRAEDGE_TELEGRAM_BUILD!r}')
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
    for script in (
        'test_screener_longterm_polish_4b14b.py',
        'test_screener_import_attachment_4b14a.py',
        'test_tradecard_memory_4b13.py',
        'test_cap_bucket_visibility_4b12.py',
    ):
        rc = _run_regression(script)
        if rc:
            return rc
    return 0


def main() -> int:
    tests = [
        test_ascending_triangle_detected,
        test_descending_triangle_detected,
        test_symmetrical_triangle_detected,
        test_breakout_confirmed_with_volume,
        test_failed_breakout_risk,
        test_retest_confirmed,
        test_missing_candles_no_crash,
        test_pattern_alone_not_tradecard_eligible,
        test_pattern_boost_capped,
        test_tradecard_pattern_section_when_present,
        test_tradecard_pattern_section_hidden_when_absent,
        test_tradecards_reason_includes_pattern_phrase,
        test_tradecard_memory_stores_pattern_fields,
        test_memory_stock_shows_pattern_memory,
        test_patterns_command,
        test_build_label_51t,
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
    print(f'ALL {len(tests)} CHART_PATTERNS_4B15 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
