#!/usr/bin/env python3
"""Focused tests for AstraEdge 53E deterministic multi-timeframe analysis."""

from __future__ import annotations

import ast
import copy
import os
import re
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

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'multi_timeframe.py'
PASS_MARKERS: list[str] = []


def _fail(message: str) -> int:
    print(f'MULTI_TIMEFRAME_53E_FAIL: {message}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


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


def _key_projection(
    *,
    state: str = 'OK',
    bias: str = 'BULLISH',
    swings: int = 1,
    breaks: int = 0,
    levels: int = 1,
    groups: int = 0,
    active_zones: int = 1,
    invalidated_zones: int = 0,
) -> dict:
    source_structure = None
    if state == 'OK':
        source_structure = {
            'structure_state': 'OK',
            'structure_bias': bias,
            'swing_points': [{'swing_id': f'SWING:{index}'} for index in range(swings)],
            'break_events': [{'index': index} for index in range(breaks)],
            'candle_anatomy': [],
        }
    return {
        'schema_version': '53C',
        'level_state': state,
        'candle_count': 5,
        'cluster_tolerance_ratio': 0.0025,
        'structure_bias': bias if state == 'OK' else 'UNDEFINED',
        'key_levels': [{'level_id': f'LEVEL:{index}'} for index in range(levels)] if state == 'OK' else [],
        'level_groups': [{'group_id': f'GROUP:{index}'} for index in range(groups)] if state == 'OK' else [],
        'zones': (
            [{'zone_state': 'ACTIVE'} for _ in range(active_zones)]
            + [{'zone_state': 'INVALIDATED'} for _ in range(invalidated_zones)]
            if state == 'OK'
            else []
        ),
        'source_structure': source_structure,
    }


def _volume_projection(
    *,
    state: str = 'OK',
    vwap: float | None = 100.0,
    relation: str = 'ABOVE_VWAP',
    ratio: float | None = 1.0,
    volume_state: str = 'NORMAL_VOLUME',
) -> dict:
    if state != 'OK':
        vwap = None
        relation = 'UNDEFINED'
        ratio = None
        volume_state = 'UNDEFINED'
    return {
        'schema_version': '53D',
        'analysis_state': state,
        'latest_vwap': vwap,
        'latest_vwap_relation': relation,
        'latest_volume_ratio': ratio,
        'latest_volume_state': volume_state,
        'records': [],
        'candle_anatomy': [],
    }


def _mocked_analysis(
    key_results: list[dict],
    volume_results: list[dict],
    *,
    labels: list[str] | None = None,
    candles: list[list] | None = None,
) -> dict:
    import backend.analysis.multi_timeframe as module

    count = len(key_results)
    frame_labels = labels or [f'frame-{index}' for index in range(count)]
    frame_candles = candles or [[{'raw': index}] for index in range(count)]
    frames = [
        {'timeframe': frame_labels[index], 'candles': frame_candles[index]}
        for index in range(count)
    ]
    with (
        patch.object(module, 'analyze_key_levels', side_effect=key_results),
        patch.object(module, 'analyze_volume_vwap', side_effect=volume_results),
    ):
        return module.analyze_multi_timeframe(frames)


def _actual_candles(offset: float = 0.0) -> list[dict]:
    rows = (
        (5.0, 6.0, 4.0, 5.0, 10.0),
        (6.0, 8.0, 5.0, 6.0, 12.0),
        (7.0, 10.0, 6.0, 7.0, 14.0),
        (6.0, 8.0, 5.0, 6.0, 16.0),
        (5.0, 7.0, 4.0, 5.0, 18.0),
        (5.0, 6.5, 4.5, 6.0, 20.0),
        (6.0, 7.0, 5.0, 6.5, 22.0),
    )
    return [
        {
            'open': open_ + offset,
            'high': high + offset,
            'low': low + offset,
            'close': close + offset,
            'volume': volume,
        }
        for open_, high, low, close, volume in rows
    ]


def _actual_frames() -> list[dict]:
    return [
        {'timeframe': 'caller-first', 'candles': _actual_candles()},
        {'timeframe': 'caller-second', 'candles': _actual_candles(20.0)},
    ]


def test_t1_t10_build_reuse_and_cardinality() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53E', 'AstraEdge 53E'),
        ('53E2', 'AstraEdge 53E2'),
    }:
        return _fail(f'T1 expected 53E or successor 53E2 pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')

    source = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'backend.analysis.key_levels_supply_demand' not in imported or 'analyze_key_levels' not in source:
        return _fail('T2 53C analyze_key_levels import/reuse missing')
    _pass('T2')

    if 'backend.analysis.volume_vwap' not in imported or 'analyze_volume_vwap' not in source:
        return _fail('T3 53D analyze_volume_vwap import/reuse missing')
    _pass('T3')

    if 'backend.analysis.price_action_structure' in imported or 'analyze_price_action_structure' in source:
        return _fail('T4 direct 53B dependency found')
    _pass('T4')

    if 'backend.analysis.candle_anatomy' in imported or 'analyze_candle' in source:
        return _fail('T5 direct 53A dependency found')
    _pass('T5')

    from backend.analysis.multi_timeframe import analyze_multi_timeframe

    malformed = analyze_multi_timeframe({'timeframe': 'x'})
    if malformed['analysis_state'] != 'MALFORMED' or malformed['timeframe_count'] != 0:
        return _fail(f'T6 non-list contract mismatch: {malformed}')
    _pass('T6')

    empty = analyze_multi_timeframe([])
    if empty['analysis_state'] != 'INSUFFICIENT_TIMEFRAMES':
        return _fail(f'T7 empty-list contract mismatch: {empty}')
    _pass('T7')

    one = analyze_multi_timeframe([{'timeframe': 'only', 'candles': []}])
    if one['analysis_state'] != 'INSUFFICIENT_TIMEFRAMES' or one['timeframe_count'] != 1:
        return _fail(f'T8 one-frame contract mismatch: {one}')
    _pass('T8')

    import backend.analysis.multi_timeframe as module

    with patch.object(module, 'analyze_key_levels') as key_analyzer:
        result = module.analyze_multi_timeframe([{'timeframe': 'only', 'candles': []}])
    if key_analyzer.called or result['analysis_state'] != 'INSUFFICIENT_TIMEFRAMES':
        return _fail('T9 cardinality did not precede 53C')
    _pass('T9')

    with patch.object(module, 'analyze_volume_vwap') as volume_analyzer:
        result = module.analyze_multi_timeframe([{'timeframe': 'only', 'candles': []}])
    if volume_analyzer.called or result['analysis_state'] != 'INSUFFICIENT_TIMEFRAMES':
        return _fail('T10 cardinality did not precede 53D')
    _pass('T10')
    return 0


