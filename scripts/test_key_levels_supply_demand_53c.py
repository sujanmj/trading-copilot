#!/usr/bin/env python3
"""Focused tests for AstraEdge 53C deterministic key levels and zones."""

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

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'key_levels_supply_demand.py'
PASS_MARKERS: list[str] = []


def _fail(message: str) -> int:
    print(f'KEY_LEVELS_SUPPLY_DEMAND_53C_FAIL: {message}', file=sys.stderr)
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


def _basic_high() -> list[dict]:
    return _series([6, 8, 10, 8, 7], [4, 5, 6, 5, 4])


def _basic_low() -> list[dict]:
    return _series([7, 6, 5, 6, 7], [5, 4, 2, 4, 5])


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


def _outside_candle() -> list[dict]:
    return _series([6, 8, 12, 8, 6], [4, 3, 0, 3, 4])


def _analyze(candles):
    from backend.analysis.key_levels_supply_demand import analyze_key_levels

    return analyze_key_levels(candles)


def _levels(result: dict, kind: str | None = None) -> list[dict]:
    rows = result['key_levels']
    return rows if kind is None else [row for row in rows if row['kind'] == kind]


def _zones(result: dict, kind: str | None = None) -> list[dict]:
    rows = result['zones']
    return rows if kind is None else [row for row in rows if row['kind'] == kind]


def _swing(
    index: int,
    kind: str,
    price: float,
    *,
    relation: str | None = None,
) -> dict:
    if relation is None:
        relation = 'FIRST_HIGH' if kind == 'HIGH' else 'FIRST_LOW'
    return {
        'swing_id': f'{kind}:{index}',
        'index': index,
        'kind': kind,
        'price': price,
        'confirmed_at_index': index + 2,
        'relation': relation,
    }


def _source(
    swings: list[dict],
    *,
    breaks: list[dict] | None = None,
    bias: str = 'UNDEFINED',
    anatomy: list[dict] | None = None,
    candle_count: int | None = None,
) -> dict:
    maximum = max((row['confirmed_at_index'] for row in swings), default=4)
    count = max(5, maximum + 1) if candle_count is None else candle_count
    if anatomy is None:
        anatomy = [
            {'open': 0.0, 'high': 1.0, 'low': -1.0, 'close': 0.0}
            for _ in range(count)
        ]
        by_index: dict[int, list[dict]] = {}
        for swing in swings:
            by_index.setdefault(swing['index'], []).append(swing)
        for index, rows in by_index.items():
            highs = [row['price'] for row in rows if row['kind'] == 'HIGH']
            lows = [row['price'] for row in rows if row['kind'] == 'LOW']
            if highs and lows:
                high = max(highs)
                low = min(lows)
                middle = (high + low) / 2.0
            elif highs:
                high = max(highs)
                low = high - 2.0
                middle = high - 1.0
            else:
                low = min(lows)
                high = low + 2.0
                middle = low + 1.0
            anatomy[index] = {'open': middle, 'high': high, 'low': low, 'close': middle}
    return {
        'schema_version': '53B',
        'structure_state': 'OK',
        'candle_count': count,
        'swing_span': 2,
        'structure_bias': bias,
        'swing_points': copy.deepcopy(swings),
        'break_events': copy.deepcopy(breaks or []),
        'candle_anatomy': copy.deepcopy(anatomy),
    }


def _group_source(prices: list[float], *, kind: str = 'HIGH') -> dict:
    swings = [
        _swing(index=2 + position * 3, kind=kind, price=price)
        for position, price in enumerate(prices)
    ]
    return _source(swings)


def _with_source(source: dict) -> dict:
    import backend.analysis.key_levels_supply_demand as module

    candles = [{} for _ in range(source['candle_count'])]
    with patch.object(module, 'analyze_price_action_structure', return_value=source):
        return module.analyze_key_levels(candles)


