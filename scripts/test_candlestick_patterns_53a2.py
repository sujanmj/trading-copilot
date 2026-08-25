#!/usr/bin/env python3
"""AstraEdge 53A2 — deterministic multi-candle candlestick pattern focused tests."""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

PASS_MARKERS: list[str] = []
MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'candlestick_patterns.py'
ANATOMY_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'candle_anatomy.py'
FORBIDDEN_OUTPUT = (
    'buy',
    'sell',
    'entry',
    'stop',
    'target',
    'recommendation',
    'probability',
    'confidence',
    'trade_signal',
)


def _fail(msg: str) -> int:
    print(f'CANDLESTICK_PATTERNS_53A2_FAIL: {msg}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


def _git_data_status() -> str:
    proc = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or '').strip()


def _imported_names(src: str) -> set[str]:
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split('.')[0])
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            imported.add(mod.split('.')[0])
            imported.add(mod)
    return imported


def _c(*, o, h, l, c, volume=None):
    row = {'open': o, 'high': h, 'low': l, 'close': c}
    if volume is not None:
        row['volume'] = volume
    return row


def _analyze(candles):
    from backend.analysis.candlestick_patterns import analyze_candlestick_patterns

    return analyze_candlestick_patterns(candles)


def _ok_tags(result, expected: list[str], marker: str) -> int | None:
    if result['pattern_state'] != 'OK':
        return _fail(f'{marker} expected OK, got {result["pattern_state"]!r}')
    if result['pattern_tags'] != expected:
        return _fail(f'{marker} expected {expected}, got {result["pattern_tags"]}')
    if result['schema_version'] != '53A2':
        return _fail(f'{marker} schema_version must be 53A2')
    return None


def test_t1_build() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53A2', 'AstraEdge 53A2'),
        ('53B', 'AstraEdge 53B'),
    }:
        return _fail(f'expected 53A2 or successor 53B pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')
    return 0


def test_t2_t4_engulfing() -> int:
    from backend.analysis.candlestick_patterns import (
        TAG_BEARISH_ENGULFING,
        TAG_BULLISH_ENGULFING,
    )

    bullish = _analyze([
        _c(o=110, h=120, l=90, c=100),
        _c(o=98, h=125, l=95, c=112),
    ])
    err = _ok_tags(bullish, [TAG_BULLISH_ENGULFING], 'T2')
    if err:
        return err
    _pass('T2')

    bearish = _analyze([
        _c(o=100, h=120, l=90, c=110),
        _c(o=112, h=125, l=95, c=98),
    ])
    err = _ok_tags(bearish, [TAG_BEARISH_ENGULFING], 'T3')
    if err:
        return err
    _pass('T3')

    equal_body = _analyze([
        _c(o=110, h=120, l=90, c=100),
        _c(o=100, h=130, l=80, c=110),
    ])
    if TAG_BULLISH_ENGULFING in equal_body['pattern_tags']:
        return _fail('T4 identical bodies must not be engulfing')
    if equal_body['pattern_state'] != 'OK':
        return _fail('T4 equal-body window must remain OK')
    _pass('T4')
    return 0


def test_t5_t6_harami() -> int:
    from backend.analysis.candlestick_patterns import TAG_BEARISH_HARAMI, TAG_BULLISH_HARAMI

    bullish = _analyze([
        _c(o=120, h=125, l=95, c=100),
        _c(o=105, h=140, l=103, c=108),
    ])
    err = _ok_tags(bullish, [TAG_BULLISH_HARAMI], 'T5')
    if err:
        return err
    _pass('T5')

    bearish = _analyze([
        _c(o=100, h=125, l=95, c=120),
        _c(o=115, h=140, l=103, c=112),
    ])
    err = _ok_tags(bearish, [TAG_BEARISH_HARAMI], 'T6')
    if err:
        return err
    _pass('T6')
    return 0


