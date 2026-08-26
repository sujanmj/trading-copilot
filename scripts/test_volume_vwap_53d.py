#!/usr/bin/env python3
"""Focused tests for AstraEdge 53D deterministic volume and VWAP."""

from __future__ import annotations

import ast
import copy
import math
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

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'volume_vwap.py'
PASS_MARKERS: list[str] = []


def _fail(message: str) -> int:
    print(f'VOLUME_VWAP_53D_FAIL: {message}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


def _c(
    *,
    h: float,
    l: float,
    c: float | None = None,
    o: float | None = None,
    v: object = 10.0,
) -> dict:
    close = (h + l) / 2.0 if c is None else c
    open_ = close if o is None else o
    return {'open': open_, 'high': h, 'low': l, 'close': close, 'volume': v}


def _flat(volumes: list[object], *, h: float = 3.0, l: float = 1.0, c: float = 2.0) -> list[dict]:
    return [_c(h=h, l=l, c=c, v=volume) for volume in volumes]


def _analyze(candles):
    from backend.analysis.volume_vwap import analyze_volume_vwap

    return analyze_volume_vwap(candles)


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


def _emitted_strings(value) -> list[str]:
    if isinstance(value, dict):
        values = [str(key) for key in value]
        for item in value.values():
            values.extend(_emitted_strings(item))
        return values
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_emitted_strings(item))
        return values
    return [value] if isinstance(value, str) else []


def test_t1_t17_build_reuse_validation() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53D', 'AstraEdge 53D'),
        ('53E', 'AstraEdge 53E'),
        ('53E2', 'AstraEdge 53E2'),
    }:
        return _fail(f'T1 expected 53D or successor 53E/53E2 pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')

    source = MODULE_PATH.read_text(encoding='utf-8')
    if 'from backend.analysis.candle_anatomy import' not in source or 'analyze_candle' not in source:
        return _fail('T2 53A analyze_candle import/reuse missing')
    _pass('T2')

    if 'def analyze_candle(' in source or 'def _finite_number(' in source:
        return _fail('T3 53A OHLC analyzer was duplicated')
    _pass('T3')

    non_list = _analyze({'open': 1})
    if non_list['analysis_state'] != 'MALFORMED' or non_list['vwap_anchor_index'] is not None:
        return _fail(f'T4 non-list contract mismatch: {non_list}')
    _pass('T4')

    empty = _analyze([])
    if empty['analysis_state'] != 'INSUFFICIENT_CANDLES' or empty['vwap_anchor_index'] is not None:
        return _fail(f'T5 empty-list contract mismatch: {empty}')
    _pass('T5')

    import backend.analysis.volume_vwap as module

    with patch.object(module, 'analyze_candle') as analyzer:
        result = module.analyze_volume_vwap([])
    if analyzer.called or result['analysis_state'] != 'INSUFFICIENT_CANDLES':
        return _fail('T6 empty input evaluated candle anatomy')
    _pass('T6')

    malformed = [_c(h=3, l=1, c=4, v=10)]
    result = _analyze(malformed)
    if result['analysis_state'] != 'MALFORMED' or result['records']:
        return _fail(f'T7 malformed OHLC contract mismatch: {result}')
    if len(result['candle_anatomy']) != 1:
        return _fail('T7 malformed anatomy trace missing')
    _pass('T7')

    from backend.analysis.candle_anatomy import analyze_candle as real_analyze_candle

    supported = _flat([10, 20, 30])
    with patch.object(module, 'analyze_candle', wraps=real_analyze_candle) as analyzer:
        result = module.analyze_volume_vwap(supported)
    if result['analysis_state'] != 'OK' or analyzer.call_count != len(supported):
        return _fail(f'T8 every supported candle must use 53A, calls={analyzer.call_count}')
    _pass('T8')

    missing = _analyze([_c(h=3, l=1, v=None)])
    if missing['analysis_state'] != 'MISSING_VOLUME' or missing['records']:
        return _fail(f'T9 missing-volume state mismatch: {missing}')
    _pass('T9')

    if len(missing['candle_anatomy']) != 1 or missing['candle_anatomy'][0]['volume'] is not None:
        return _fail(f'T10 missing volume anatomy not preserved: {missing["candle_anatomy"]}')
    _pass('T10')

    invalid_cases = (
        (True, 'T11'),
        (-1, 'T12'),
        (float('nan'), 'T13'),
        (float('inf'), 'T14'),
    )
    for volume, marker in invalid_cases:
        invalid = _analyze([_c(h=3, l=1, v=volume)])
        if invalid['analysis_state'] != 'MALFORMED' or invalid['records']:
            return _fail(f'{marker} invalid volume was not rejected: {invalid}')
        _pass(marker)

    integer = _analyze([_c(h=3, l=1, v=7)])
    if integer['analysis_state'] != 'OK' or integer['records'][0]['volume'] != 7.0:
        return _fail(f'T15 integer volume mismatch: {integer}')
    _pass('T15')

    floating = _analyze([_c(h=3, l=1, v=7.5)])
    if floating['analysis_state'] != 'OK' or floating['records'][0]['volume'] != 7.5:
        return _fail(f'T16 float volume mismatch: {floating}')
    _pass('T16')

    zero = _analyze([_c(h=3, l=1, v=0)])
    if zero['analysis_state'] != 'OK' or zero['records'][0]['volume'] != 0.0:
        return _fail(f'T17 zero volume must remain valid: {zero}')
    _pass('T17')
    return 0