def test_t11_t18_outer_envelope_validation() -> int:
    import backend.analysis.multi_timeframe as module

    cases = (
        ([None, {'timeframe': 'b', 'candles': []}], 'T11'),
        ([{'candles': []}, {'timeframe': 'b', 'candles': []}], 'T12'),
        ([{'timeframe': 5, 'candles': []}, {'timeframe': 'b', 'candles': []}], 'T13'),
        ([{'timeframe': '   ', 'candles': []}, {'timeframe': 'b', 'candles': []}], 'T14'),
        ([{'timeframe': 'a'}, {'timeframe': 'b', 'candles': []}], 'T15'),
        ([{'timeframe': 'a', 'candles': 'bad'}, {'timeframe': 'b', 'candles': []}], 'T16'),
        ([{'timeframe': 'same', 'candles': []}, {'timeframe': ' same ', 'candles': []}], 'T17'),
    )
    last_result = None
    for frames, marker in cases:
        with (
            patch.object(module, 'analyze_key_levels') as key_analyzer,
            patch.object(module, 'analyze_volume_vwap') as volume_analyzer,
        ):
            result = module.analyze_multi_timeframe(frames)
        if result['analysis_state'] != 'MALFORMED':
            return _fail(f'{marker} malformed envelope accepted: {result}')
        if key_analyzer.called or volume_analyzer.called:
            return _fail(f'{marker} malformed envelope invoked a source analyzer')
        _pass(marker)
        last_result = result

    if (
        last_result is None
        or last_result['frames']
        or last_result['structure_alignment'] != 'UNDEFINED'
        or last_result['vwap_alignment'] != 'UNDEFINED'
        or last_result['structure_alignment_frame_count'] != 0
        or last_result['vwap_alignment_frame_count'] != 0
        or any(last_result['volume_state_counts'].values())
    ):
        return _fail(f'T18 malformed outer output mismatch: {last_result}')
    _pass('T18')
    return 0


