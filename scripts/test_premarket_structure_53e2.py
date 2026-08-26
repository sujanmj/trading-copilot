#!/usr/bin/env python3
"""Focused tests for AstraEdge 53E2 deterministic premarket structure."""

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

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'premarket_structure.py'
PASS_MARKERS: list[str] = []


def _fail(message: str) -> int:
    print(f'PREMARKET_STRUCTURE_53E2_FAIL: {message}', file=sys.stderr)
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


def _mtf_result(
    *,
    state: str = 'OK',
    timeframe_count: int = 2,
    structure_alignment: str = 'ALIGNED_BULLISH',
    structure_count: int = 2,
    vwap_alignment: str = 'ALIGNED_ABOVE_VWAP',
    vwap_count: int = 2,
    volume_counts: dict[str, int] | None = None,
    frames: list[dict] | None = None,
) -> dict:
    return {
        'schema_version': '53E',
        'analysis_state': state,
        'timeframe_count': timeframe_count,
        'alignment_scope': 'CALLER_SUPPLIED_WINDOWS',
        'min_timeframes': 2,
        'min_alignment_frames': 2,
        'structure_alignment': structure_alignment,
        'structure_alignment_frame_count': structure_count,
        'vwap_alignment': vwap_alignment,
        'vwap_alignment_frame_count': vwap_count,
        'volume_state_counts': volume_counts or {
            'HIGH_VOLUME': 0,
            'NORMAL_VOLUME': timeframe_count,
            'LOW_VOLUME': 0,
            'UNDEFINED': 0,
        },
        'frames': frames or [
            {'timeframe': f'frame-{index}'}
            for index in range(timeframe_count)
        ],
    }


def _snapshot(**overrides) -> dict:
    snapshot = {
        'previous_close': 100.0,
        'premarket_reference_price': 102.0,
        'premarket_high': 105.0,
        'premarket_low': 95.0,
        'observation_price': 103.0,
        'frames': [
            {'timeframe': 'first', 'candles': []},
            {'timeframe': 'second', 'candles': []},
        ],
    }
    snapshot.update(overrides)
    return snapshot


def _project(snapshot: dict, source: dict | None = None) -> dict:
    import backend.analysis.premarket_structure as module

    source_result = source or _mtf_result()
    with patch.object(module, 'analyze_multi_timeframe', return_value=source_result):
        return module.analyze_premarket_structure(snapshot)


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


def _actual_snapshot() -> dict:
    return _snapshot(frames=[
        {'timeframe': 'opaque-zeta', 'candles': _actual_candles()},
        {'timeframe': 'custom alpha', 'candles': _actual_candles(20.0)},
    ])