def test_t18_t31_vwap_math_and_relations() -> int:
    one = _analyze([_c(h=6, l=3, c=5, v=10)])
    record = one['records'][0]
    expected_typical = (6.0 + 3.0 + 5.0) / 3.0
    if record['typical_price'] != expected_typical:
        return _fail(f'T18 HLC3 mismatch: {record}')
    _pass('T18')

    if record['vwap'] != expected_typical:
        return _fail(f'T19 one-candle VWAP mismatch: {record}')
    _pass('T19')

    two_rows = [
        _c(h=3, l=1, c=2, v=10),
        _c(h=6, l=3, c=5, v=20),
    ]
    two = _analyze(two_rows)
    second = two['records'][1]
    expected_vwap = (2.0 * 10.0 + ((6.0 + 3.0 + 5.0) / 3.0) * 20.0) / 30.0
    if second['vwap'] != expected_vwap:
        return _fail(f'T20 cumulative VWAP mismatch: {second}')
    _pass('T20')

    if second['cumulative_volume'] != 30.0:
        return _fail(f'T21 cumulative volume mismatch: {second}')
    _pass('T21')

    all_zero = _analyze(_flat([0, 0, 0]))
    if any(row['vwap'] is not None for row in all_zero['records']):
        return _fail(f'T22 all-zero prefix invented VWAP: {all_zero["records"]}')
    _pass('T22')

    delayed = _analyze(_flat([0, 0, 5]))
    if any(row['vwap'] is not None for row in delayed['records'][:2]):
        return _fail(f'T23 pre-positive zero volume invented VWAP: {delayed["records"]}')
    _pass('T23')

    if delayed['records'][2]['vwap'] != 2.0:
        return _fail(f'T24 first positive candle did not establish VWAP: {delayed["records"][2]}')
    _pass('T24')

    zero_after = _analyze(_flat([5, 0]))
    if zero_after['records'][1]['vwap'] != zero_after['records'][0]['vwap']:
        return _fail(f'T25 later zero volume changed VWAP: {zero_after["records"]}')
    _pass('T25')

    if one['vwap_scope'] != 'SUPPLIED_WINDOW':
        return _fail(f'T26 VWAP scope mismatch: {one["vwap_scope"]}')
    _pass('T26')

    if one['vwap_anchor_index'] != 0:
        return _fail(f'T27 VWAP anchor mismatch: {one["vwap_anchor_index"]}')
    _pass('T27')

    above = _analyze([_c(h=10, l=0, c=9, v=10)])['records'][0]
    if above['vwap_relation'] != 'ABOVE_VWAP':
        return _fail(f'T28 above-VWAP relation mismatch: {above}')
    _pass('T28')

    below = _analyze([_c(h=10, l=0, c=1, v=10)])['records'][0]
    if below['vwap_relation'] != 'BELOW_VWAP':
        return _fail(f'T29 below-VWAP relation mismatch: {below}')
    _pass('T29')

    at = _analyze([_c(h=3, l=1, c=2, v=10)])['records'][0]
    if at['vwap_relation'] != 'AT_VWAP':
        return _fail(f'T30 at-VWAP relation mismatch: {at}')
    _pass('T30')

    undefined = all_zero['records'][0]
    if undefined['vwap_relation'] != 'UNDEFINED':
        return _fail(f'T31 undefined VWAP relation mismatch: {undefined}')
    _pass('T31')
    return 0