def test_t19_t27_order_calls_and_traceability() -> int:
    import backend.analysis.multi_timeframe as module

    key_results = [_key_projection(), _key_projection(bias='BEARISH')]
    volume_results = [_volume_projection(), _volume_projection(relation='BELOW_VWAP')]
    result = _mocked_analysis(key_results, volume_results, labels=['zeta', 'alpha'])
    if result['analysis_state'] != 'OK' or len(result['frames']) != 2:
        return _fail(f'T19 two valid frames not accepted: {result}')
    _pass('T19')

    if [frame['timeframe'] for frame in result['frames']] != ['zeta', 'alpha']:
        return _fail(f'T20 supplied order changed: {result["frames"]}')
    _pass('T20')

    arbitrary = _mocked_analysis(
        [_key_projection(), _key_projection()],
        [_volume_projection(), _volume_projection()],
        labels=['not-a-duration', 'custom label'],
    )
    if [frame['timeframe'] for frame in arbitrary['frames']] != ['not-a-duration', 'custom label']:
        return _fail(f'T21 arbitrary labels rejected: {arbitrary}')
    _pass('T21')

    source = MODULE_PATH.read_text(encoding='utf-8')
    if re.search(r"['\"](?:1m|5m|15m|1h|1d)['\"]", source, re.I):
        return _fail('T22 hard-coded timeframe parsing label found')
    _pass('T22')

    frames = [
        {'timeframe': 'first', 'candles': [{'opaque': 1}]},
        {'timeframe': 'second', 'candles': [{'opaque': 2}]},
    ]
    keys = [_key_projection(), _key_projection()]
    volumes = [_volume_projection(), _volume_projection()]
    with (
        patch.object(module, 'analyze_key_levels', side_effect=keys) as key_analyzer,
        patch.object(module, 'analyze_volume_vwap', side_effect=volumes) as volume_analyzer,
    ):
        traced = module.analyze_multi_timeframe(frames)
    if key_analyzer.call_count != 2:
        return _fail(f'T23 53C call count mismatch: {key_analyzer.call_count}')
    _pass('T23')

    if volume_analyzer.call_count != 2:
        return _fail(f'T24 53D call count mismatch: {volume_analyzer.call_count}')
    _pass('T24')

    if (
        key_analyzer.call_args_list[0].args[0] is not frames[0]['candles']
        or key_analyzer.call_args_list[1].args[0] is not frames[1]['candles']
        or volume_analyzer.call_args_list[0].args[0] is not frames[0]['candles']
        or volume_analyzer.call_args_list[1].args[0] is not frames[1]['candles']
    ):
        return _fail('T25 source analyzers did not receive original candle lists')
    _pass('T25')

    if traced['frames'][0]['source_key_levels'] is not keys[0]:
        return _fail('T26 source_key_levels is not the exact 53C result')
    _pass('T26')

    if traced['frames'][0]['source_volume_vwap'] is not volumes[0]:
        return _fail('T27 source_volume_vwap is not the exact 53D result')
    _pass('T27')
    return 0