def _group_for_level(result: dict, level_id: str) -> str | None:
    for group in result['level_groups']:
        if level_id in group['member_level_ids']:
            return group['group_id']
    return None


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


def test_t1_t8_build_reuse_and_failures() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53C', 'AstraEdge 53C'),
        ('53D', 'AstraEdge 53D'),
        ('53E', 'AstraEdge 53E'),
    }:
        return _fail(f'T1 expected 53C or successor 53D/53E pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')

    import backend.analysis.key_levels_supply_demand as module

    source = _source([])
    candles = [_c(h=2, l=0) for _ in range(5)]
    with patch.object(module, 'analyze_price_action_structure', return_value=source) as analyzer:
        result = module.analyze_key_levels(candles)
    if analyzer.call_count != 1 or analyzer.call_args.args[0] is not candles:
        return _fail(f'T2 53B analyzer reuse mismatch: {analyzer.call_args_list}')
    if result['source_structure'] is not source:
        return _fail('T2 returned source_structure is not the exact 53B result')
    _pass('T2')

    source_text = MODULE_PATH.read_text(encoding='utf-8')
    forbidden_reimplementation = (
        'def _confirmed_swings',
        'SWING_SPAN',
        'def analyze_candle',
        'from backend.analysis.candle_anatomy',
    )
    if any(needle in source_text for needle in forbidden_reimplementation):
        return _fail('T3 independent swing/anatomy engine found in 53C module')
    _pass('T3')

    short = _basic_high()[:4]
    with patch.object(module, 'analyze_price_action_structure') as analyzer:
        insufficient = module.analyze_key_levels(short)
    if insufficient['level_state'] != 'INSUFFICIENT_CANDLES' or analyzer.called:
        return _fail(f'T4 short valid cardinality mismatch: {insufficient}')
    if any(insufficient[key] for key in ('key_levels', 'level_groups', 'zones')):
        return _fail('T4 insufficient collections must be empty')
    if insufficient['source_structure'] is not None:
        return _fail('T4 insufficient source_structure must be None')
    _pass('T4')

    malformed_short = copy.deepcopy(short)
    malformed_short[0]['open'] = True
    with patch.object(module, 'analyze_price_action_structure') as analyzer:
        result = module.analyze_key_levels(malformed_short)
    if result['level_state'] != 'INSUFFICIENT_CANDLES' or analyzer.called:
        return _fail(f'T5 cardinality must precede malformed anatomy: {result}')
    _pass('T5')

    with patch.object(module, 'analyze_price_action_structure') as analyzer:
        result = module.analyze_key_levels({'open': 1})
    if result['level_state'] != 'MALFORMED' or result['source_structure'] is not None or analyzer.called:
        return _fail(f'T6 non-list malformed contract mismatch: {result}')
    _pass('T6')

    malformed_supported = _basic_high()
    malformed_supported[1]['open'] = True
    result = _analyze(malformed_supported)
    if result['level_state'] != 'MALFORMED':
        return _fail(f'T7 supported malformed state mismatch: {result}')
    if result['key_levels'] or result['level_groups'] or result['zones']:
        return _fail('T7 malformed structural collections must be empty')
    _pass('T7')

    from backend.analysis.price_action_structure import analyze_price_action_structure

    expected_source = analyze_price_action_structure(malformed_supported)
    if result['source_structure'] != expected_source or result['source_structure'] is None:
        return _fail('T8 malformed source_structure was not preserved exactly')
    _pass('T8')
    return 0