def test_t32_t40_crosses_and_distance() -> int:
    cross_above_rows = [
        _c(h=10, l=0, c=1, v=10),
        _c(h=20, l=10, c=19, v=10),
    ]
    cross_above = _analyze(cross_above_rows)
    if cross_above['records'][1]['event_tags'] != ['CROSS_ABOVE_VWAP']:
        return _fail(f'T32 cross-above mismatch: {cross_above["records"]}')
    _pass('T32')

    cross_below_rows = [
        _c(h=10, l=0, c=9, v=10),
        _c(h=5, l=0, c=1, v=10),
    ]
    cross_below = _analyze(cross_below_rows)
    if cross_below['records'][1]['event_tags'] != ['CROSS_BELOW_VWAP']:
        return _fail(f'T33 cross-below mismatch: {cross_below["records"]}')
    _pass('T33')

    undefined_previous = _analyze([
        _c(h=3, l=1, c=2, v=0),
        _c(h=10, l=0, c=9, v=10),
    ])
    if undefined_previous['records'][1]['event_tags']:
        return _fail(f'T34 undefined previous relation emitted cross: {undefined_previous["records"]}')
    _pass('T34')

    staying_above = _analyze(cross_above_rows + [_c(h=21, l=11, c=20, v=10)])
    if staying_above['records'][2]['vwap_relation'] != 'ABOVE_VWAP' or staying_above['records'][2]['event_tags']:
        return _fail(f'T35 repeated above cross emitted: {staying_above["records"]}')
    _pass('T35')

    staying_below = _analyze(cross_below_rows + [_c(h=4, l=0, c=0.5, v=10)])
    if staying_below['records'][2]['vwap_relation'] != 'BELOW_VWAP' or staying_below['records'][2]['event_tags']:
        return _fail(f'T36 repeated below cross emitted: {staying_below["records"]}')
    _pass('T36')

    from backend.analysis.volume_vwap import EVENT_TAG_ORDER

    if EVENT_TAG_ORDER != ('CROSS_ABOVE_VWAP', 'CROSS_BELOW_VWAP'):
        return _fail(f'T37 event-tag order mismatch: {EVENT_TAG_ORDER}')
    allowed = set(EVENT_TAG_ORDER)
    if any(not isinstance(row['event_tags'], list) or not set(row['event_tags']) <= allowed for row in staying_above['records']):
        return _fail('T37 event tags are not deterministic allowed lists')
    _pass('T37')

    above = _analyze([_c(h=10, l=0, c=9, v=10)])['records'][0]
    expected_distance = above['close'] - above['vwap']
    if above['vwap_distance'] != expected_distance:
        return _fail(f'T38 VWAP distance mismatch: {above}')
    _pass('T38')

    if above['vwap_distance_ratio'] != expected_distance / abs(above['vwap']):
        return _fail(f'T39 VWAP distance ratio mismatch: {above}')
    _pass('T39')

    zero_vwap = _analyze([_c(h=1, l=-1, c=0, v=10)])['records'][0]
    if zero_vwap['vwap'] != 0.0 or zero_vwap['vwap_distance_ratio'] is not None:
        return _fail(f'T40 zero VWAP distance-ratio mismatch: {zero_vwap}')
    _pass('T40')
    return 0


def test_t41_t51_volume_baselines() -> int:
    context = _analyze(_flat([10, 20, 30, 100]))
    if any(context['records'][index]['baseline_volume'] is not None for index in (1, 2)):
        return _fail(f'T41 early baseline exposed too soon: {context["records"]}')
    _pass('T41')

    fourth = context['records'][3]
    if fourth['baseline_sample_count'] != 3 or fourth['baseline_volume'] is None:
        return _fail(f'T42 third prior sample did not enable baseline: {fourth}')
    _pass('T42')

    if fourth['baseline_volume'] != 20.0:
        return _fail(f'T43 current candle contaminated baseline: {fourth}')
    _pass('T43')

    if fourth['baseline_volume'] != (10.0 + 20.0 + 30.0) / 3.0:
        return _fail(f'T44 arithmetic baseline mismatch: {fourth}')
    _pass('T44')

    long_result = _analyze(_flat(list(range(1, 27))))
    final = long_result['records'][25]
    expected_previous = list(range(6, 26))
    if final['baseline_volume'] != sum(expected_previous) / 20.0:
        return _fail(f'T45 baseline did not use previous indices 5..24: {final}')
    _pass('T45')

    if final['baseline_sample_count'] != 20:
        return _fail(f'T46 baseline sample count exceeded lookback: {final}')
    _pass('T46')

    ratio = _analyze(_flat([10, 10, 10, 12]))['records'][3]
    if ratio['volume_ratio'] != 1.2:
        return _fail(f'T47 exact volume ratio mismatch: {ratio}')
    _pass('T47')

    high = _analyze(_flat([10, 10, 10, 15]))['records'][3]
    if high['volume_ratio'] != 1.5 or high['volume_state'] != 'HIGH_VOLUME':
        return _fail(f'T48 inclusive high threshold mismatch: {high}')
    _pass('T48')

    low = _analyze(_flat([10, 10, 10, 5]))['records'][3]
    if low['volume_ratio'] != 0.5 or low['volume_state'] != 'LOW_VOLUME':
        return _fail(f'T49 inclusive low threshold mismatch: {low}')
    _pass('T49')

    normal = _analyze(_flat([10, 10, 10, 10]))['records'][3]
    if normal['volume_ratio'] != 1.0 or normal['volume_state'] != 'NORMAL_VOLUME':
        return _fail(f'T50 normal volume classification mismatch: {normal}')
    _pass('T50')

    zero_baseline = _analyze(_flat([0, 0, 0, 5]))['records'][3]
    if zero_baseline['baseline_volume'] != 0.0 or zero_baseline['volume_ratio'] is not None:
        return _fail(f'T51 zero baseline division guard mismatch: {zero_baseline}')
    if zero_baseline['volume_state'] != 'UNDEFINED':
        return _fail(f'T51 zero baseline state mismatch: {zero_baseline}')
    _pass('T51')
    return 0