def test_t7_t8_piercing_dark_cloud() -> int:
    from backend.analysis.candlestick_patterns import (
        TAG_DARK_CLOUD_COVER_LIKE,
        TAG_PIERCING_LINE_LIKE,
    )

    piercing = _analyze([
        _c(o=120, h=125, l=70, c=100),
        _c(o=98, h=160, l=98, c=115),
    ])
    err = _ok_tags(piercing, [TAG_PIERCING_LINE_LIKE], 'T7')
    if err:
        return err
    _pass('T7')

    dark = _analyze([
        _c(o=100, h=125, l=70, c=120),
        _c(o=122, h=160, l=105, c=105),
    ])
    err = _ok_tags(dark, [TAG_DARK_CLOUD_COVER_LIKE], 'T8')
    if err:
        return err
    _pass('T8')
    return 0


def test_t9_t11_inside_outside() -> int:
    from backend.analysis.candlestick_patterns import TAG_INSIDE_BAR, TAG_OUTSIDE_BAR

    inside = _analyze([
        _c(o=100, h=120, l=90, c=110),
        _c(o=102, h=115, l=95, c=108),
    ])
    err = _ok_tags(inside, [TAG_INSIDE_BAR], 'T9')
    if err:
        return err
    _pass('T9')

    outside = _analyze([
        _c(o=102, h=110, l=100, c=108),
        _c(o=100, h=115, l=95, c=106),
    ])
    err = _ok_tags(outside, [TAG_OUTSIDE_BAR], 'T10')
    if err:
        return err
    _pass('T10')

    identical = _analyze([
        _c(o=100, h=120, l=90, c=110),
        _c(o=100, h=120, l=90, c=110),
    ])
    if TAG_INSIDE_BAR in identical['pattern_tags'] or TAG_OUTSIDE_BAR in identical['pattern_tags']:
        return _fail('T11 identical ranges must not be inside or outside')
    if identical['pattern_state'] != 'OK':
        return _fail('T11 identical-range window must remain OK')
    _pass('T11')
    return 0


def test_t12_t14_tweezers() -> int:
    from backend.analysis.candlestick_patterns import (
        TAG_TWEEZER_BOTTOM_LIKE,
        TAG_TWEEZER_TOP_LIKE,
    )

    top = _analyze([
        _c(o=100, h=120, l=90, c=110),
        _c(o=118, h=120.5, l=100, c=108),
    ])
    err = _ok_tags(top, [TAG_TWEEZER_TOP_LIKE], 'T12')
    if err:
        return err
    _pass('T12')

    bottom = _analyze([
        _c(o=110, h=120, l=90, c=100),
        _c(o=92, h=125, l=90.4, c=102),
    ])
    err = _ok_tags(bottom, [TAG_TWEEZER_BOTTOM_LIKE], 'T13')
    if err:
        return err
    _pass('T13')

    outside_tol = _analyze([
        _c(o=100, h=120, l=100, c=110),
        _c(o=118, h=122, l=108, c=108),
    ])
    if TAG_TWEEZER_TOP_LIKE in outside_tol['pattern_tags'] or TAG_TWEEZER_BOTTOM_LIKE in outside_tol['pattern_tags']:
        return _fail('T14 highs/lows outside tolerance must not be tweezers')
    _pass('T14')
    return 0


def test_t15_t18_three_candle() -> int:
    from backend.analysis.candlestick_patterns import (
        TAG_EVENING_STAR_LIKE,
        TAG_MORNING_STAR_LIKE,
        TAG_THREE_BLACK_CROWS_LIKE,
        TAG_THREE_WHITE_SOLDIERS_LIKE,
    )

    morning = _analyze([
        _c(o=120, h=121, l=99, c=100),
        _c(o=99, h=105, l=95, c=101),
        _c(o=102, h=120, l=101, c=118),
    ])
    err = _ok_tags(morning, [TAG_MORNING_STAR_LIKE], 'T15')
    if err:
        return err
    _pass('T15')

    evening = _analyze([
        _c(o=100, h=121, l=99, c=120),
        _c(o=121, h=125, l=115, c=119),
        _c(o=118, h=119, l=100, c=102),
    ])
    err = _ok_tags(evening, [TAG_EVENING_STAR_LIKE], 'T16')
    if err:
        return err
    _pass('T16')

    soldiers = _analyze([
        _c(o=100, h=111, l=99, c=110),
        _c(o=105, h=117, l=104, c=116),
        _c(o=112, h=125, l=111, c=124),
    ])
    err = _ok_tags(soldiers, [TAG_THREE_WHITE_SOLDIERS_LIKE], 'T17')
    if err:
        return err
    _pass('T17')

    crows = _analyze([
        _c(o=124, h=125, l=113, c=114),
        _c(o=119, h=120, l=107, c=108),
        _c(o=112, h=113, l=99, c=100),
    ])
    err = _ok_tags(crows, [TAG_THREE_BLACK_CROWS_LIKE], 'T18')
    if err:
        return err
    _pass('T18')
    return 0