def test_t1_t18_build_dependencies_and_outer_validation() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('53E2', 'AstraEdge 53E2'):
        return _fail(f'T1 exact build mismatch: {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')

    source = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'backend.analysis.multi_timeframe' not in imported or 'analyze_multi_timeframe' not in source:
        return _fail('T2 53E analyze_multi_timeframe import/reuse missing')
    _pass('T2')

    if 'backend.analysis.key_levels_supply_demand' in imported or 'analyze_key_levels' in source:
        return _fail('T3 direct 53C dependency found')
    _pass('T3')

    if 'backend.analysis.volume_vwap' in imported or 'analyze_volume_vwap' in source:
        return _fail('T4 direct 53D dependency found')
    _pass('T4')

    direct_predecessors = (
        'backend.analysis.candle_anatomy',
        'backend.analysis.candlestick_patterns',
        'backend.analysis.price_action_structure',
        'analyze_candle',
        'analyze_candlestick_patterns',
        'analyze_price_action_structure',
    )
    if any(needle in imported or needle in source for needle in direct_predecessors):
        return _fail('T5 direct 53A/53A2/53B dependency found')
    _pass('T5')

    from backend.analysis.premarket_structure import OUTPUT_KEYS, analyze_premarket_structure

    non_dict = analyze_premarket_structure([])
    if non_dict['analysis_state'] != 'MALFORMED':
        return _fail(f'T6 non-dict contract mismatch: {non_dict}')
    _pass('T6')

    missing_scalar = _snapshot()
    del missing_scalar['previous_close']
    if analyze_premarket_structure(missing_scalar)['analysis_state'] != 'MALFORMED':
        return _fail('T7 missing required scalar accepted')
    _pass('T7')

    missing_frames = _snapshot()
    del missing_frames['frames']
    if analyze_premarket_structure(missing_frames)['analysis_state'] != 'MALFORMED':
        return _fail('T8 missing frames accepted')
    _pass('T8')

    if analyze_premarket_structure(_snapshot(frames='bad'))['analysis_state'] != 'MALFORMED':
        return _fail('T9 non-list frames accepted')
    _pass('T9')

    if analyze_premarket_structure(_snapshot(previous_close=True))['analysis_state'] != 'MALFORMED':
        return _fail('T10 bool scalar accepted')
    _pass('T10')

    if analyze_premarket_structure(_snapshot(observation_price=float('nan')))['analysis_state'] != 'MALFORMED':
        return _fail('T11 NaN scalar accepted')
    _pass('T11')

    if analyze_premarket_structure(_snapshot(premarket_high=float('inf')))['analysis_state'] != 'MALFORMED':
        return _fail('T12 +inf scalar accepted')
    _pass('T12')

    if analyze_premarket_structure(_snapshot(premarket_low=float('-inf')))['analysis_state'] != 'MALFORMED':
        return _fail('T13 -inf scalar accepted')
    _pass('T13')

    if analyze_premarket_structure(_snapshot(premarket_high=94.0))['analysis_state'] != 'MALFORMED':
        return _fail('T14 high below low accepted')
    _pass('T14')

    if analyze_premarket_structure(_snapshot(premarket_reference_price=94.0))['analysis_state'] != 'MALFORMED':
        return _fail('T15 reference below low accepted')
    _pass('T15')

    if analyze_premarket_structure(_snapshot(premarket_reference_price=106.0))['analysis_state'] != 'MALFORMED':
        return _fail('T16 reference above high accepted')
    _pass('T16')

    import backend.analysis.premarket_structure as module

    with patch.object(module, 'analyze_multi_timeframe') as analyzer:
        malformed = module.analyze_premarket_structure(_snapshot(previous_close=None))
    if analyzer.called or malformed['analysis_state'] != 'MALFORMED':
        return _fail('T17 malformed outer input invoked 53E')
    _pass('T17')

    expected_malformed = {
        'schema_version': '53E2',
        'analysis_state': 'MALFORMED',
        'premarket_scope': 'CALLER_SUPPLIED_PREMARKET_SNAPSHOT',
        'previous_close': None,
        'premarket_reference_price': None,
        'premarket_high': None,
        'premarket_low': None,
        'observation_price': None,
        'gap_points': None,
        'gap_ratio': None,
        'gap_state': 'UNDEFINED',
        'premarket_range_points': None,
        'premarket_range_ratio': None,
        'observation_vs_previous_close': 'UNDEFINED',
        'observation_vs_premarket_reference': 'UNDEFINED',
        'observation_vs_premarket_range': 'UNDEFINED',
        'timeframe_count': 0,
        'structure_alignment': 'UNDEFINED',
        'structure_alignment_frame_count': 0,
        'vwap_alignment': 'UNDEFINED',
        'vwap_alignment_frame_count': 0,
        'volume_state_counts': {
            'HIGH_VOLUME': 0,
            'NORMAL_VOLUME': 0,
            'LOW_VOLUME': 0,
            'UNDEFINED': 0,
        },
        'source_multi_timeframe': None,
    }
    if malformed != expected_malformed or tuple(malformed.keys()) != OUTPUT_KEYS:
        return _fail(f'T18 malformed closed output mismatch: {malformed}')
    _pass('T18')
    return 0