def test_t52_t62_latest_determinism_and_source() -> int:
    candles = _flat([10, 10, 10, 15])
    result = _analyze(candles)
    latest = result['records'][-1]
    if result['latest_vwap'] != latest['vwap']:
        return _fail('T52 latest_vwap differs from final record')
    _pass('T52')

    if result['latest_vwap_relation'] != latest['vwap_relation']:
        return _fail('T53 latest_vwap_relation differs from final record')
    _pass('T53')

    if result['latest_volume_ratio'] != latest['volume_ratio']:
        return _fail('T54 latest_volume_ratio differs from final record')
    _pass('T54')

    if result['latest_volume_state'] != latest['volume_state']:
        return _fail('T55 latest_volume_state differs from final record')
    _pass('T55')

    before = copy.deepcopy(candles)
    _analyze(candles)
    if candles != before:
        return _fail('T56 analyzer mutated input')
    _pass('T56')

    if _analyze(candles) != result:
        return _fail('T57 same input did not produce exact output')
    _pass('T57')

    reordered = [
        {
            'volume': row['volume'],
            'close': row['close'],
            'low': row['low'],
            'high': row['high'],
            'open': row['open'],
        }
        for row in candles
    ]
    if _analyze(reordered) != result:
        return _fail('T58 candle dictionary key order changed output')
    _pass('T58')

    from backend.analysis.volume_vwap import OUTPUT_KEYS, RECORD_KEYS

    if tuple(result.keys()) != OUTPUT_KEYS:
        return _fail(f'T59 top-level keys are not closed: {tuple(result.keys())}')
    _pass('T59')

    if any(tuple(row.keys()) != RECORD_KEYS for row in result['records']):
        return _fail('T60 record keys are not closed')
    _pass('T60')

    forbidden = {
        'BUY', 'SELL', 'LONG', 'SHORT', 'ENTRY', 'STOP', 'TARGET',
        'POSITION SIZE', 'TRADE SIGNAL', 'WIN PROBABILITY', 'CONFIDENCE',
        'RECOMMENDATION', 'STRONG BUY', 'STRONG SELL',
    }
    emitted = {value.strip().upper() for value in _emitted_strings(result)}
    found = sorted(forbidden & emitted)
    if found:
        return _fail(f'T61 forbidden interpretation output: {found}')
    _pass('T61')

    import backend.analysis.volume_vwap as module

    anatomy = {
        'anatomy_state': 'OK',
        'high': 3.0,
        'low': 1.0,
        'close': 2.0,
        'volume': 7.0,
    }
    raw = [_c(h=30, l=10, c=20, v=999)]
    with patch.object(module, 'analyze_candle', return_value=anatomy):
        projected = module.analyze_volume_vwap(raw)
    if projected['records'][0]['volume'] != 7.0 or projected['records'][0]['typical_price'] != 2.0:
        return _fail(f'T62 record did not originate from 53A anatomy: {projected}')
    _pass('T62')
    return 0