def test_t19_t20_additive_and_empty() -> int:
    from backend.analysis.candlestick_patterns import TAG_BULLISH_ENGULFING, TAG_OUTSIDE_BAR

    multi = _analyze([
        _c(o=110, h=110, l=100, c=100),
        _c(o=99, h=112, l=99, c=112),
    ])
    err = _ok_tags(multi, [TAG_BULLISH_ENGULFING, TAG_OUTSIDE_BAR], 'T19')
    if err:
        return err
    _pass('T19')

    empty = _analyze([
        _c(o=100, h=102, l=99, c=101),
        _c(o=101.5, h=103, l=100.5, c=102.5),
    ])
    err = _ok_tags(empty, [], 'T20')
    if err:
        return err
    _pass('T20')
    return 0


def test_t21_t25_fail_closed() -> int:
    from backend.analysis.candlestick_patterns import TAG_INSIDE_BAR

    one = _analyze([_c(o=100, h=110, l=99, c=108)])
    if one['pattern_state'] != 'INSUFFICIENT_CANDLES' or one['pattern_tags'] != []:
        return _fail(f'T21 expected INSUFFICIENT_CANDLES, got {one}')
    if one['candle_count'] != 1:
        return _fail('T21 candle_count must be 1')
    _pass('T21')

    empty = _analyze([])
    if empty['pattern_state'] != 'INSUFFICIENT_CANDLES' or empty['pattern_tags'] != []:
        return _fail(f'T22 expected INSUFFICIENT_CANDLES, got {empty}')
    if empty['candle_count'] != 0:
        return _fail('T22 candle_count must be 0')
    _pass('T22')

    four = _analyze([
        _c(o=100, h=101, l=99, c=100.5),
        _c(o=101, h=102, l=100, c=101.5),
        _c(o=102, h=103, l=101, c=102.5),
        _c(o=103, h=104, l=102, c=103.5),
    ])
    if four['pattern_state'] != 'UNSUPPORTED_WINDOW' or four['pattern_tags'] != []:
        return _fail(f'T23 four candles must fail closed, got {four}')
    if four['candle_count'] != 4:
        return _fail('T23 candle_count must remain 4')
    _pass('T23')

    malformed = _analyze([
        _c(o=110, h=120, l=90, c=100),
        _c(o=True, h=125, l=95, c=112),
    ])
    if malformed['pattern_state'] != 'MALFORMED' or malformed['pattern_tags'] != []:
        return _fail(f'T24 malformed must propagate, got {malformed}')
    _pass('T24')

    zero = _analyze([
        _c(o=100, h=120, l=90, c=110),
        _c(o=105, h=105, l=105, c=105),
    ])
    if zero['pattern_state'] != 'OK':
        return _fail(f'T25 zero-range must remain analyzable, got {zero["pattern_state"]}')
    if zero['pattern_tags'] != [TAG_INSIDE_BAR]:
        return _fail(f'T25 zero-range inside previous range expected INSIDE_BAR, got {zero["pattern_tags"]}')
    if zero['candle_anatomy'][1]['anatomy_state'] != 'ZERO_RANGE':
        return _fail('T25 current anatomy_state must remain ZERO_RANGE')
    _pass('T25')
    return 0