def test_t19_t27_delegation_and_state_propagation() -> int:
    import backend.analysis.premarket_structure as module

    snapshot = _snapshot()
    source = _mtf_result()
    with patch.object(module, 'analyze_multi_timeframe', return_value=source) as analyzer:
        result = module.analyze_premarket_structure(snapshot)
    if analyzer.call_count != 1:
        return _fail(f'T19 53E call count mismatch: {analyzer.call_count}')
    _pass('T19')

    if analyzer.call_args.args[0] is not snapshot['frames']:
        return _fail('T20 original frames object was not passed to 53E')
    _pass('T20')

    if result['source_multi_timeframe'] is not source:
        return _fail('T21 source_multi_timeframe is not exact 53E result')
    _pass('T21')

    if result['analysis_state'] != 'OK':
        return _fail(f'T22 53E OK state not propagated: {result}')
    _pass('T22')

    partial = _project(_snapshot(), _mtf_result(state='PARTIAL'))
    if partial['analysis_state'] != 'PARTIAL':
        return _fail(f'T23 PARTIAL state not propagated: {partial}')
    _pass('T23')

    insufficient_source = _mtf_result(
        state='INSUFFICIENT_TIMEFRAMES',
        timeframe_count=1,
        structure_alignment='UNDEFINED',
        structure_count=0,
        vwap_alignment='UNDEFINED',
        vwap_count=0,
    )
    insufficient = _project(_snapshot(), insufficient_source)
    if insufficient['analysis_state'] != 'INSUFFICIENT_TIMEFRAMES':
        return _fail(f'T24 insufficient state not propagated: {insufficient}')
    _pass('T24')

    malformed_source = _mtf_result(
        state='MALFORMED',
        timeframe_count=0,
        structure_alignment='UNDEFINED',
        structure_count=0,
        vwap_alignment='UNDEFINED',
        vwap_count=0,
        volume_counts={
            'HIGH_VOLUME': 0,
            'NORMAL_VOLUME': 0,
            'LOW_VOLUME': 0,
            'UNDEFINED': 0,
        },
        frames=[],
    )
    delegated_malformed = _project(_snapshot(), malformed_source)
    if delegated_malformed['analysis_state'] != 'MALFORMED':
        return _fail(f'T25 delegated MALFORMED state not propagated: {delegated_malformed}')
    _pass('T25')

    if partial['gap_points'] != 2.0 or partial['premarket_range_points'] != 10.0:
        return _fail(f'T26 scalar facts erased by PARTIAL source: {partial}')
    _pass('T26')

    if insufficient['gap_state'] != 'GAP_UP' or insufficient['observation_price'] != 103.0:
        return _fail(f'T27 scalar facts erased by insufficient source: {insufficient}')
    _pass('T27')
    return 0


def test_t28_t38_gap_and_range_math() -> int:
    gap_up = _project(_snapshot(premarket_reference_price=103.0))
    if gap_up['gap_state'] != 'GAP_UP':
        return _fail(f'T28 gap-up state mismatch: {gap_up}')
    _pass('T28')

    gap_down = _project(_snapshot(premarket_reference_price=97.0))
    if gap_down['gap_state'] != 'GAP_DOWN':
        return _fail(f'T29 gap-down state mismatch: {gap_down}')
    _pass('T29')

    flat = _project(_snapshot(premarket_reference_price=100.0))
    if flat['gap_state'] != 'FLAT':
        return _fail(f'T30 flat-gap state mismatch: {flat}')
    _pass('T30')

    if gap_up['gap_points'] != 3.0:
        return _fail(f'T31 gap points mismatch: {gap_up}')
    _pass('T31')

    if gap_up['gap_ratio'] != 0.03:
        return _fail(f'T32 positive gap ratio mismatch: {gap_up}')
    _pass('T32')

    if gap_down['gap_ratio'] != -0.03:
        return _fail(f'T33 negative gap ratio mismatch: {gap_down}')
    _pass('T33')

    zero_previous = _project(_snapshot(
        previous_close=0.0,
        premarket_reference_price=3.0,
        premarket_high=4.0,
        premarket_low=2.0,
        observation_price=3.0,
    ))
    if zero_previous['gap_ratio'] is not None:
        return _fail(f'T34 zero previous close gap ratio mismatch: {zero_previous}')
    _pass('T34')

    range_result = _project(_snapshot(premarket_high=106.0, premarket_low=96.0))
    if range_result['premarket_range_points'] != 10.0:
        return _fail(f'T35 premarket range points mismatch: {range_result}')
    _pass('T35')

    if range_result['premarket_range_ratio'] != 0.1:
        return _fail(f'T36 premarket range ratio mismatch: {range_result}')
    _pass('T36')

    if zero_previous['premarket_range_ratio'] is not None:
        return _fail(f'T37 zero previous close range ratio mismatch: {zero_previous}')
    _pass('T37')

    zero_width = _project(_snapshot(
        premarket_reference_price=102.0,
        premarket_high=102.0,
        premarket_low=102.0,
        observation_price=102.0,
    ))
    if zero_width['analysis_state'] != 'OK' or zero_width['premarket_range_points'] != 0.0:
        return _fail(f'T38 zero-width premarket range rejected: {zero_width}')
    _pass('T38')
    return 0