def test_t28_t43_states_and_fact_propagation() -> int:
    ok = _mocked_analysis(
        [_key_projection(), _key_projection()],
        [_volume_projection(), _volume_projection()],
    )
    if any(frame['frame_state'] != 'OK' for frame in ok['frames']):
        return _fail(f'T28 both-success frame state mismatch: {ok["frames"]}')
    _pass('T28')

    key_partial = _mocked_analysis(
        [_key_projection(state='INSUFFICIENT_CANDLES'), _key_projection()],
        [_volume_projection(), _volume_projection()],
    )
    if key_partial['frames'][0]['frame_state'] != 'PARTIAL':
        return _fail(f'T29 53C-insufficient frame mismatch: {key_partial["frames"][0]}')
    _pass('T29')

    volume_partial = _mocked_analysis(
        [_key_projection(), _key_projection()],
        [_volume_projection(state='MISSING_VOLUME'), _volume_projection()],
    )
    if volume_partial['frames'][0]['frame_state'] != 'PARTIAL':
        return _fail(f'T30 missing-volume frame mismatch: {volume_partial["frames"][0]}')
    _pass('T30')

    if ok['analysis_state'] != 'OK':
        return _fail(f'T31 all-OK top state mismatch: {ok}')
    _pass('T31')

    if key_partial['analysis_state'] != 'PARTIAL' or volume_partial['analysis_state'] != 'PARTIAL':
        return _fail('T32 partial frame did not propagate to top-level PARTIAL')
    _pass('T32')

    detailed_key = _key_projection(
        bias='BEARISH',
        swings=3,
        breaks=2,
        levels=4,
        groups=2,
        active_zones=2,
        invalidated_zones=1,
    )
    detailed_volume = _volume_projection(
        vwap=123.5,
        relation='BELOW_VWAP',
        ratio=1.75,
        volume_state='HIGH_VOLUME',
    )
    detailed = _mocked_analysis(
        [detailed_key, _key_projection()],
        [detailed_volume, _volume_projection()],
    )['frames'][0]
    if detailed['structure_bias'] != 'BEARISH':
        return _fail(f'T33 structure bias mismatch: {detailed}')
    _pass('T33')

    if detailed['confirmed_swing_count'] != 3:
        return _fail(f'T34 swing count mismatch: {detailed}')
    _pass('T34')

    if detailed['break_event_count'] != 2:
        return _fail(f'T35 break count mismatch: {detailed}')
    _pass('T35')

    if detailed['key_level_count'] != 4:
        return _fail(f'T36 key-level count mismatch: {detailed}')
    _pass('T36')

    if detailed['level_group_count'] != 2:
        return _fail(f'T37 level-group count mismatch: {detailed}')
    _pass('T37')

    if detailed['active_zone_count'] != 2:
        return _fail(f'T38 active-zone count mismatch: {detailed}')
    _pass('T38')

    if detailed['invalidated_zone_count'] != 1:
        return _fail(f'T39 invalidated-zone count mismatch: {detailed}')
    _pass('T39')

    if detailed['latest_vwap'] != 123.5:
        return _fail(f'T40 latest VWAP mismatch: {detailed}')
    _pass('T40')

    if detailed['latest_vwap_relation'] != 'BELOW_VWAP':
        return _fail(f'T41 VWAP relation mismatch: {detailed}')
    _pass('T41')

    if detailed['latest_volume_ratio'] != 1.75:
        return _fail(f'T42 volume ratio mismatch: {detailed}')
    _pass('T42')

    if detailed['latest_volume_state'] != 'HIGH_VOLUME':
        return _fail(f'T43 volume state mismatch: {detailed}')
    _pass('T43')
    return 0