def test_repair1_cardinality_precedence() -> int:
    one_valid = _analyze([_c(o=100, h=110, l=99, c=108)])
    if one_valid['pattern_state'] != 'INSUFFICIENT_CANDLES':
        return _fail(f'R1 one valid candle must be INSUFFICIENT_CANDLES, got {one_valid}')
    if one_valid['candle_count'] != 1 or one_valid['candle_anatomy'] != []:
        return _fail(f'R1 one valid candle must not run anatomy, got {one_valid}')
    _pass('R1_ONE_VALID_INSUFFICIENT_OK')

    one_malformed = _analyze([_c(o=True, h=110, l=99, c=108)])
    if one_malformed['pattern_state'] != 'INSUFFICIENT_CANDLES':
        return _fail(f'R1 one malformed candle must be INSUFFICIENT_CANDLES, got {one_malformed}')
    if one_malformed['candle_count'] != 1 or one_malformed['candle_anatomy'] != []:
        return _fail(f'R1 one malformed candle must not run anatomy, got {one_malformed}')
    _pass('R1_ONE_MALFORMED_INSUFFICIENT_OK')

    empty = _analyze([])
    if empty['pattern_state'] != 'INSUFFICIENT_CANDLES':
        return _fail(f'R1 empty list must be INSUFFICIENT_CANDLES, got {empty}')
    if empty['candle_count'] != 0 or empty['candle_anatomy'] != []:
        return _fail(f'R1 empty list envelope mismatch, got {empty}')
    _pass('R1_EMPTY_INSUFFICIENT_OK')

    four_valid_rows = [
        _c(o=100, h=101, l=99, c=100.5),
        _c(o=101, h=102, l=100, c=101.5),
        _c(o=102, h=103, l=101, c=102.5),
        _c(o=103, h=104, l=102, c=103.5),
    ]
    four_malformed_rows = copy.deepcopy(four_valid_rows)
    four_malformed_rows[1]['open'] = True
    with patch('backend.analysis.candlestick_patterns.analyze_candle') as anatomy_mock:
        four_valid = _analyze(four_valid_rows)
        four_malformed = _analyze(four_malformed_rows)
    if anatomy_mock.call_count != 0:
        return _fail(f'R1 unsupported windows must not run anatomy, calls={anatomy_mock.call_count}')
    if four_valid['pattern_state'] != 'UNSUPPORTED_WINDOW':
        return _fail(f'R1 four valid candles must be UNSUPPORTED_WINDOW, got {four_valid}')
    if four_valid['candle_count'] != 4 or four_valid['candle_anatomy'] != []:
        return _fail(f'R1 four valid candle envelope mismatch, got {four_valid}')
    _pass('R1_FOUR_VALID_UNSUPPORTED_OK')
    if four_malformed['pattern_state'] != 'UNSUPPORTED_WINDOW':
        return _fail(f'R1 four candles with malformed must be UNSUPPORTED_WINDOW, got {four_malformed}')
    if four_malformed['candle_count'] != 4 or four_malformed['candle_anatomy'] != []:
        return _fail(f'R1 four malformed-containing candle envelope mismatch, got {four_malformed}')
    _pass('R1_FOUR_MALFORMED_UNSUPPORTED_OK')

    two_malformed = _analyze([
        _c(o=110, h=120, l=90, c=100),
        _c(o=True, h=125, l=95, c=112),
    ])
    if two_malformed['pattern_state'] != 'MALFORMED':
        return _fail(f'R1 supported 2-candle malformed window must be MALFORMED, got {two_malformed}')
    if len(two_malformed['candle_anatomy']) != 2:
        return _fail(f'R1 supported 2-candle window must analyze every candle, got {two_malformed}')
    _pass('R1_TWO_MALFORMED_OK')

    three_malformed = _analyze([
        _c(o=110, h=120, l=90, c=100),
        _c(o=100, h=115, l=95, c=105),
        _c(o=True, h=125, l=95, c=112),
    ])
    if three_malformed['pattern_state'] != 'MALFORMED':
        return _fail(f'R1 supported 3-candle malformed window must be MALFORMED, got {three_malformed}')
    if len(three_malformed['candle_anatomy']) != 3:
        return _fail(f'R1 supported 3-candle window must analyze every candle, got {three_malformed}')
    _pass('R1_THREE_MALFORMED_OK')
    _pass('CANDLESTICK_PATTERNS_53A2_REPAIR1_CARDINALITY_OK')
    return 0