def test_t39_t50_observation_relations() -> int:
    above_previous = _project(_snapshot(observation_price=101.0))
    if above_previous['observation_vs_previous_close'] != 'ABOVE_PREVIOUS_CLOSE':
        return _fail(f'T39 above previous-close mismatch: {above_previous}')
    _pass('T39')

    below_previous = _project(_snapshot(observation_price=99.0))
    if below_previous['observation_vs_previous_close'] != 'BELOW_PREVIOUS_CLOSE':
        return _fail(f'T40 below previous-close mismatch: {below_previous}')
    _pass('T40')

    at_previous = _project(_snapshot(observation_price=100.0))
    if at_previous['observation_vs_previous_close'] != 'AT_PREVIOUS_CLOSE':
        return _fail(f'T41 at previous-close mismatch: {at_previous}')
    _pass('T41')

    above_reference = _project(_snapshot(observation_price=103.0))
    if above_reference['observation_vs_premarket_reference'] != 'ABOVE_PREMARKET_REFERENCE':
        return _fail(f'T42 above reference mismatch: {above_reference}')
    _pass('T42')

    below_reference = _project(_snapshot(observation_price=101.0))
    if below_reference['observation_vs_premarket_reference'] != 'BELOW_PREMARKET_REFERENCE':
        return _fail(f'T43 below reference mismatch: {below_reference}')
    _pass('T43')

    at_reference = _project(_snapshot(observation_price=102.0))
    if at_reference['observation_vs_premarket_reference'] != 'AT_PREMARKET_REFERENCE':
        return _fail(f'T44 at reference mismatch: {at_reference}')
    _pass('T44')

    above_range = _project(_snapshot(observation_price=106.0))
    if above_range['observation_vs_premarket_range'] != 'ABOVE_PREMARKET_RANGE':
        return _fail(f'T45 above range mismatch: {above_range}')
    _pass('T45')

    below_range = _project(_snapshot(observation_price=94.0))
    if below_range['observation_vs_premarket_range'] != 'BELOW_PREMARKET_RANGE':
        return _fail(f'T46 below range mismatch: {below_range}')
    _pass('T46')

    at_high = _project(_snapshot(observation_price=105.0))
    if at_high['observation_vs_premarket_range'] != 'AT_PREMARKET_HIGH':
        return _fail(f'T47 at high mismatch: {at_high}')
    _pass('T47')

    at_low = _project(_snapshot(observation_price=95.0))
    if at_low['observation_vs_premarket_range'] != 'AT_PREMARKET_LOW':
        return _fail(f'T48 at low mismatch: {at_low}')
    _pass('T48')

    inside = _project(_snapshot(observation_price=103.0))
    if inside['observation_vs_premarket_range'] != 'INSIDE_PREMARKET_RANGE':
        return _fail(f'T49 inside range mismatch: {inside}')
    _pass('T49')

    zero_width = _project(_snapshot(
        premarket_reference_price=102.0,
        premarket_high=102.0,
        premarket_low=102.0,
        observation_price=102.0,
    ))
    if zero_width['observation_vs_premarket_range'] != 'AT_PREMARKET_RANGE':
        return _fail(f'T50 zero-width range precedence mismatch: {zero_width}')
    _pass('T50')
    return 0


def test_t51_t58_exact_53e_aggregate_propagation() -> int:
    counts = {
        'HIGH_VOLUME': 1,
        'NORMAL_VOLUME': 0,
        'LOW_VOLUME': 1,
        'UNDEFINED': 1,
    }
    source_frames = [
        {'timeframe': 'zeta'},
        {'timeframe': 'arbitrary label'},
        {'timeframe': 'alpha'},
    ]
    source = _mtf_result(
        timeframe_count=3,
        structure_alignment='DIVERGENT',
        structure_count=3,
        vwap_alignment='ALIGNED_BELOW_VWAP',
        vwap_count=2,
        volume_counts=counts,
        frames=source_frames,
    )
    result = _project(_snapshot(), source)
    if result['timeframe_count'] != 3:
        return _fail(f'T51 timeframe count mismatch: {result}')
    _pass('T51')

    if result['structure_alignment'] != 'DIVERGENT':
        return _fail(f'T52 structure alignment mismatch: {result}')
    _pass('T52')

    if result['structure_alignment_frame_count'] != 3:
        return _fail(f'T53 structure alignment count mismatch: {result}')
    _pass('T53')

    if result['vwap_alignment'] != 'ALIGNED_BELOW_VWAP':
        return _fail(f'T54 VWAP alignment mismatch: {result}')
    _pass('T54')

    if result['vwap_alignment_frame_count'] != 2:
        return _fail(f'T55 VWAP alignment count mismatch: {result}')
    _pass('T55')

    if result['volume_state_counts'] is not counts:
        return _fail('T56 volume-state counts were recalculated or copied')
    _pass('T56')

    if [row['timeframe'] for row in result['source_multi_timeframe']['frames']] != [
        'zeta', 'arbitrary label', 'alpha',
    ]:
        return _fail(f'T57 source MTF order changed: {result}')
    _pass('T57')

    from backend.analysis.premarket_structure import analyze_premarket_structure

    actual = analyze_premarket_structure(_actual_snapshot())
    if [row['timeframe'] for row in actual['source_multi_timeframe']['frames']] != [
        'opaque-zeta', 'custom alpha',
    ]:
        return _fail(f'T58 arbitrary real 53E labels not preserved: {actual}')
    _pass('T58')
    return 0