def test_t44_t57_alignment_contracts() -> int:
    def aligned(
        biases: list[str],
        relations: list[str],
        *,
        key_states: list[str] | None = None,
        volume_states: list[str] | None = None,
    ) -> dict:
        key_source_states = key_states or ['OK'] * len(biases)
        vwap_source_states = volume_states or ['OK'] * len(relations)
        return _mocked_analysis(
            [
                _key_projection(state=key_source_states[index], bias=bias)
                for index, bias in enumerate(biases)
            ],
            [
                _volume_projection(state=vwap_source_states[index], relation=relation)
                for index, relation in enumerate(relations)
            ],
        )

    bullish = aligned(['BULLISH', 'BULLISH'], ['ABOVE_VWAP', 'ABOVE_VWAP'])
    if bullish['structure_alignment'] != 'ALIGNED_BULLISH':
        return _fail(f'T44 bullish alignment mismatch: {bullish}')
    _pass('T44')

    bearish = aligned(['BEARISH', 'BEARISH'], ['ABOVE_VWAP', 'ABOVE_VWAP'])
    if bearish['structure_alignment'] != 'ALIGNED_BEARISH':
        return _fail(f'T45 bearish alignment mismatch: {bearish}')
    _pass('T45')

    mixed = aligned(['MIXED', 'MIXED'], ['ABOVE_VWAP', 'ABOVE_VWAP'])
    if mixed['structure_alignment'] != 'ALIGNED_MIXED':
        return _fail(f'T46 mixed alignment mismatch: {mixed}')
    _pass('T46')

    bull_bear = aligned(['BULLISH', 'BEARISH'], ['ABOVE_VWAP', 'ABOVE_VWAP'])
    if bull_bear['structure_alignment'] != 'DIVERGENT':
        return _fail(f'T47 bullish/bearish divergence mismatch: {bull_bear}')
    _pass('T47')

    bull_mixed = aligned(['BULLISH', 'MIXED'], ['ABOVE_VWAP', 'ABOVE_VWAP'])
    if bull_mixed['structure_alignment'] != 'DIVERGENT':
        return _fail(f'T48 bullish/mixed divergence mismatch: {bull_mixed}')
    _pass('T48')

    one_structure = aligned(['BULLISH', 'UNDEFINED'], ['ABOVE_VWAP', 'ABOVE_VWAP'])
    if one_structure['structure_alignment'] != 'UNDEFINED':
        return _fail(f'T49 insufficient usable structure mismatch: {one_structure}')
    _pass('T49')

    three_structure = aligned(
        ['BULLISH', 'BEARISH', 'MIXED'],
        ['ABOVE_VWAP', 'ABOVE_VWAP', 'ABOVE_VWAP'],
    )
    if three_structure['structure_alignment_frame_count'] != 3:
        return _fail(f'T50 structure alignment count mismatch: {three_structure}')
    _pass('T50')

    above = aligned(['BULLISH', 'BULLISH'], ['ABOVE_VWAP', 'ABOVE_VWAP'])
    if above['vwap_alignment'] != 'ALIGNED_ABOVE_VWAP':
        return _fail(f'T51 above-VWAP alignment mismatch: {above}')
    _pass('T51')

    below = aligned(['BULLISH', 'BULLISH'], ['BELOW_VWAP', 'BELOW_VWAP'])
    if below['vwap_alignment'] != 'ALIGNED_BELOW_VWAP':
        return _fail(f'T52 below-VWAP alignment mismatch: {below}')
    _pass('T52')

    at = aligned(['BULLISH', 'BULLISH'], ['AT_VWAP', 'AT_VWAP'])
    if at['vwap_alignment'] != 'ALIGNED_AT_VWAP':
        return _fail(f'T53 at-VWAP alignment mismatch: {at}')
    _pass('T53')

    above_below = aligned(['BULLISH', 'BULLISH'], ['ABOVE_VWAP', 'BELOW_VWAP'])
    if above_below['vwap_alignment'] != 'DIVERGENT':
        return _fail(f'T54 above/below divergence mismatch: {above_below}')
    _pass('T54')

    above_at = aligned(['BULLISH', 'BULLISH'], ['ABOVE_VWAP', 'AT_VWAP'])
    if above_at['vwap_alignment'] != 'DIVERGENT':
        return _fail(f'T55 above/at divergence mismatch: {above_at}')
    _pass('T55')

    one_vwap = aligned(['BULLISH', 'BULLISH'], ['ABOVE_VWAP', 'UNDEFINED'])
    if one_vwap['vwap_alignment'] != 'UNDEFINED':
        return _fail(f'T56 insufficient usable VWAP mismatch: {one_vwap}')
    _pass('T56')

    three_vwap = aligned(
        ['BULLISH', 'BULLISH', 'BULLISH'],
        ['ABOVE_VWAP', 'BELOW_VWAP', 'AT_VWAP'],
    )
    if three_vwap['vwap_alignment_frame_count'] != 3:
        return _fail(f'T57 VWAP alignment count mismatch: {three_vwap}')
    _pass('T57')
    return 0