def test_t26_t29_determinism() -> int:
    from backend.analysis.candlestick_patterns import (
        PATTERN_KEYS,
        TAG_BULLISH_ENGULFING,
        TAG_INSIDE_BAR,
    )

    original = [
        _c(o=110, h=120, l=90, c=100, volume=10),
        _c(o=98, h=125, l=95, c=112, volume=11),
    ]
    before = copy.deepcopy(original)
    first = _analyze(original)
    if original != before:
        return _fail('T26 input was mutated')
    _pass('T26')

    second = _analyze(original)
    if first != second:
        return _fail('T27 same input must produce the same output')
    _pass('T27')

    reordered = [
        {'volume': 10, 'close': 100, 'low': 90, 'high': 120, 'open': 110},
        {'close': 112, 'open': 98, 'volume': 11, 'high': 125, 'low': 95},
    ]
    if _analyze(reordered) != first:
        return _fail('T28 key order must not change output')
    if list(first.keys()) != list(PATTERN_KEYS):
        return _fail(f'T28 closed keys mismatch {list(first.keys())}')
    _pass('T28')

    reversed_pair = _analyze(list(reversed(original)))
    if TAG_BULLISH_ENGULFING in reversed_pair['pattern_tags']:
        return _fail('T29 reversed chronology must not keep BULLISH_ENGULFING')
    if reversed_pair['pattern_tags'] == first['pattern_tags']:
        return _fail('T29 reversed chronology must change the pair geometry')
    last_pair_in_three = _analyze([
        _c(o=50, h=52, l=49, c=51),
        _c(o=100, h=120, l=90, c=110),
        _c(o=102, h=115, l=95, c=108),
    ])
    if last_pair_in_three['pattern_tags'] != [TAG_INSIDE_BAR]:
        return _fail(f'T29 last-pair tags expected INSIDE_BAR, got {last_pair_in_three["pattern_tags"]}')
    _pass('T29')
    return 0