def test_t9_t20_exact_levels_and_breaks() -> int:
    high_result = _analyze(_basic_high())
    high = _levels(high_result, 'HIGH')[0]
    if high['level_kind'] != 'SWING_HIGH_LEVEL' or high['price'] != 10.0:
        return _fail(f'T9 HIGH level mismatch: {high}')
    _pass('T9')

    low_result = _analyze(_basic_low())
    low = _levels(low_result, 'LOW')[0]
    if low['level_kind'] != 'SWING_LOW_LEVEL' or low['price'] != 2.0:
        return _fail(f'T10 LOW level mismatch: {low}')
    _pass('T10')

    if high['level_id'] != 'LEVEL:HIGH:2' or high['swing_id'] != 'HIGH:2':
        return _fail(f'T11 deterministic level ID mismatch: {high}')
    _pass('T11')

    source_high = high_result['source_structure']['swing_points'][0]
    if high['confirmed_at_index'] != source_high['confirmed_at_index']:
        return _fail(f'T12 confirmation index was not preserved: {high} / {source_high}')
    _pass('T12')

    high_relations = _levels(_analyze(_high_relation(12)), 'HIGH')
    if high_relations[-1]['relation'] != 'HIGHER_HIGH':
        return _fail(f'T13 HIGH relation mismatch: {high_relations}')
    _pass('T13')

    low_relations = _levels(_analyze(_low_relation(4)), 'LOW')
    if low_relations[-1]['relation'] != 'HIGHER_LOW':
        return _fail(f'T14 LOW relation mismatch: {low_relations}')
    _pass('T14')

    if high['break_state'] != 'UNBROKEN' or high['broken_at_index'] is not None:
        return _fail(f'T15 unbroken HIGH mismatch: {high}')
    _pass('T15')

    broken_high_result = _analyze(_basic_high() + [_c(h=11, l=5, c=10.5)])
    broken_high = [row for row in _levels(broken_high_result, 'HIGH') if row['swing_id'] == 'HIGH:2'][0]
    if broken_high['break_state'] != 'BROKEN_ABOVE':
        return _fail(f'T16 broken HIGH mismatch: {broken_high}')
    _pass('T16')

    if low['break_state'] != 'UNBROKEN' or low['broken_at_index'] is not None:
        return _fail(f'T17 unbroken LOW mismatch: {low}')
    _pass('T17')

    broken_low_result = _analyze(_basic_low() + [_c(h=5, l=1, c=1.5)])
    broken_low = [row for row in _levels(broken_low_result, 'LOW') if row['swing_id'] == 'LOW:2'][0]
    if broken_low['break_state'] != 'BROKEN_BELOW':
        return _fail(f'T18 broken LOW mismatch: {broken_low}')
    _pass('T18')

    source_event = broken_high_result['source_structure']['break_events'][0]
    if broken_high['broken_at_index'] != source_event['index']:
        return _fail(f'T19 broken_at_index differs from 53B event: {broken_high} / {source_event}')
    _pass('T19')

    wick_result = _analyze(_basic_high() + [_c(h=11, l=5, c=9.5)])
    wick_level = [row for row in _levels(wick_result, 'HIGH') if row['swing_id'] == 'HIGH:2'][0]
    if wick_level['break_state'] != 'UNBROKEN' or wick_level['broken_at_index'] is not None:
        return _fail(f'T20 wick-only penetration became an independent break: {wick_level}')
    _pass('T20')
    return 0


