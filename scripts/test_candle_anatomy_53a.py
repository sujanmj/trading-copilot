#!/usr/bin/env python3
"""AstraEdge 53A — deterministic candle anatomy focused tests."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

PASS_MARKERS: list[str] = []
MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'candle_anatomy.py'
FORBIDDEN_OUTPUT = (
    'buy',
    'sell',
    'entry',
    'stop',
    'target',
    'probability',
    'confidence',
    'signal',
)


def _fail(msg: str) -> int:
    print(f'CANDLE_ANATOMY_53A_FAIL: {msg}', file=sys.stderr)
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


def _candle(**fields):
    return dict(fields)


def test_t1_build() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53A', 'AstraEdge 53A'),
        ('53A2', 'AstraEdge 53A2'),
        ('53B', 'AstraEdge 53B'),
        ('53C', 'AstraEdge 53C'),
        ('53D', 'AstraEdge 53D'),
    }:
        return _fail(f'expected 53A or successor 53A2/53B/53C/53D pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')
    return 0


def test_t2_t7_directions() -> int:
    from backend.analysis.candle_anatomy import (
        ANATOMY_STATE_OK,
        ANATOMY_STATE_ZERO_RANGE,
        DIRECTION_BEARISH,
        DIRECTION_BULLISH,
        DIRECTION_NEUTRAL,
        TAG_MARUBOZU_LIKE,
        TAG_STRONG_BEARISH_BODY,
        TAG_STRONG_BULLISH_BODY,
        analyze_candle,
    )

    bull = analyze_candle(_candle(open=100, high=110, low=99, close=108, volume=1000))
    if bull['direction'] != DIRECTION_BULLISH or bull['anatomy_state'] != ANATOMY_STATE_OK:
        return _fail(f'T2 unexpected {bull["direction"]} {bull["anatomy_state"]}')
    _pass('T2')

    bear = analyze_candle(_candle(open=108, high=110, low=99, close=100, volume=1000))
    if bear['direction'] != DIRECTION_BEARISH:
        return _fail(f'T3 unexpected {bear["direction"]}')
    _pass('T3')

    neutral = analyze_candle(_candle(open=105, high=110, low=100, close=105))
    if neutral['direction'] != DIRECTION_NEUTRAL or neutral['anatomy_state'] != ANATOMY_STATE_OK:
        return _fail('T4 neutral candle with range must stay NEUTRAL/OK')
    if neutral['body'] != 0:
        return _fail('T4 body must be 0')
    _pass('T4')

    zero = analyze_candle(_candle(open=100, high=100, low=100, close=100))
    if zero['anatomy_state'] != ANATOMY_STATE_ZERO_RANGE:
        return _fail(f'T5 expected ZERO_RANGE got {zero["anatomy_state"]}')
    if zero['direction'] != DIRECTION_NEUTRAL:
        return _fail('T5 zero-range direction must be NEUTRAL')
    if any(zero[k] not in (0, 0.0) for k in ('range', 'body', 'upper_wick', 'lower_wick')):
        return _fail('T5 zero-range measures must be 0')
    if any(zero[k] is not None for k in (
        'body_ratio', 'upper_wick_ratio', 'lower_wick_ratio', 'open_position', 'close_position',
    )):
        return _fail('T5 zero-range ratios must be null')
    if zero['shape_tags'] != []:
        return _fail('T5 zero-range tags must be empty')
    _pass('T5')

    full_bull = analyze_candle(_candle(open=100, high=110, low=100, close=110))
    if full_bull['direction'] != DIRECTION_BULLISH:
        return _fail('T6 full-body must be BULLISH')
    if TAG_STRONG_BULLISH_BODY not in full_bull['shape_tags'] or TAG_MARUBOZU_LIKE not in full_bull['shape_tags']:
        return _fail(f'T6 expected strong/marubozu tags, got {full_bull["shape_tags"]}')
    if full_bull['body'] != full_bull['range'] or full_bull['upper_wick'] != 0 or full_bull['lower_wick'] != 0:
        return _fail('T6 full-body wicks must be 0')
    _pass('T6')

    full_bear = analyze_candle(_candle(open=110, high=110, low=100, close=100))
    if full_bear['direction'] != DIRECTION_BEARISH:
        return _fail('T7 full-body must be BEARISH')
    if TAG_STRONG_BEARISH_BODY not in full_bear['shape_tags'] or TAG_MARUBOZU_LIKE not in full_bear['shape_tags']:
        return _fail(f'T7 expected strong/marubozu tags, got {full_bear["shape_tags"]}')
    _pass('T7')
    return 0


def test_t8_t18_shapes() -> int:
    from backend.analysis.candle_anatomy import (
        TAG_DOJI_LIKE,
        TAG_HAMMER_LIKE,
        TAG_LONG_LOWER_WICK,
        TAG_LONG_UPPER_WICK,
        TAG_LOWER_REJECTION,
        TAG_MARUBOZU_LIKE,
        TAG_SHOOTING_STAR_LIKE,
        TAG_STRONG_BEARISH_BODY,
        TAG_STRONG_BULLISH_BODY,
        TAG_UPPER_REJECTION,
        analyze_candle,
    )

    doji = analyze_candle(_candle(open=105, high=110, low=100, close=105))
    if TAG_DOJI_LIKE not in doji['shape_tags']:
        return _fail(f'T8 expected DOJI_LIKE got {doji["shape_tags"]}')
    _pass('T8')

    strong_bull = analyze_candle(_candle(open=100, high=120, low=100, close=113))
    if TAG_STRONG_BULLISH_BODY not in strong_bull['shape_tags']:
        return _fail(f'T9 expected STRONG_BULLISH_BODY got {strong_bull["shape_tags"]}')
    if TAG_MARUBOZU_LIKE in strong_bull['shape_tags']:
        return _fail('T9 must not be MARUBOZU_LIKE')
    _pass('T9')

    strong_bear = analyze_candle(_candle(open=120, high=120, low=100, close=107))
    if TAG_STRONG_BEARISH_BODY not in strong_bear['shape_tags']:
        return _fail(f'T10 expected STRONG_BEARISH_BODY got {strong_bear["shape_tags"]}')
    _pass('T10')

    long_upper = analyze_candle(_candle(open=100, high=120, low=100, close=101))
    if TAG_LONG_UPPER_WICK not in long_upper['shape_tags']:
        return _fail(f'T11 expected LONG_UPPER_WICK got {long_upper["shape_tags"]}')
    _pass('T11')

    long_lower = analyze_candle(_candle(open=119, high=120, low=100, close=120))
    if TAG_LONG_LOWER_WICK not in long_lower['shape_tags']:
        return _fail(f'T12 expected LONG_LOWER_WICK got {long_lower["shape_tags"]}')
    _pass('T12')

    upper_rej = analyze_candle(_candle(open=100, high=120, low=100, close=104))
    if TAG_UPPER_REJECTION not in upper_rej['shape_tags']:
        return _fail(f'T13 expected UPPER_REJECTION got {upper_rej["shape_tags"]}')
    _pass('T13')

    lower_rej = analyze_candle(_candle(open=116, high=120, low=100, close=120))
    if TAG_LOWER_REJECTION not in lower_rej['shape_tags']:
        return _fail(f'T14 expected LOWER_REJECTION got {lower_rej["shape_tags"]}')
    _pass('T14')

    hammer = analyze_candle(_candle(open=105, high=107, low=100, close=106))
    if TAG_HAMMER_LIKE not in hammer['shape_tags']:
        return _fail(f'T15 expected HAMMER_LIKE got {hammer["shape_tags"]}')
    if hammer['direction'] != 'BULLISH':
        return _fail('T15 fixture is geometrically bullish but HAMMER_LIKE must not require a trade bias')
    _pass('T15')

    star = analyze_candle(_candle(open=105, high=110, low=103, close=104))
    if TAG_SHOOTING_STAR_LIKE not in star['shape_tags']:
        return _fail(f'T16 expected SHOOTING_STAR_LIKE got {star["shape_tags"]}')
    _pass('T16')

    maru = analyze_candle(_candle(open=100.4, high=110.0, low=100.0, close=109.6))
    if TAG_MARUBOZU_LIKE not in maru['shape_tags']:
        return _fail(f'T17 expected MARUBOZU_LIKE got {maru["shape_tags"]}')
    _pass('T17')

    multi = analyze_candle(_candle(open=100, high=120, low=100, close=101))
    required = {TAG_DOJI_LIKE, TAG_LONG_UPPER_WICK, TAG_UPPER_REJECTION, TAG_SHOOTING_STAR_LIKE}
    missing = required - set(multi['shape_tags'])
    if missing:
        return _fail(f'T18 missing tags {sorted(missing)} in {multi["shape_tags"]}')
    _pass('T18')
    return 0


def test_t19_t21_ratios() -> int:
    from backend.analysis.candle_anatomy import analyze_candle

    row = analyze_candle(_candle(open=10, high=20, low=0, close=15, volume=12))
    if row['range'] != 20:
        return _fail(f'T19 range {row["range"]}')
    if row['body'] != 5:
        return _fail(f'T19 body {row["body"]}')
    if row['upper_wick'] != 5 or row['lower_wick'] != 10:
        return _fail(f'T19 wicks {row["upper_wick"]} {row["lower_wick"]}')
    if row['body_ratio'] != 0.25 or row['upper_wick_ratio'] != 0.25 or row['lower_wick_ratio'] != 0.5:
        return _fail('T19 ratio mismatch')
    if row['open_position'] != 0.5 or row['close_position'] != 0.75:
        return _fail('T19 position mismatch')
    for key in ('body_ratio', 'upper_wick_ratio', 'lower_wick_ratio', 'open_position', 'close_position'):
        val = row[key]
        if not (0.0 <= val <= 1.0):
            return _fail(f'T19 {key} out of bounds {val}')
    _pass('T19')

    at_high = analyze_candle(_candle(open=10, high=20, low=0, close=20))
    if at_high['close_position'] != 1:
        return _fail(f'T20 close_position {at_high["close_position"]}')
    _pass('T20')

    at_low = analyze_candle(_candle(open=10, high=20, low=0, close=0))
    if at_low['close_position'] != 0:
        return _fail(f'T21 close_position {at_low["close_position"]}')
    _pass('T21')
    return 0


def test_t22_t33_fail_closed() -> int:
    from backend.analysis.candle_anatomy import ANATOMY_STATE_MALFORMED, ANATOMY_STATE_OK, analyze_candle

    cases = [
        ('T22', _candle(open=10, high=5, low=8, close=9)),
        ('T23', _candle(open=20, high=15, low=10, close=12)),
        ('T24', _candle(open=10, high=15, low=10, close=20)),
        ('T25', _candle(open=5, high=20, low=10, close=15)),
        ('T26', _candle(open=15, high=20, low=10, close=5)),
        ('T27', {'high': 10, 'low': 1, 'close': 5}),
        ('T28', _candle(open='100', high=110, low=90, close=105)),
        ('T29', _candle(open=100, high=float('nan'), low=90, close=105)),
        ('T30', _candle(open=100, high=float('inf'), low=90, close=105)),
    ]
    for marker, payload in cases:
        result = analyze_candle(payload)
        if result['anatomy_state'] != ANATOMY_STATE_MALFORMED:
            return _fail(f'{marker} expected MALFORMED got {result["anatomy_state"]}')
        if any(result[k] is not None for k in (
            'range', 'body', 'upper_wick', 'lower_wick',
            'body_ratio', 'upper_wick_ratio', 'lower_wick_ratio',
            'open_position', 'close_position', 'direction',
        )):
            return _fail(f'{marker} malformed must not invent measures')
        _pass(marker)

    with_vol = analyze_candle(_candle(open=100, high=110, low=99, close=108, volume=2500))
    if with_vol['volume'] != 2500 or with_vol['anatomy_state'] != ANATOMY_STATE_OK:
        return _fail('T31 valid volume must pass through')
    _pass('T31')

    missing_vol = analyze_candle(_candle(open=100, high=110, low=99, close=108))
    if missing_vol['volume'] is not None or missing_vol['anatomy_state'] != ANATOMY_STATE_OK:
        return _fail('T32 missing volume must be allowed')
    _pass('T32')

    bad_vol = analyze_candle(_candle(open=100, high=110, low=99, close=108, volume=float('nan')))
    if bad_vol['anatomy_state'] != ANATOMY_STATE_MALFORMED:
        return _fail('T33 malformed volume must fail closed')
    _pass('T33')
    return 0


def test_t34_t45_contract() -> int:
    from backend.analysis.candle_anatomy import (
        ANATOMY_KEYS,
        DOJI_BODY_RATIO_MAX,
        HAMMER_OPPOSITE_WICK_TO_BODY_MAX,
        HAMMER_WICK_TO_BODY_MIN,
        LONG_WICK_RATIO_MIN,
        MARUBOZU_BODY_RATIO_MIN,
        MARUBOZU_WICK_RATIO_MAX,
        REJECTION_BODY_RATIO_MAX,
        REJECTION_WICK_RATIO_MIN,
        STRONG_BODY_RATIO_MIN,
        analyze_candle,
    )

    original = _candle(open=100, high=110, low=99, close=108, volume=10)
    before = dict(original)
    first = analyze_candle(original)
    if original != before:
        return _fail('T34 input was mutated')
    _pass('T34')

    second = analyze_candle(original)
    if first != second:
        return _fail('T35 same input must produce the same output')
    _pass('T35')

    reordered = {'volume': 10, 'close': 108, 'low': 99, 'high': 110, 'open': 100}
    if analyze_candle(reordered) != first:
        return _fail('T36 key order must not change output')
    _pass('T36')

    lonely = analyze_candle(_candle(open=100, high=110, low=99, close=108))
    if lonely['schema_version'] != '53A':
        return _fail('T37 schema_version must be 53A')
    _pass('T37')

    src = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(src)
    for mod in ('requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser'):
        if mod in imported:
            return _fail(f'T38 network import {mod}')
    for needle in ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai'):
        if needle in src:
            return _fail(f'T38 AI needle {needle}')
    for needle in ('open(', 'write_text', 'write_bytes', 'atomic_write'):
        if needle in src:
            return _fail(f'T38 write path {needle}')
    _pass('T38')

    blob = json.dumps(first).lower()
    for token in FORBIDDEN_OUTPUT:
        if token in blob:
            return _fail(f'T39 output contains {token}')
    _pass('T39')

    if _git_data_status():
        return _fail('T40 data/ is not clean')
    _pass('T40')

    if list(first.keys()) != list(ANATOMY_KEYS):
        return _fail(f'T41 closed keys mismatch {list(first.keys())}')
    _pass('T41')

    constants = (
        DOJI_BODY_RATIO_MAX,
        STRONG_BODY_RATIO_MIN,
        LONG_WICK_RATIO_MIN,
        REJECTION_WICK_RATIO_MIN,
        REJECTION_BODY_RATIO_MAX,
        MARUBOZU_BODY_RATIO_MIN,
        MARUBOZU_WICK_RATIO_MAX,
        HAMMER_WICK_TO_BODY_MIN,
        HAMMER_OPPOSITE_WICK_TO_BODY_MAX,
    )
    if constants != (0.10, 0.60, 0.50, 0.60, 0.30, 0.90, 0.05, 2.0, 1.0):
        return _fail(f'T42 threshold constants drifted {constants}')
    _pass('T42')

    pos = analyze_candle(_candle(open=10, high=20, low=0, close=15))
    if pos['open_position'] != 0.5:
        return _fail(f'T43 open_position {pos["open_position"]}')
    _pass('T43')

    zero = analyze_candle(_candle(open=7, high=7, low=7, close=7, volume=1))
    if zero['body_ratio'] is not None or zero['shape_tags'] != []:
        return _fail('T44 zero-range must not emit ratios or tags')
    _pass('T44')

    malformed = analyze_candle(_candle(open=True, high=10, low=1, close=5))
    if malformed['anatomy_state'] != 'MALFORMED' or malformed['range'] is not None:
        return _fail('T45 bool OHLC must fail closed')
    src_lower = src.lower()
    for token in FORBIDDEN_OUTPUT:
        if token in src_lower:
            return _fail(f'T45 module source contains {token}')
    _pass('T45')
    return 0


def main() -> int:
    if _git_data_status():
        return _fail('repository data/ is not clean before tests')
    for fn in (
        test_t1_build,
        test_t2_t7_directions,
        test_t8_t18_shapes,
        test_t19_t21_ratios,
        test_t22_t33_fail_closed,
        test_t34_t45_contract,
    ):
        rc = fn()
        if rc:
            return rc
    if _git_data_status():
        return _fail('repository data/ mutated')
    required = [f'T{i}' for i in range(1, 46)]
    missing = [m for m in required if m not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers {missing}')
    print('CANDLE_ANATOMY_53A_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
