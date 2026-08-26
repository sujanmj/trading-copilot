#!/usr/bin/env python3
"""Focused tests for AstraEdge 53B deterministic price-action structure."""

from __future__ import annotations

import ast
import copy
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

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'price_action_structure.py'
PASS_MARKERS: list[str] = []


def _fail(message: str) -> int:
    print(f'PRICE_ACTION_STRUCTURE_53B_FAIL: {message}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


def _c(*, h: float, l: float, c: float | None = None, o: float | None = None) -> dict:
    close = (h + l) / 2.0 if c is None else c
    open_ = close if o is None else o
    return {'open': open_, 'high': h, 'low': l, 'close': close}


def _series(
    highs: list[float],
    lows: list[float],
    closes: list[float] | None = None,
) -> list[dict]:
    if len(highs) != len(lows):
        raise ValueError('high/low fixture lengths differ')
    if closes is not None and len(closes) != len(highs):
        raise ValueError('close fixture length differs')
    return [
        _c(h=high, l=lows[index], c=None if closes is None else closes[index])
        for index, high in enumerate(highs)
    ]


def _analyze(candles):
    from backend.analysis.price_action_structure import analyze_price_action_structure

    return analyze_price_action_structure(candles)


def _swings(result: dict, kind: str) -> list[dict]:
    return [row for row in result['swing_points'] if row['kind'] == kind]


def _events(result: dict, direction: str | None = None) -> list[dict]:
    rows = result['break_events']
    if direction is None:
        return rows
    return [row for row in rows if row['direction'] == direction]


def _basic_high() -> list[dict]:
    return _series(
        [6, 8, 10, 8, 7],
        [4, 5, 6, 5, 4],
    )


def _basic_low() -> list[dict]:
    return _series(
        [7, 6, 5, 6, 7],
        [5, 4, 2, 4, 5],
    )


def _high_relation(second: float) -> list[dict]:
    return _series(
        [6, 8, 10, 7, 6, second, 7, 6],
        [0, 0, 0, 0, 0, 0, 0, 0],
    )


def _low_relation(second: float) -> list[dict]:
    return _series(
        [12, 12, 12, 12, 12, 12, 12, 12],
        [8, 7, 2, 7, 8, second, 8, 7],
    )


def _bullish_base() -> list[dict]:
    return _series(
        [6, 8, 10, 8, 7, 9, 12, 10, 9, 10, 11],
        [5, 6, 7, 5, 2, 5, 7, 6, 4, 6, 7],
    )


def _bearish_base() -> list[dict]:
    return _series(
        [6, 8, 10, 8, 6, 7, 8, 7, 6, 7, 8],
        [5, 6, 7, 5, 2, 4, 4, 3, 1, 3, 4],
    )


def _mixed_base() -> list[dict]:
    return _series(
        [6, 8, 10, 8, 7, 9, 12, 10, 9, 10, 11],
        [5, 6, 7, 5, 2, 5, 7, 4, 1, 4, 5],
    )


def _extended_bias_change() -> tuple[list[dict], list[dict]]:
    prefix = _bullish_base() + [_c(h=9, l=3, c=3)]
    extended = prefix + [
        _c(h=8, l=1.5, c=2),
        _c(h=9, l=4, c=6),
        _c(h=10, l=5, c=7),
        _c(h=9, l=4, c=6),
        _c(h=8, l=3.5, c=5),
    ]
    return prefix, extended


def _imported_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                names.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            names.add(module)
            names.add(module.split('.')[0])
    return names


def _git_names(*args: str) -> list[str]:
    proc = subprocess.run(
        ['git', *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or 'git command failed')
    return [line.strip().replace('\\', '/') for line in (proc.stdout or '').splitlines() if line.strip()]


def test_t1_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53B', 'AstraEdge 53B'),
        ('53C', 'AstraEdge 53C'),
        ('53D', 'AstraEdge 53D'),
        ('53E', 'AstraEdge 53E'),
        ('53E2', 'AstraEdge 53E2'),
        ('53F', 'AstraEdge 53F'),
        ('53G', 'AstraEdge 53G'),
    }:
        return _fail(f'T1 expected 53B or successor 53C/53D/53E/53E2/53F/53G pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')
    return 0


def test_t2_t8_confirmed_swings() -> int:
    high_result = _analyze(_basic_high())
    highs = _swings(high_result, 'HIGH')
    if [(row['index'], row['price']) for row in highs] != [(2, 10.0)]:
        return _fail(f'T2 basic swing high mismatch: {highs}')
    _pass('T2')

    low_result = _analyze(_basic_low())
    lows = _swings(low_result, 'LOW')
    if [(row['index'], row['price']) for row in lows] != [(2, 2.0)]:
        return _fail(f'T3 basic swing low mismatch: {lows}')
    _pass('T3')

    high_tie = _analyze(_series([6, 8, 10, 10, 7], [4, 5, 6, 6, 4]))
    if _swings(high_tie, 'HIGH'):
        return _fail(f'T4 equal neighborhood highs must not pivot: {high_tie["swing_points"]}')
    _pass('T4')

    low_tie = _analyze(_series([8, 7, 6, 6, 8], [5, 4, 2, 2, 5]))
    if _swings(low_tie, 'LOW'):
        return _fail(f'T5 equal neighborhood lows must not pivot: {low_tie["swing_points"]}')
    _pass('T5')

    final_extremes = _analyze(_series(
        [6, 7, 9, 7, 6, 20, 30],
        [5, 6, 7, 6, 5, 0, -10],
    ))
    if any(row['index'] >= 5 for row in final_extremes['swing_points']):
        return _fail(f'T6 final two candles cannot be confirmed pivots: {final_extremes["swing_points"]}')
    _pass('T6')

    if highs[0]['confirmed_at_index'] != highs[0]['index'] + 2:
        return _fail(f'T7 confirmation lag mismatch: {highs[0]}')
    _pass('T7')

    delayed_rows = _series([5, 6, 7, 10, 7, 6], [4, 4, 4, 5, 4, 4])
    before = _analyze(delayed_rows[:5])
    after = _analyze(delayed_rows)
    if any(row['swing_id'] == 'HIGH:3' for row in before['swing_points']):
        return _fail('T8 pivot leaked before its confirmation candle')
    delayed = [row for row in after['swing_points'] if row['swing_id'] == 'HIGH:3']
    if len(delayed) != 1 or delayed[0]['confirmed_at_index'] != 5:
        return _fail(f'T8 pivot missing at confirmation: {after["swing_points"]}')
    _pass('T8')
    return 0


def test_t9_t16_relations() -> int:
    first_high = _swings(_analyze(_basic_high()), 'HIGH')[0]
    if first_high['relation'] != 'FIRST_HIGH':
        return _fail(f'T9 first high relation mismatch: {first_high}')
    _pass('T9')

    cases = ((12, 'HIGHER_HIGH', 'T10'), (8, 'LOWER_HIGH', 'T11'), (10, 'EQUAL_HIGH', 'T12'))
    for price, relation, marker in cases:
        highs = _swings(_analyze(_high_relation(price)), 'HIGH')
        if len(highs) != 2 or highs[-1]['relation'] != relation:
            return _fail(f'{marker} expected {relation}, got {highs}')
        _pass(marker)

    first_low = _swings(_analyze(_basic_low()), 'LOW')[0]
    if first_low['relation'] != 'FIRST_LOW':
        return _fail(f'T13 first low relation mismatch: {first_low}')
    _pass('T13')

    low_cases = ((4, 'HIGHER_LOW', 'T14'), (1, 'LOWER_LOW', 'T15'), (2, 'EQUAL_LOW', 'T16'))
    for price, relation, marker in low_cases:
        lows = _swings(_analyze(_low_relation(price)), 'LOW')
        if len(lows) != 2 or lows[-1]['relation'] != relation:
            return _fail(f'{marker} expected {relation}, got {lows}')
        _pass(marker)
    return 0


def test_t17_t20_structure_bias() -> int:
    bullish = _analyze(_bullish_base())
    if bullish['structure_bias'] != 'BULLISH':
        return _fail(f'T17 expected bullish HH+HL structure, got {bullish["structure_bias"]}')
    _pass('T17')

    bearish = _analyze(_bearish_base())
    if bearish['structure_bias'] != 'BEARISH':
        return _fail(f'T18 expected bearish LH+LL structure, got {bearish["structure_bias"]}')
    _pass('T18')

    mixed = _analyze(_mixed_base())
    if mixed['structure_bias'] != 'MIXED':
        return _fail(f'T19 expected mixed HH+LL structure, got {mixed["structure_bias"]}')
    _pass('T19')

    undefined = _analyze(_basic_high())
    if undefined['structure_bias'] != 'UNDEFINED':
        return _fail(f'T20 one-sided swing history must be undefined, got {undefined["structure_bias"]}')
    _pass('T20')
    return 0


def test_t21_t25_raw_breaks() -> int:
    above_rows = _basic_high() + [_c(h=11, l=5, c=10.5)]
    above = _events(_analyze(above_rows), 'ABOVE')
    if len(above) != 1 or above[0]['reference_swing_id'] != 'HIGH:2':
        return _fail(f'T21 close-confirmed break above mismatch: {above}')
    _pass('T21')

    wick_above = _events(_analyze(_basic_high() + [_c(h=11, l=5, c=9.5)]), 'ABOVE')
    if wick_above:
        return _fail(f'T22 wick-only high penetration must not break: {wick_above}')
    _pass('T22')

    below_rows = _basic_low() + [_c(h=5, l=1, c=1.5)]
    below = _events(_analyze(below_rows), 'BELOW')
    if len(below) != 1 or below[0]['reference_swing_id'] != 'LOW:2':
        return _fail(f'T23 close-confirmed break below mismatch: {below}')
    _pass('T23')

    wick_below = _events(_analyze(_basic_low() + [_c(h=5, l=1, c=2.5)]), 'BELOW')
    if wick_below:
        return _fail(f'T24 wick-only low penetration must not break: {wick_below}')
    _pass('T24')

    repeated_rows = above_rows + [
        _c(h=12, l=5, c=9),
        _c(h=11, l=5, c=10.5),
    ]
    repeated = [
        row for row in _events(_analyze(repeated_rows), 'ABOVE')
        if row['reference_swing_id'] == 'HIGH:2'
    ]
    if len(repeated) != 1:
        return _fail(f'T25 a swing reference must break only once: {repeated}')
    _pass('T25')
    return 0


def test_t26_t30_bos_choch() -> int:
    bullish_above = _events(_analyze(_bullish_base() + [_c(h=14, l=8, c=13)]), 'ABOVE')
    if not bullish_above or bullish_above[-1]['event_tags'] != [
        'BREAK_ABOVE_SWING_HIGH', 'BULLISH_BOS_LIKE',
    ]:
        return _fail(f'T26 bullish continuation tags mismatch: {bullish_above}')
    _pass('T26')

    bearish_below = _events(_analyze(_bearish_base() + [_c(h=6, l=0, c=0.5)]), 'BELOW')
    if not bearish_below or bearish_below[-1]['event_tags'] != [
        'BREAK_BELOW_SWING_LOW', 'BEARISH_BOS_LIKE',
    ]:
        return _fail(f'T27 bearish continuation tags mismatch: {bearish_below}')
    _pass('T27')

    bearish_above = _events(_analyze(_bearish_base() + [_c(h=9, l=5, c=8.5)]), 'ABOVE')
    if not bearish_above or bearish_above[-1]['event_tags'] != [
        'BREAK_ABOVE_SWING_HIGH', 'BULLISH_CHOCH_LIKE',
    ]:
        return _fail(f'T28 bearish-to-bullish change tags mismatch: {bearish_above}')
    _pass('T28')

    bullish_below = _events(_analyze(_bullish_base() + [_c(h=8, l=3, c=3)]), 'BELOW')
    if not bullish_below or bullish_below[-1]['event_tags'] != [
        'BREAK_BELOW_SWING_LOW', 'BEARISH_CHOCH_LIKE',
    ]:
        return _fail(f'T29 bullish-to-bearish change tags mismatch: {bullish_below}')
    _pass('T29')

    raw = _events(_analyze(_basic_high() + [_c(h=11, l=5, c=10.5)]), 'ABOVE')
    if not raw or raw[-1]['structure_bias_before'] != 'UNDEFINED':
        return _fail(f'T30 undefined raw break bias mismatch: {raw}')
    if raw[-1]['event_tags'] != ['BREAK_ABOVE_SWING_HIGH']:
        return _fail(f'T30 undefined break must have only raw tag: {raw[-1]}')
    mixed_raw = _events(_analyze(_mixed_base() + [_c(h=14, l=7, c=13)]), 'ABOVE')
    if not mixed_raw or mixed_raw[-1]['structure_bias_before'] != 'MIXED':
        return _fail(f'T30 mixed raw break bias mismatch: {mixed_raw}')
    if mixed_raw[-1]['event_tags'] != ['BREAK_ABOVE_SWING_HIGH']:
        return _fail(f'T30 mixed break must have only raw tag: {mixed_raw[-1]}')
    _pass('T30')
    return 0


def test_t31_t37_order_and_failures() -> int:
    chronological = _basic_high() + [_c(h=11, l=5, c=10.5)]
    if _analyze(chronological) == _analyze(list(reversed(chronological))):
        return _fail('T31 chronological reversal must change structure facts')
    _pass('T31')

    outside = _analyze(_series([6, 8, 12, 8, 6], [4, 3, 0, 3, 4]))
    both = [row for row in outside['swing_points'] if row['index'] == 2]
    if [row['kind'] for row in both] != ['HIGH', 'LOW']:
        return _fail(f'T32 same candle must retain HIGH then LOW: {both}')
    _pass('T32')

    zero = _analyze([_c(h=5, l=5) for _ in range(5)])
    if zero['structure_state'] != 'OK' or zero['swing_points'] or zero['break_events']:
        return _fail(f'T33 ZERO_RANGE series must remain safe: {zero}')
    if any(row['anatomy_state'] != 'ZERO_RANGE' for row in zero['candle_anatomy']):
        return _fail('T33 ZERO_RANGE anatomy records were not preserved')
    _pass('T33')

    insufficient = _analyze(_basic_high()[:4])
    if insufficient['structure_state'] != 'INSUFFICIENT_CANDLES':
        return _fail(f'T34 four valid candles must be insufficient: {insufficient}')
    if insufficient['candle_anatomy'] != []:
        return _fail('T34 cardinality must precede anatomy')
    _pass('T34')

    malformed_short = _basic_high()[:4]
    malformed_short[0]['open'] = True
    insufficient_malformed = _analyze(malformed_short)
    if insufficient_malformed['structure_state'] != 'INSUFFICIENT_CANDLES':
        return _fail(f'T35 short malformed list must remain insufficient: {insufficient_malformed}')
    if insufficient_malformed['candle_anatomy'] != []:
        return _fail('T35 short malformed list must not run anatomy')
    _pass('T35')

    malformed_supported = _basic_high()
    malformed_supported[1]['open'] = True
    malformed = _analyze(malformed_supported)
    if malformed['structure_state'] != 'MALFORMED':
        return _fail(f'T36 supported malformed series must be malformed: {malformed}')
    if malformed['swing_points'] or malformed['break_events'] or len(malformed['candle_anatomy']) != 5:
        return _fail(f'T36 malformed envelope mismatch: {malformed}')
    _pass('T36')

    non_list = _analyze({'open': 1})
    if non_list['structure_state'] != 'MALFORMED' or non_list['candle_count'] != 0:
        return _fail(f'T37 non-list must be malformed: {non_list}')
    _pass('T37')
    return 0


def test_t38_t43_determinism_and_closed_contract() -> int:
    original = _bullish_base() + [_c(h=14, l=8, c=13)]
    before = copy.deepcopy(original)
    first = _analyze(original)
    if original != before:
        return _fail('T38 analyzer mutated input')
    _pass('T38')

    if _analyze(original) != first:
        return _fail('T39 same input did not produce exact same output')
    _pass('T39')

    reordered = [
        {'close': row['close'], 'low': row['low'], 'high': row['high'], 'open': row['open']}
        for row in original
    ]
    if _analyze(reordered) != first:
        return _fail('T40 dictionary key ordering changed output')
    _pass('T40')

    outside = _analyze(_series([6, 8, 12, 8, 6], [4, 3, 0, 3, 4]))
    if [(row['index'], row['kind']) for row in outside['swing_points']] != [(2, 'HIGH'), (2, 'LOW')]:
        return _fail(f'T41 swing ordering mismatch: {outside["swing_points"]}')
    _pass('T41')

    bos_event = _events(first, 'ABOVE')[-1]
    if bos_event['event_tags'] != ['BREAK_ABOVE_SWING_HIGH', 'BULLISH_BOS_LIKE']:
        return _fail(f'T42 event-tag order mismatch: {bos_event}')
    _pass('T42')

    from backend.analysis.price_action_structure import (
        BREAK_EVENT_KEYS,
        STRUCTURE_KEYS,
        SWING_KEYS,
    )

    if tuple(first.keys()) != STRUCTURE_KEYS:
        return _fail(f'T43 output keys are not closed: {tuple(first.keys())}')
    if any(tuple(row.keys()) != SWING_KEYS for row in first['swing_points']):
        return _fail('T43 swing record keys are not closed')
    if any(tuple(row.keys()) != BREAK_EVENT_KEYS for row in first['break_events']):
        return _fail('T43 break record keys are not closed')
    _pass('T43')
    return 0


def test_t44_t51_boundaries() -> int:
    import backend.analysis.price_action_structure as module
    from backend.analysis.candle_anatomy import analyze_candle as real_analyze_candle

    with patch.object(module, 'analyze_candle', wraps=real_analyze_candle) as analyzer:
        result = module.analyze_price_action_structure(_basic_high())
    if result['structure_state'] != 'OK' or analyzer.call_count != 5:
        return _fail(f'T44 every supported candle must pass through 53A, calls={analyzer.call_count}')
    source = MODULE_PATH.read_text(encoding='utf-8')
    if 'from backend.analysis.candle_anatomy import' not in source or 'def analyze_candle(' in source:
        return _fail('T44 53A reuse contract missing')
    _pass('T44')

    if _git_names('diff', '--name-only', 'HEAD', '--', 'backend/analysis/candle_anatomy.py'):
        return _fail('T45 candle_anatomy.py changed')
    _pass('T45')

    if _git_names('diff', '--name-only', 'HEAD', '--', 'backend/analysis/candlestick_patterns.py'):
        return _fail('T46 candlestick_patterns.py changed')
    _pass('T46')

    imported = _imported_names(source)
    for name in ('requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser'):
        if name in imported:
            return _fail(f'T47 network import found: {name}')
    _pass('T47')

    for needle in ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai'):
        if needle in source.lower():
            return _fail(f'T48 AI dependency found: {needle}')
    _pass('T48')

    for needle in ('write_text', 'write_bytes', 'atomic_write', 'open('):
        if needle in source:
            return _fail(f'T49 write/file path found: {needle}')
    _pass('T49')

    for needle in ('backend.news', 'backend.collectors', 'broker', 'telegram', 'freshness'):
        if needle in source.lower():
            return _fail(f'T50 forbidden external dependency found: {needle}')
    _pass('T50')

    if _git_names('status', '--short', '--', 'data'):
        return _fail('T51 repository data/ is dirty')
    _pass('T51')
    return 0


def test_t52_t55_lookahead_and_timing() -> int:
    prefix, extended_rows = _extended_bias_change()
    prefix_result = _analyze(prefix)
    extended = _analyze(extended_rows)
    cutoff = len(prefix) - 1
    earlier_events = [row for row in extended['break_events'] if row['index'] <= cutoff]
    if earlier_events != prefix_result['break_events']:
        return _fail(
            f'T52 later candles changed earlier decisions: prefix={prefix_result["break_events"]} '
            f'extended={earlier_events}'
        )
    _pass('T52')

    bullish = _analyze(_bullish_base())
    highs = _swings(bullish, 'HIGH')
    lows = _swings(bullish, 'LOW')
    if [row['relation'] for row in highs] != ['FIRST_HIGH', 'HIGHER_HIGH']:
        return _fail(f'T53 high relation stream contaminated: {highs}')
    if [row['relation'] for row in lows] != ['FIRST_LOW', 'HIGHER_LOW']:
        return _fail(f'T53 low relation stream contaminated: {lows}')
    _pass('T53')

    event = [row for row in extended['break_events'] if row['index'] == cutoff]
    if len(event) != 1 or event[0]['structure_bias_before'] != 'BULLISH':
        return _fail(f'T54 event-time bias mismatch: {event}')
    if event[0]['event_tags'] != ['BREAK_BELOW_SWING_LOW', 'BEARISH_CHOCH_LIKE']:
        return _fail(f'T54 event-time classification mismatch: {event[0]}')
    if extended['structure_bias'] != 'BEARISH':
        return _fail(f'T54 fixture must finish bearish, got {extended["structure_bias"]}')
    _pass('T54')

    last_index = len(extended_rows) - 1
    if any(row['confirmed_at_index'] > last_index for row in extended['swing_points']):
        return _fail('T55 final bias used an unconfirmed swing')
    if any(row['index'] > last_index - 2 for row in extended['swing_points']):
        return _fail('T55 final two candles were emitted as pivots')
    final_highs = _swings(extended, 'HIGH')
    final_lows = _swings(extended, 'LOW')
    if final_highs[-1]['relation'] != 'LOWER_HIGH' or final_lows[-1]['relation'] != 'LOWER_LOW':
        return _fail(f'T55 final confirmed relation pair mismatch: {final_highs[-1]} / {final_lows[-1]}')
    if extended['structure_bias'] != 'BEARISH':
        return _fail('T55 final bias was not derived from the final confirmed relation pair')
    _pass('T55')
    return 0


def main() -> int:
    tests = (
        test_t1_build_identity,
        test_t2_t8_confirmed_swings,
        test_t9_t16_relations,
        test_t17_t20_structure_bias,
        test_t21_t25_raw_breaks,
        test_t26_t30_bos_choch,
        test_t31_t37_order_and_failures,
        test_t38_t43_determinism_and_closed_contract,
        test_t44_t51_boundaries,
        test_t52_t55_lookahead_and_timing,
    )
    for test in tests:
        result = test()
        if result:
            return result

    expected = tuple(f'T{index}' for index in range(1, 56))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('PRICE_ACTION_STRUCTURE_53B_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