def test_t21_t34_level_groups() -> int:
    high_group = _with_source(_group_source([100.0, 100.2]))['level_groups']
    if len(high_group) != 1 or high_group[0]['kind'] != 'HIGH':
        return _fail(f'T21 near-equal HIGH grouping mismatch: {high_group}')
    _pass('T21')

    low_group = _with_source(_group_source([50.0, 50.1], kind='LOW'))['level_groups']
    if len(low_group) != 1 or low_group[0]['kind'] != 'LOW':
        return _fail(f'T22 near-equal LOW grouping mismatch: {low_group}')
    _pass('T22')

    mixed_source = _source([_swing(2, 'HIGH', 100.0), _swing(2, 'LOW', 100.0)])
    if _with_source(mixed_source)['level_groups']:
        return _fail('T23 HIGH and LOW at the same price clustered together')
    _pass('T23')

    boundary = _with_source(_group_source([100.0, 99.75]))['level_groups']
    if len(boundary) != 1 or boundary[0]['member_count'] != 2:
        return _fail(f'T24 inclusive tolerance boundary mismatch: {boundary}')
    _pass('T24')

    outside = _with_source(_group_source([100.0, 99.74]))['level_groups']
    if outside:
        return _fail(f'T25 outside-tolerance values clustered: {outside}')
    _pass('T25')

    singleton = _with_source(_group_source([100.0]))['level_groups']
    if singleton:
        return _fail(f'T26 singleton group must not be emitted: {singleton}')
    _pass('T26')

    anchored = _with_source(_group_source([100.0, 100.2, 100.4]))
    groups = anchored['level_groups']
    if len(groups) != 1 or groups[0]['anchor_price'] != 100.0:
        return _fail(f'T27 immutable anchor mismatch: {groups}')
    if groups[0]['member_level_ids'] != ['LEVEL:HIGH:2', 'LEVEL:HIGH:5']:
        return _fail(f'T27 anchor drift changed membership: {groups[0]}')
    _pass('T27')

    if _group_for_level(anchored, 'LEVEL:HIGH:8') is not None:
        return _fail('T28 transitive A~B~C chaining incorrectly grouped C with A')
    _pass('T28')

    nearest = _with_source(_group_source([100.0, 100.4, 100.2]))
    if _group_for_level(nearest, 'LEVEL:HIGH:8') != 'HIGH_GROUP:2':
        return _fail(f'T29 nearest eligible anchor was not selected: {nearest["level_groups"]}')
    _pass('T29')

    import backend.analysis.key_levels_supply_demand as module

    tie_source = _group_source([-1.0, 1.0, 0.0])
    with patch.object(module, 'LEVEL_CLUSTER_TOLERANCE_RATIO', 1.0):
        tie = _with_source(tie_source)
    if _group_for_level(tie, 'LEVEL:HIGH:8') != 'HIGH_GROUP:1':
        return _fail(f'T30 equal-distance tie did not choose earliest group: {tie["level_groups"]}')
    _pass('T30')

    mean_group = high_group[0]
    if mean_group['representative_price'] != (100.0 + 100.2) / 2:
        return _fail(f'T31 arithmetic representative mismatch: {mean_group}')
    _pass('T31')

    if mean_group['member_level_ids'] != ['LEVEL:HIGH:2', 'LEVEL:HIGH:5']:
        return _fail(f'T32 member ordering mismatch: {mean_group}')
    _pass('T32')

    high_ids = _with_source(_group_source([100.0, 100.1, 101.0, 101.1]))['level_groups']
    if [row['group_id'] for row in high_ids] != ['HIGH_GROUP:1', 'HIGH_GROUP:2']:
        return _fail(f'T33 deterministic HIGH_GROUP IDs mismatch: {high_ids}')
    _pass('T33')

    low_ids = _with_source(_group_source([50.0, 50.1, 51.0, 51.1], kind='LOW'))['level_groups']
    if [row['group_id'] for row in low_ids] != ['LOW_GROUP:1', 'LOW_GROUP:2']:
        return _fail(f'T34 deterministic LOW_GROUP IDs mismatch: {low_ids}')
    _pass('T34')
    return 0