def test_t58_t66_counts_closed_output_and_determinism() -> int:
    counted = _mocked_analysis(
        [_key_projection() for _ in range(4)],
        [
            _volume_projection(volume_state='HIGH_VOLUME'),
            _volume_projection(volume_state='NORMAL_VOLUME'),
            _volume_projection(volume_state='LOW_VOLUME'),
            _volume_projection(volume_state='UNDEFINED', ratio=None),
        ],
    )
    expected_counts = {
        'HIGH_VOLUME': 1,
        'NORMAL_VOLUME': 1,
        'LOW_VOLUME': 1,
        'UNDEFINED': 1,
    }
    if counted['volume_state_counts'] != expected_counts:
        return _fail(f'T58 volume-state counts mismatch: {counted["volume_state_counts"]}')
    _pass('T58')

    undefined = _mocked_analysis(
        [_key_projection(), _key_projection()],
        [_volume_projection(), _volume_projection(state='MISSING_VOLUME')],
    )
    if undefined['volume_state_counts']['UNDEFINED'] != 1:
        return _fail(f'T59 undefined volume state not counted: {undefined}')
    _pass('T59')

    visible_keys = list(counted.keys()) + [key for frame in counted['frames'] for key in frame]
    if any(any(token in key.lower() for token in ('score', 'vote', 'signal')) for key in visible_keys):
        return _fail(f'T60 volume count derived a score/vote/signal: {visible_keys}')
    _pass('T60')

    from backend.analysis.multi_timeframe import FRAME_KEYS, OUTPUT_KEYS

    if tuple(counted.keys()) != OUTPUT_KEYS:
        return _fail(f'T61 top-level keys are not closed: {tuple(counted.keys())}')
    _pass('T61')

    if any(tuple(frame.keys()) != FRAME_KEYS for frame in counted['frames']):
        return _fail('T62 frame keys are not closed')
    _pass('T62')

    forbidden = {
        'BUY', 'SELL', 'LONG', 'SHORT', 'ENTRY', 'STOP', 'TARGET',
        'POSITION SIZE', 'TRADE SIGNAL', 'WIN PROBABILITY', 'CONFIDENCE',
        'RECOMMENDATION', 'STRONG BUY', 'STRONG SELL',
    }
    emitted = {value.strip().upper() for value in _emitted_strings(counted)}
    found = sorted(forbidden & emitted)
    if found:
        return _fail(f'T63 forbidden trade interpretation output: {found}')
    _pass('T63')

    from backend.analysis.multi_timeframe import analyze_multi_timeframe

    frames = _actual_frames()
    before = copy.deepcopy(frames)
    actual = analyze_multi_timeframe(frames)
    if frames != before:
        return _fail('T64 analyzer mutated input')
    _pass('T64')

    if analyze_multi_timeframe(frames) != actual:
        return _fail('T65 repeated input did not produce exact output')
    _pass('T65')

    reordered = [
        {'candles': frame['candles'], 'timeframe': frame['timeframe']}
        for frame in frames
    ]
    if analyze_multi_timeframe(reordered) != actual:
        return _fail('T66 frame dictionary key order changed output')
    _pass('T66')
    return 0