def test_t30_t40_contract() -> int:
    from backend.analysis.candlestick_patterns import (
        PATTERN_TAG_ORDER,
        SOLDIER_BODY_RATIO_MIN,
        STAR_OUTER_BODY_RATIO_MIN,
        STAR_SMALL_BODY_RATIO_MAX,
        TWEEZER_LEVEL_TOLERANCE_RATIO,
        analyze_candlestick_patterns,
    )

    src = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(src)
    if 'backend.analysis.candle_anatomy' not in imported:
        return _fail('T30 must import backend.analysis.candle_anatomy')
    if 'analyze_candle(' not in src or 'from backend.analysis.candle_anatomy import' not in src:
        return _fail('T30 must reuse analyze_candle')
    if 'def analyze_candle(' in src:
        return _fail('T30 must not reimplement analyze_candle')
    if 'isnan' in src or 'isinf' in src:
        return _fail('T30 must not duplicate 53A OHLC validation')
    if not ANATOMY_PATH.is_file():
        return _fail('T30 53A analyzer is missing')
    _pass('T30')

    for mod in ('requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser'):
        if mod in imported:
            return _fail(f'T31 network import {mod}')
    for needle in ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai'):
        if needle in src:
            return _fail(f'T31 AI needle {needle}')
    for needle in ('open(', 'write_text', 'write_bytes', 'atomic_write'):
        if needle in src:
            return _fail(f'T31 write path {needle}')
    _pass('T31')

    sample = _analyze([
        _c(o=110, h=120, l=90, c=100),
        _c(o=98, h=125, l=95, c=112),
    ])
    blob = json.dumps(sample).lower()
    for token in FORBIDDEN_OUTPUT:
        if token in blob:
            return _fail(f'T32 output contains {token}')
    src_lower = src.lower()
    for token in FORBIDDEN_OUTPUT:
        if token in src_lower:
            return _fail(f'T32 module source contains {token}')
    _pass('T32')

    if _git_data_status():
        return _fail('T33 data/ is not clean')
    _pass('T33')

    if sample['candle_count'] != 2 or len(sample['candle_anatomy']) != 2:
        return _fail('T34 candle_anatomy must carry both 53A records')
    if sample['candle_anatomy'][0]['schema_version'] != '53A':
        return _fail('T34 per-candle anatomy schema must remain 53A')
    _pass('T34')

    constants = (
        TWEEZER_LEVEL_TOLERANCE_RATIO,
        STAR_SMALL_BODY_RATIO_MAX,
        STAR_OUTER_BODY_RATIO_MIN,
        SOLDIER_BODY_RATIO_MIN,
    )
    if constants != (0.05, 0.30, 0.50, 0.50):
        return _fail(f'T35 threshold constants drifted {constants}')
    required = {
        'BULLISH_ENGULFING',
        'BEARISH_ENGULFING',
        'BULLISH_HARAMI',
        'BEARISH_HARAMI',
        'PIERCING_LINE_LIKE',
        'DARK_CLOUD_COVER_LIKE',
        'INSIDE_BAR',
        'OUTSIDE_BAR',
        'TWEEZER_TOP_LIKE',
        'TWEEZER_BOTTOM_LIKE',
        'MORNING_STAR_LIKE',
        'EVENING_STAR_LIKE',
        'THREE_WHITE_SOLDIERS_LIKE',
        'THREE_BLACK_CROWS_LIKE',
    }
    if set(PATTERN_TAG_ORDER) != required:
        return _fail(f'T35 PATTERN_TAG_ORDER mismatch {PATTERN_TAG_ORDER}')
    _pass('T35')

    not_list = analyze_candlestick_patterns({'open': 1, 'high': 2, 'low': 0, 'close': 1})  # type: ignore[arg-type]
    if not_list['pattern_state'] != 'MALFORMED' or not_list['pattern_tags'] != []:
        return _fail(f'T36 non-list must fail closed, got {not_list}')
    _pass('T36')

    two_of_morning = _analyze([
        _c(o=120, h=121, l=99, c=100),
        _c(o=99, h=105, l=95, c=101),
    ])
    if 'MORNING_STAR_LIKE' in two_of_morning['pattern_tags']:
        return _fail('T37 2-candle window must not emit 3-candle star tags')
    _pass('T37')

    if any(name.startswith(('BUY_', 'SELL_')) for name in sample['pattern_tags']):
        return _fail('T38 must not emit BUY_/SELL_ recommendation tags')
    _pass('T38')

    if sample['candle_anatomy'][0] is sample['candle_anatomy'][1]:
        return _fail('T39 anatomy records must not be aliased')
    _pass('T39')

    if 'HAMMER_LIKE' in src or 'SHOOTING_STAR_LIKE' in src or 'UPPER_REJECTION' in src:
        return _fail('T40 must not duplicate 53A pin-bar tags')
    _pass('T40')
    return 0


def main() -> int:
    tests = (
        test_t1_build,
        test_t2_t4_engulfing,
        test_t5_t6_harami,
        test_t7_t8_piercing_dark_cloud,
        test_t9_t11_inside_outside,
        test_t12_t14_tweezers,
        test_t15_t18_three_candle,
        test_t19_t20_additive_and_empty,
        test_t21_t25_fail_closed,
        test_repair1_cardinality_precedence,
        test_t26_t29_determinism,
        test_t30_t40_contract,
    )
    for test in tests:
        rc = test()
        if rc:
            return rc
    expected = tuple(f'T{i}' for i in range(1, 41))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers {missing}')
    repair_markers = (
        'R1_ONE_VALID_INSUFFICIENT_OK',
        'R1_ONE_MALFORMED_INSUFFICIENT_OK',
        'R1_EMPTY_INSUFFICIENT_OK',
        'R1_FOUR_VALID_UNSUPPORTED_OK',
        'R1_FOUR_MALFORMED_UNSUPPORTED_OK',
        'R1_TWO_MALFORMED_OK',
        'R1_THREE_MALFORMED_OK',
        'CANDLESTICK_PATTERNS_53A2_REPAIR1_CARDINALITY_OK',
    )
    missing_repair = [marker for marker in repair_markers if marker not in PASS_MARKERS]
    if missing_repair:
        return _fail(f'missing repair markers {missing_repair}')
    print('CANDLESTICK_PATTERNS_53A2_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