def test_t59_t70_closed_deterministic_effects() -> int:
    from backend.analysis.premarket_structure import OUTPUT_KEYS, analyze_premarket_structure

    actual_snapshot = _actual_snapshot()
    result = analyze_premarket_structure(actual_snapshot)
    if tuple(result.keys()) != OUTPUT_KEYS:
        return _fail(f'T59 top-level keys are not closed: {tuple(result.keys())}')
    _pass('T59')

    forbidden = {
        'BUY', 'SELL', 'LONG', 'SHORT', 'ENTRY', 'STOP', 'TARGET',
        'POSITION SIZE', 'TRADE SIGNAL', 'WIN PROBABILITY', 'CONFIDENCE',
        'RECOMMENDATION', 'STRONG BUY', 'STRONG SELL', 'RISK-ON', 'RISK-OFF',
        'TRADEABLE', 'AVOID TRADE',
    }
    emitted = {value.strip().upper() for value in _emitted_strings(result)}
    found = sorted(forbidden & emitted)
    if found:
        return _fail(f'T60 forbidden trade interpretation output: {found}')
    _pass('T60')

    visible_keys = list(result.keys())
    if any(any(token in key.lower() for token in ('score', 'weight', 'vote', 'confidence')) for key in visible_keys):
        return _fail(f'T61 score/weight/vote/confidence output found: {visible_keys}')
    _pass('T61')

    before = copy.deepcopy(actual_snapshot)
    analyze_premarket_structure(actual_snapshot)
    if actual_snapshot != before:
        return _fail('T62 analyzer mutated input snapshot')
    _pass('T62')

    if actual_snapshot['frames'] != before['frames']:
        return _fail('T63 analyzer mutated frames or candles')
    _pass('T63')

    if analyze_premarket_structure(actual_snapshot) != result:
        return _fail('T64 repeated input did not produce exact output')
    _pass('T64')

    reordered = {
        'frames': actual_snapshot['frames'],
        'observation_price': actual_snapshot['observation_price'],
        'premarket_low': actual_snapshot['premarket_low'],
        'premarket_high': actual_snapshot['premarket_high'],
        'premarket_reference_price': actual_snapshot['premarket_reference_price'],
        'previous_close': actual_snapshot['previous_close'],
    }
    if analyze_premarket_structure(reordered) != result:
        return _fail('T65 snapshot dictionary key order changed output')
    _pass('T65')

    source = MODULE_PATH.read_text(encoding='utf-8')
    forbidden_time_logic = (
        'resample', 'aggregate_candles', 'fill_missing', 'timedelta', 'datetime',
        'zoneinfo', 'trading_calendar', 'market_calendar', '09:00', '09:08',
        '09:15', 'strptime', 'current_time',
    )
    if any(needle in source.lower() for needle in forbidden_time_logic):
        return _fail('T66 timeframe/session parsing or resampling logic found')
    _pass('T66')

    imported = _imported_names(source)
    network = {'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser'}
    if imported & network:
        return _fail(f'T67 network import found: {sorted(imported & network)}')
    if any(needle in source.lower() for needle in ('openai', 'anthropic', 'groq', 'ai_router')):
        return _fail('T67 AI dependency found')
    if any(needle in source for needle in ('write_text', 'write_bytes', 'atomic_write', 'open(')):
        return _fail('T67 write path found')
    _pass('T67')

    forbidden_dependencies = (
        'backend.news', 'backend.collectors', 'backend.trading', 'backend.telegram',
        'broker', 'freshness', 'telegram',
    )
    if any(needle in source.lower() for needle in forbidden_dependencies):
        return _fail('T68 broker/news/freshness/Telegram dependency found')
    _pass('T68')

    protected = (
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
        'backend/analysis/price_action_structure.py',
        'backend/analysis/key_levels_supply_demand.py',
        'backend/analysis/volume_vwap.py',
        'backend/analysis/multi_timeframe.py',
    )
    changed = {
        path
        for protected_path in protected
        for path in _git_names('diff', '--name-only', 'HEAD', '--', protected_path)
    }
    if changed:
        return _fail(f'T69 protected predecessor production changed: {sorted(changed)}')
    _pass('T69')

    if _git_names('status', '--short', '--', 'data'):
        return _fail('T70 repository data/ is dirty')
    _pass('T70')
    return 0