def test_t35_t49_zone_geometry_and_lifecycle() -> int:
    supply_result = _analyze(_basic_high())
    supply = [row for row in _zones(supply_result, 'HIGH') if row['swing_id'] == 'HIGH:2'][0]
    pivot = supply_result['source_structure']['candle_anatomy'][2]
    if supply['zone_kind'] != 'SUPPLY_LIKE' or supply['zone_low'] != max(pivot['open'], pivot['close']):
        return _fail(f'T35 supply geometry mismatch: {supply} / {pivot}')
    if supply['zone_high'] != pivot['high']:
        return _fail(f'T35 supply distal boundary mismatch: {supply} / {pivot}')
    _pass('T35')

    demand_result = _analyze(_basic_low())
    demand = [row for row in _zones(demand_result, 'LOW') if row['swing_id'] == 'LOW:2'][0]
    pivot = demand_result['source_structure']['candle_anatomy'][2]
    if demand['zone_kind'] != 'DEMAND_LIKE' or demand['zone_low'] != pivot['low']:
        return _fail(f'T36 demand geometry mismatch: {demand} / {pivot}')
    if demand['zone_high'] != min(pivot['open'], pivot['close']):
        return _fail(f'T36 demand proximal boundary mismatch: {demand} / {pivot}')
    _pass('T36')

    if supply['zone_width'] != supply['zone_high'] - supply['zone_low']:
        return _fail(f'T37 exact zone width mismatch: {supply}')
    _pass('T37')

    zero_rows = _basic_high()
    zero_rows[2] = _c(h=10, l=6, c=10, o=10)
    zero_zone = _zones(_analyze(zero_rows), 'HIGH')[0]
    if zero_zone['zone_width'] != 0.0 or zero_zone['zone_low'] != zero_zone['zone_high']:
        return _fail(f'T38 zero-width zone was not preserved: {zero_zone}')
    _pass('T38')

    delayed = _series([5, 6, 7, 10, 7, 6], [4, 4, 4, 5, 4, 4])
    before = _analyze(delayed[:5])
    after = _analyze(delayed)
    if any(row['swing_id'] == 'HIGH:3' for row in before['zones']):
        return _fail('T39 zone appeared before 53B confirmation')
    confirmed = [row for row in after['zones'] if row['swing_id'] == 'HIGH:3']
    if len(confirmed) != 1 or confirmed[0]['confirmed_at_index'] != 5:
        return _fail(f'T39 confirmed zone missing: {after["zones"]}')
    _pass('T39')

    if supply['zone_state'] != 'ACTIVE' or supply['invalidated_at_index'] is not None:
        return _fail(f'T40 active supply mismatch: {supply}')
    _pass('T40')

    if demand['zone_state'] != 'ACTIVE' or demand['invalidated_at_index'] is not None:
        return _fail(f'T41 active demand mismatch: {demand}')
    _pass('T41')

    supply_invalid = _analyze(_basic_high() + [_c(h=11, l=5, c=10.5)])
    invalid_supply = [row for row in _zones(supply_invalid, 'HIGH') if row['swing_id'] == 'HIGH:2'][0]
    if invalid_supply['zone_state'] != 'INVALIDATED' or invalid_supply['invalidated_at_index'] != 5:
        return _fail(f'T42 supply close invalidation mismatch: {invalid_supply}')
    _pass('T42')

    wick_supply = _analyze(_basic_high() + [_c(h=11, l=5, c=9.5)])
    wick_supply_zone = [row for row in _zones(wick_supply, 'HIGH') if row['swing_id'] == 'HIGH:2'][0]
    if wick_supply_zone['zone_state'] != 'ACTIVE':
        return _fail(f'T43 wick-only supply penetration invalidated zone: {wick_supply_zone}')
    _pass('T43')

    demand_invalid = _analyze(_basic_low() + [_c(h=5, l=1, c=1.5)])
    invalid_demand = [row for row in _zones(demand_invalid, 'LOW') if row['swing_id'] == 'LOW:2'][0]
    if invalid_demand['zone_state'] != 'INVALIDATED' or invalid_demand['invalidated_at_index'] != 5:
        return _fail(f'T44 demand close invalidation mismatch: {invalid_demand}')
    _pass('T44')

    wick_demand = _analyze(_basic_low() + [_c(h=5, l=1, c=2.5)])
    wick_demand_zone = [row for row in _zones(wick_demand, 'LOW') if row['swing_id'] == 'LOW:2'][0]
    if wick_demand_zone['zone_state'] != 'ACTIVE':
        return _fail(f'T45 wick-only demand penetration invalidated zone: {wick_demand_zone}')
    _pass('T45')

    equal_supply = _analyze(_basic_high() + [_c(h=11, l=5, c=10)])
    equal_supply_zone = [row for row in _zones(equal_supply, 'HIGH') if row['swing_id'] == 'HIGH:2'][0]
    if equal_supply_zone['zone_state'] != 'ACTIVE':
        return _fail(f'T46 close equal to supply distal invalidated zone: {equal_supply_zone}')
    _pass('T46')

    equal_demand = _analyze(_basic_low() + [_c(h=5, l=1, c=2)])
    equal_demand_zone = [row for row in _zones(equal_demand, 'LOW') if row['swing_id'] == 'LOW:2'][0]
    if equal_demand_zone['zone_state'] != 'ACTIVE':
        return _fail(f'T47 close equal to demand distal invalidated zone: {equal_demand_zone}')
    _pass('T47')

    repeated = _basic_high() + [
        _c(h=11, l=5, c=10.5),
        _c(h=9, l=4, c=5),
        _c(h=12, l=5, c=11),
    ]
    repeated_zone = [row for row in _zones(_analyze(repeated), 'HIGH') if row['swing_id'] == 'HIGH:2'][0]
    if repeated_zone['invalidated_at_index'] != 5:
        return _fail(f'T48 first invalidation index was not retained: {repeated_zone}')
    _pass('T48')

    if repeated_zone['zone_state'] != 'INVALIDATED':
        return _fail(f'T49 invalidated zone reactivated: {repeated_zone}')
    _pass('T49')
    return 0