def test_t63_t71_protected_and_effect_boundaries() -> int:
    protected = (
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
        'backend/analysis/price_action_structure.py',
        'backend/analysis/key_levels_supply_demand.py',
    )
    for marker, path in zip(('T63', 'T64', 'T65', 'T66'), protected):
        if _git_names('diff', '--name-only', 'HEAD', '--', path):
            return _fail(f'{marker} protected analysis module changed: {path}')
        _pass(marker)

    source = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(source)
    network = {'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser'}
    if imported & network:
        return _fail(f'T67 network import found: {sorted(imported & network)}')
    _pass('T67')

    if any(needle in source.lower() for needle in ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai')):
        return _fail('T68 AI dependency found')
    _pass('T68')

    if any(needle in source for needle in ('write_text', 'write_bytes', 'atomic_write', 'open(')):
        return _fail('T69 write/file path found')
    _pass('T69')

    forbidden_dependencies = ('backend.news', 'backend.collectors', 'backend.trading', 'broker', 'telegram', 'freshness')
    if any(needle in source.lower() for needle in forbidden_dependencies):
        return _fail('T70 broker/news/freshness dependency found')
    _pass('T70')

    if _git_names('status', '--short', '--', 'data'):
        return _fail('T71 repository data/ is dirty')
    _pass('T71')
    return 0


def test_t72_t77_lookahead_and_successor_scope() -> int:
    prefix_rows = [
        _c(h=3, l=1, c=2, v=10),
        _c(h=10, l=0, c=9, v=20),
        _c(h=5, l=0, c=1, v=30),
        _c(h=6, l=2, c=5, v=40),
    ]
    prefix = _analyze(prefix_rows)
    extension = prefix_rows + [
        _c(h=100, l=80, c=99, v=1000),
        _c(h=2, l=-2, c=-1, v=0),
    ]
    extended = _analyze(extension)
    if prefix['records'] != extended['records'][:len(prefix_rows)]:
        return _fail('T72 future candles changed prefix records')
    _pass('T72')

    future_price_a = prefix_rows + [_c(h=10, l=5, c=8, v=50)]
    future_price_b = prefix_rows + [_c(h=1000, l=500, c=800, v=50)]
    if _analyze(future_price_a)['records'][:4] != _analyze(future_price_b)['records'][:4]:
        return _fail('T73 changing future price changed earlier records')
    _pass('T73')

    future_volume_a = prefix_rows + [_c(h=10, l=5, c=8, v=1)]
    future_volume_b = prefix_rows + [_c(h=10, l=5, c=8, v=1000000)]
    if _analyze(future_volume_a)['records'][:4] != _analyze(future_volume_b)['records'][:4]:
        return _fail('T74 changing future volume changed earlier records')
    _pass('T74')

    zero_future = _analyze(prefix_rows + [_c(h=100, l=0, c=99, v=0)])
    if zero_future['records'][:4] != prefix['records']:
        return _fail('T75 future zero-volume candle changed previous VWAP records')
    _pass('T75')

    current_small = _analyze(_flat([10, 20, 30, 1]))['records'][3]
    current_large = _analyze(_flat([10, 20, 30, 1000000]))['records'][3]
    if current_small['baseline_volume'] != current_large['baseline_volume']:
        return _fail('T76 current volume participated in its own baseline')
    if current_small['baseline_sample_count'] != current_large['baseline_sample_count']:
        return _fail('T76 current volume changed its own baseline count')
    _pass('T76')

    expected_historical = {
        'scripts/test_multi_timeframe_53e.py',
        'scripts/validate_multi_timeframe_53e.py',
        'scripts/test_volume_vwap_53d.py',
        'scripts/validate_volume_vwap_53d.py',
        'scripts/test_key_levels_supply_demand_53c.py',
        'scripts/validate_key_levels_supply_demand_53c.py',
        'scripts/test_price_action_structure_53b.py',
        'scripts/validate_price_action_structure_53b.py',
        'scripts/test_candlestick_patterns_53a2.py',
        'scripts/validate_candlestick_patterns_53a2.py',
        'scripts/test_candle_anatomy_53a.py',
        'scripts/validate_candle_anatomy_53a.py',
        'scripts/test_event_age_freshness_52r_d2.py',
        'scripts/validate_event_age_freshness_52r_d2.py',
    }
    changed_scripts = set(_git_names('diff', '--name-only', 'HEAD', '--', 'scripts'))
    if changed_scripts != expected_historical:
        return _fail(f'T77 predecessor compatibility scope mismatch: {sorted(changed_scripts)}')
    _pass('T77')
    return 0


def main() -> int:
    tests = (
        test_t1_t17_build_reuse_validation,
        test_t18_t31_vwap_math_and_relations,
        test_t32_t40_crosses_and_distance,
        test_t41_t51_volume_baselines,
        test_t52_t62_latest_determinism_and_source,
        test_t63_t71_protected_and_effect_boundaries,
        test_t72_t77_lookahead_and_successor_scope,
    )
    for test in tests:
        result = test()
        if result:
            return result

    expected = tuple(f'T{index}' for index in range(1, 78))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('VOLUME_VWAP_53D_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