def test_t67_t71_boundaries_and_cleanliness() -> int:
    protected = (
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
        'backend/analysis/price_action_structure.py',
        'backend/analysis/key_levels_supply_demand.py',
        'backend/analysis/volume_vwap.py',
    )
    changed = {
        path
        for protected_path in protected
        for path in _git_names('diff', '--name-only', 'HEAD', '--', protected_path)
    }
    if changed:
        return _fail(f'T67 protected predecessor production changed: {sorted(changed)}')
    _pass('T67')

    source = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(source)
    network = {'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser'}
    if imported & network:
        return _fail(f'T68 network import found: {sorted(imported & network)}')
    if any(needle in source.lower() for needle in ('openai', 'anthropic', 'groq', 'ai_router')):
        return _fail('T68 AI dependency found')
    if any(needle in source for needle in ('write_text', 'write_bytes', 'atomic_write', 'open(')):
        return _fail('T68 write path found')
    _pass('T68')

    forbidden_dependencies = (
        'backend.news', 'backend.collectors', 'backend.trading', 'backend.telegram',
        'broker', 'freshness', 'telegram',
    )
    if any(needle in source.lower() for needle in forbidden_dependencies):
        return _fail('T69 broker/news/freshness/Telegram coupling found')
    _pass('T69')

    forbidden_time_logic = (
        'resample', 'aggregate_candles', 'timedelta', 'datetime', 'zoneinfo',
        'trading_calendar', 'market_calendar', '09:15', 'midnight', 'strptime',
    )
    if any(needle in source.lower() for needle in forbidden_time_logic):
        return _fail('T70 resampling/session/timeframe parsing logic found')
    if re.search(r"['\"](?:1m|5m|15m|1h|1d)['\"]", source, re.I):
        return _fail('T70 hard-coded timeframe hierarchy found')
    _pass('T70')

    if _git_names('status', '--short', '--', 'data'):
        return _fail('T71 repository data/ is dirty')
    _pass('T71')
    return 0


def test_t72_anti_lookahead_and_frame_isolation() -> int:
    from backend.analysis.multi_timeframe import analyze_multi_timeframe

    baseline_frames = _actual_frames()
    baseline = analyze_multi_timeframe(baseline_frames)
    prefix_count = len(baseline_frames[0]['candles'])

    future_price_a = {
        'open': 6.5,
        'high': 7.2,
        'low': 5.5,
        'close': 6.7,
        'volume': 50.0,
    }
    future_price_b = {
        'open': 6.5,
        'high': 8.0,
        'low': 5.0,
        'close': 7.5,
        'volume': 500.0,
    }
    extended_a = copy.deepcopy(baseline_frames)
    extended_b = copy.deepcopy(baseline_frames)
    extended_a[0]['candles'].append(future_price_a)
    extended_b[0]['candles'].append(future_price_b)
    result_a = analyze_multi_timeframe(extended_a)
    result_b = analyze_multi_timeframe(extended_b)

    if baseline['frames'][1] != result_a['frames'][1] or baseline['frames'][1] != result_b['frames'][1]:
        return _fail('T72 appending to frame A changed frame B output')

    baseline_key = baseline['frames'][0]['source_key_levels']
    baseline_structure = baseline_key['source_structure']
    baseline_volume = baseline['frames'][0]['source_volume_vwap']
    for result in (result_a, result_b):
        frame = result['frames'][0]
        key_source = frame['source_key_levels']
        structure = key_source['source_structure']
        volume_source = frame['source_volume_vwap']
        if structure['candle_anatomy'][:prefix_count] != baseline_structure['candle_anatomy']:
            return _fail('T72 future price changed earlier 53C anatomy records')
        if structure['swing_points'][:len(baseline_structure['swing_points'])] != baseline_structure['swing_points']:
            return _fail('T72 future price changed earlier 53C swing records')
        if structure['break_events'][:len(baseline_structure['break_events'])] != baseline_structure['break_events']:
            return _fail('T72 future price changed earlier 53C break records')
        if key_source['key_levels'][:len(baseline_key['key_levels'])] != baseline_key['key_levels']:
            return _fail('T72 future candle changed earlier 53C level records')
        if volume_source['records'][:prefix_count] != baseline_volume['records']:
            return _fail('T72 future price/volume changed earlier 53D records')

    _pass('T72')
    return 0


def main() -> int:
    tests = (
        test_t1_t10_build_reuse_and_cardinality,
        test_t11_t18_outer_envelope_validation,
        test_t19_t27_order_calls_and_traceability,
        test_t28_t43_states_and_fact_propagation,
        test_t44_t57_alignment_contracts,
        test_t58_t66_counts_closed_output_and_determinism,
        test_t67_t71_boundaries_and_cleanliness,
        test_t72_anti_lookahead_and_frame_isolation,
    )
    for test in tests:
        result = test()
        if result:
            return result

    expected = tuple(f'T{index}' for index in range(1, 73))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('MULTI_TIMEFRAME_53E_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