def test_t71_t72_anti_lookahead_and_scalar_isolation() -> int:
    from backend.analysis.premarket_structure import analyze_premarket_structure

    baseline_snapshot = _actual_snapshot()
    baseline = analyze_premarket_structure(baseline_snapshot)
    prefix_count = len(baseline_snapshot['frames'][0]['candles'])

    extended_snapshot = copy.deepcopy(baseline_snapshot)
    extended_snapshot['frames'][0]['candles'].append({
        'open': 6.5,
        'high': 7.8,
        'low': 5.2,
        'close': 7.2,
        'volume': 500.0,
    })
    extended = analyze_premarket_structure(extended_snapshot)
    baseline_source = baseline['source_multi_timeframe']
    extended_source = extended['source_multi_timeframe']

    if baseline_source['frames'][1] != extended_source['frames'][1]:
        return _fail('T71 appending to frame A changed frame B source output')

    baseline_frame = baseline_source['frames'][0]
    extended_frame = extended_source['frames'][0]
    baseline_key = baseline_frame['source_key_levels']
    extended_key = extended_frame['source_key_levels']
    baseline_structure = baseline_key['source_structure']
    extended_structure = extended_key['source_structure']
    if extended_structure['candle_anatomy'][:prefix_count] != baseline_structure['candle_anatomy']:
        return _fail('T71 future candle changed earlier 53C anatomy records')
    if extended_structure['swing_points'][:len(baseline_structure['swing_points'])] != baseline_structure['swing_points']:
        return _fail('T71 future candle changed earlier 53C swing records')
    if extended_structure['break_events'][:len(baseline_structure['break_events'])] != baseline_structure['break_events']:
        return _fail('T71 future candle changed earlier 53C break records')
    if extended_key['key_levels'][:len(baseline_key['key_levels'])] != baseline_key['key_levels']:
        return _fail('T71 future candle changed earlier 53C level records')
    baseline_volume = baseline_frame['source_volume_vwap']['records']
    extended_volume = extended_frame['source_volume_vwap']['records']
    if extended_volume[:prefix_count] != baseline_volume:
        return _fail('T71 future candle changed earlier 53D records')
    _pass('T71')

    scalar_keys = (
        'previous_close',
        'premarket_reference_price',
        'premarket_high',
        'premarket_low',
        'observation_price',
        'gap_points',
        'gap_ratio',
        'gap_state',
        'premarket_range_points',
        'premarket_range_ratio',
        'observation_vs_previous_close',
        'observation_vs_premarket_reference',
        'observation_vs_premarket_range',
    )
    if any(baseline[key] != extended[key] for key in scalar_keys):
        return _fail('T72 frame-only change altered scalar premarket facts')
    _pass('T72')
    return 0


def main() -> int:
    tests = (
        test_t1_t18_build_dependencies_and_outer_validation,
        test_t19_t27_delegation_and_state_propagation,
        test_t28_t38_gap_and_range_math,
        test_t39_t50_observation_relations,
        test_t51_t58_exact_53e_aggregate_propagation,
        test_t59_t70_closed_deterministic_effects,
        test_t71_t72_anti_lookahead_and_scalar_isolation,
    )
    for test in tests:
        result = test()
        if result:
            return result

    expected = tuple(f'T{index}' for index in range(1, 73))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('PREMARKET_STRUCTURE_53E2_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