def test_t50_t64_order_determinism_and_contracts() -> int:
    outside = _analyze(_outside_candle())
    if [(row['index'], row['kind']) for row in outside['key_levels']] != [(2, 'HIGH'), (2, 'LOW')]:
        return _fail(f'T50 same-candle levels missing or misordered: {outside["key_levels"]}')
    _pass('T50')

    if [(row['index'], row['zone_kind']) for row in outside['zones']] != [
        (2, 'SUPPLY_LIKE'), (2, 'DEMAND_LIKE'),
    ]:
        return _fail(f'T51 same-candle zones missing or misordered: {outside["zones"]}')
    _pass('T51')

    if [row['kind'] for row in outside['key_levels']] != ['HIGH', 'LOW']:
        return _fail(f'T52 key-level ordering mismatch: {outside["key_levels"]}')
    _pass('T52')

    if [row['kind'] for row in outside['zones']] != ['HIGH', 'LOW']:
        return _fail(f'T53 zone ordering mismatch: {outside["zones"]}')
    _pass('T53')

    grouped_source = _source([
        _swing(2, 'HIGH', 100.0),
        _swing(2, 'LOW', 50.0),
        _swing(5, 'HIGH', 100.1),
        _swing(5, 'LOW', 50.1),
    ])
    grouped = _with_source(grouped_source)
    if [row['kind'] for row in grouped['level_groups']] != ['HIGH', 'LOW']:
        return _fail(f'T54 level-group ordering mismatch: {grouped["level_groups"]}')
    _pass('T54')

    original = _bullish_base()
    before = copy.deepcopy(original)
    result = _analyze(original)
    if original != before:
        return _fail('T55 analyzer mutated input')
    _pass('T55')

    if _analyze(original) != result:
        return _fail('T56 same input did not produce exact output')
    _pass('T56')

    reordered = [
        {'close': row['close'], 'low': row['low'], 'high': row['high'], 'open': row['open']}
        for row in original
    ]
    if _analyze(reordered) != result:
        return _fail('T57 candle dictionary key order changed output')
    _pass('T57')

    from backend.analysis.key_levels_supply_demand import (
        KEY_LEVEL_KEYS,
        LEVEL_GROUP_KEYS,
        OUTPUT_KEYS,
        ZONE_KEYS,
    )

    if tuple(result.keys()) != OUTPUT_KEYS:
        return _fail(f'T58 top-level keys are not closed: {tuple(result.keys())}')
    _pass('T58')

    if any(tuple(row.keys()) != KEY_LEVEL_KEYS for row in result['key_levels']):
        return _fail('T59 key-level record keys are not closed')
    _pass('T59')

    if any(tuple(row.keys()) != LEVEL_GROUP_KEYS for row in grouped['level_groups']):
        return _fail('T60 level-group record keys are not closed')
    _pass('T60')

    if any(tuple(row.keys()) != ZONE_KEYS for row in result['zones']):
        return _fail('T61 zone record keys are not closed')
    _pass('T61')

    if result['structure_bias'] != result['source_structure']['structure_bias']:
        return _fail('T62 structure_bias was not propagated from 53B')
    if result['structure_bias'] != 'BULLISH':
        return _fail(f'T62 bullish fixture did not remain bullish: {result["structure_bias"]}')
    _pass('T62')

    from backend.analysis.price_action_structure import analyze_price_action_structure

    expected_source = analyze_price_action_structure(original)
    if result['source_structure'] != expected_source:
        return _fail('T63 valid source_structure differs from the exact 53B result')
    _pass('T63')

    anatomy = [
        {'open': 1.0, 'high': 2.0, 'low': 0.0, 'close': 1.0}
        for _ in range(5)
    ]
    anatomy[2] = {'open': 45.0, 'high': 50.0, 'low': 40.0, 'close': 46.0}
    geometry_source = _source([_swing(2, 'HIGH', 50.0)], anatomy=anatomy, candle_count=5)
    geometry = _with_source(geometry_source)
    zone = geometry['zones'][0]
    source_text = MODULE_PATH.read_text(encoding='utf-8')
    if (zone['zone_low'], zone['zone_high']) != (46.0, 50.0):
        return _fail(f'T64 zone did not use 53B anatomy geometry: {zone}')
    if 'analyze_candle' in source_text or 'from backend.analysis.candle_anatomy' in source_text:
        return _fail('T64 53C independently recalculates candle anatomy')
    _pass('T64')
    return 0


def test_t65_t72_protected_and_effect_boundaries() -> int:
    protected = (
        'backend/analysis/price_action_structure.py',
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
    )
    for marker, path in zip(('T65', 'T66', 'T67'), protected):
        if _git_names('diff', '--name-only', 'HEAD', '--', path):
            return _fail(f'{marker} protected analysis module changed: {path}')
        _pass(marker)

    source = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(source)
    network = ('requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser')
    if any(name in imported for name in network):
        return _fail(f'T68 network import found: {sorted(imported & set(network))}')
    _pass('T68')

    if any(needle in source.lower() for needle in ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai')):
        return _fail('T69 AI dependency found')
    _pass('T69')

    if any(needle in source for needle in ('write_text', 'write_bytes', 'atomic_write', 'open(')):
        return _fail('T70 write/file path found')
    _pass('T70')

    forbidden_dependencies = ('backend.news', 'backend.collectors', 'backend.trading', 'broker', 'telegram', 'freshness')
    if any(needle in source.lower() for needle in forbidden_dependencies):
        return _fail('T71 broker/news/freshness dependency found')
    _pass('T71')

    if _git_names('status', '--short', '--', 'data'):
        return _fail('T72 repository data/ is dirty')
    _pass('T72')
    return 0


def test_t73_t77_lookahead_group_stability_and_output() -> int:
    delayed = _series([5, 6, 7, 10, 7, 6], [4, 4, 4, 5, 4, 4])
    prefix = _analyze(delayed[:5])
    extended = _analyze(delayed)
    if any(row['swing_id'] == 'HIGH:3' for row in prefix['key_levels'] + prefix['zones']):
        return _fail('T73 future unconfirmed pivot leaked into prefix')
    if not any(row['swing_id'] == 'HIGH:3' for row in extended['key_levels']):
        return _fail('T73 confirmed future pivot missing from extension')
    _pass('T73')

    invalidation_prefix_rows = _basic_high() + [_c(h=11, l=5, c=10.5)]
    invalidation_prefix = _analyze(invalidation_prefix_rows)
    invalidation_extended = _analyze(invalidation_prefix_rows + [
        _c(h=9, l=4, c=5),
        _c(h=8, l=3, c=4),
        _c(h=7, l=2, c=3),
    ])
    prefix_zone = [row for row in invalidation_prefix['zones'] if row['swing_id'] == 'HIGH:2'][0]
    extended_zone = [row for row in invalidation_extended['zones'] if row['swing_id'] == 'HIGH:2'][0]
    if prefix_zone['invalidated_at_index'] != 5 or extended_zone['invalidated_at_index'] != 5:
        return _fail(f'T74 later candles changed prior invalidation: {prefix_zone} / {extended_zone}')
    _pass('T74')

    prefix_level = [row for row in invalidation_prefix['key_levels'] if row['swing_id'] == 'HIGH:2'][0]
    extended_level = [row for row in invalidation_extended['key_levels'] if row['swing_id'] == 'HIGH:2'][0]
    if prefix_level['broken_at_index'] != 5 or extended_level['broken_at_index'] != 5:
        return _fail(f'T75 later candles changed prior broken_at_index: {prefix_level} / {extended_level}')
    _pass('T75')

    old_swings = [
        _swing(2, 'HIGH', 100.0),
        _swing(5, 'HIGH', 100.1),
        _swing(8, 'HIGH', 100.5),
        _swing(11, 'HIGH', 100.55),
    ]
    new_swing = _swing(14, 'HIGH', 100.2)
    grouped_prefix = _with_source(_source(old_swings))
    grouped_extended = _with_source(_source(old_swings + [new_swing]))
    for level in grouped_prefix['key_levels']:
        before_group = _group_for_level(grouped_prefix, level['level_id'])
        after_group = _group_for_level(grouped_extended, level['level_id'])
        if before_group != after_group:
            return _fail(f'T76 prior group assignment changed for {level["level_id"]}')
    first_group = [row for row in grouped_extended['level_groups'] if row['group_id'] == 'HIGH_GROUP:1'][0]
    if first_group['member_level_ids'] != ['LEVEL:HIGH:2', 'LEVEL:HIGH:5', 'LEVEL:HIGH:14']:
        return _fail(f'T76 compatible later level did not append deterministically: {first_group}')
    _pass('T76')

    forbidden = {
        'BUY', 'SELL', 'LONG', 'SHORT', 'ENTRY', 'STOP', 'TARGET',
        'POSITION SIZE', 'TRADE SIGNAL', 'WIN PROBABILITY', 'CONFIDENCE',
        'RECOMMENDATION', 'STRONG BUY', 'STRONG SELL',
    }
    emitted = {value.strip().upper() for value in _emitted_strings(invalidation_extended)}
    found = sorted(forbidden & emitted)
    if found:
        return _fail(f'T77 forbidden trade interpretation output: {found}')
    _pass('T77')
    return 0


def main() -> int:
    tests = (
        test_t1_t8_build_reuse_and_failures,
        test_t9_t20_exact_levels_and_breaks,
        test_t21_t34_level_groups,
        test_t35_t49_zone_geometry_and_lifecycle,
        test_t50_t64_order_determinism_and_contracts,
        test_t65_t72_protected_and_effect_boundaries,
        test_t73_t77_lookahead_group_stability_and_output,
    )
    for test in tests:
        result = test()
        if result:
            return result

    expected = tuple(f'T{index}' for index in range(1, 78))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('KEY_LEVELS_SUPPLY_DEMAND_53C_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
