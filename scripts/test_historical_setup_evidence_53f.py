#!/usr/bin/env python3
"""Focused tests for AstraEdge 53F deterministic historical setup evidence."""

from __future__ import annotations

import ast
import copy
import math
import os
import statistics
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

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'historical_setup_evidence.py'
PASS_MARKERS: list[str] = []

MALFORMED_OUTPUT = {
    'schema_version': '53F',
    'analysis_state': 'MALFORMED',
    'match_scope': 'EXACT_53E2_FACT_FINGERPRINT',
    'outcome_scope': 'CALLER_SUPPLIED_FORWARD_RETURN_RATIO',
    'outcome_horizon': None,
    'fingerprint_version': '53F-1',
    'history_count': 0,
    'history_eligible_count': 0,
    'history_excluded_count': 0,
    'matched_sample_count': 0,
    'current_fingerprint': None,
    'outcome_counts': {
        'POSITIVE': 0,
        'NEGATIVE': 0,
        'FLAT': 0,
    },
    'mean_forward_return_ratio': None,
    'median_forward_return_ratio': None,
    'min_forward_return_ratio': None,
    'max_forward_return_ratio': None,
    'matched_evidence': [],
    'source_current': None,
    'history_records': [],
}

FINGERPRINT_KEYS = (
    'fingerprint_version',
    'gap_state',
    'observation_vs_previous_close',
    'observation_vs_premarket_reference',
    'observation_vs_premarket_range',
    'timeframe_count',
    'structure_alignment',
    'structure_alignment_frame_count',
    'vwap_alignment',
    'vwap_alignment_frame_count',
    'volume_state_counts',
)

HISTORY_RECORD_KEYS = (
    'history_index',
    'forward_return_ratio',
    'outcome_state',
    'source_state',
    'eligible',
    'fingerprint',
    'matched',
    'source_premarket',
)

MATCHED_EVIDENCE_KEYS = (
    'history_index',
    'forward_return_ratio',
    'outcome_state',
)

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'match_scope',
    'outcome_scope',
    'outcome_horizon',
    'fingerprint_version',
    'history_count',
    'history_eligible_count',
    'history_excluded_count',
    'matched_sample_count',
    'current_fingerprint',
    'outcome_counts',
    'mean_forward_return_ratio',
    'median_forward_return_ratio',
    'min_forward_return_ratio',
    'max_forward_return_ratio',
    'matched_evidence',
    'source_current',
    'history_records',
)

PROTECTED_PRODUCTION = (
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/analysis/price_action_structure.py',
    'backend/analysis/key_levels_supply_demand.py',
    'backend/analysis/volume_vwap.py',
    'backend/analysis/multi_timeframe.py',
    'backend/analysis/premarket_structure.py',
)


def _fail(message: str) -> int:
    print(f'HISTORICAL_SETUP_EVIDENCE_53F_FAIL: {message}', file=sys.stderr)
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


def _owned_strings(result: dict) -> list[str]:
    values = [str(key) for key in result]
    for key in (
        'analysis_state',
        'match_scope',
        'outcome_scope',
        'outcome_horizon',
        'fingerprint_version',
        'schema_version',
    ):
        value = result.get(key)
        if isinstance(value, str):
            values.append(value)
    fingerprint = result.get('current_fingerprint')
    if isinstance(fingerprint, dict):
        values.extend(str(key) for key in fingerprint)
        volume_counts = fingerprint.get('volume_state_counts')
        if isinstance(volume_counts, dict):
            values.extend(str(key) for key in volume_counts)
        for field in fingerprint.values():
            if isinstance(field, str):
                values.append(field)
    for record in result.get('history_records') or []:
        values.extend(str(key) for key in record)
        outcome = record.get('outcome_state')
        if isinstance(outcome, str):
            values.append(outcome)
        nested = record.get('fingerprint')
        if isinstance(nested, dict):
            values.extend(str(key) for key in nested)
    for record in result.get('matched_evidence') or []:
        values.extend(str(key) for key in record)
        outcome = record.get('outcome_state')
        if isinstance(outcome, str):
            values.append(outcome)
    values.extend(str(key) for key in (result.get('outcome_counts') or {}))
    return values


def _actual_candles(offset: float = 0.0, scale: float = 1.0) -> list[dict]:
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
            'open': (open_ + offset) * scale,
            'high': (high + offset) * scale,
            'low': (low + offset) * scale,
            'close': (close + offset) * scale,
            'volume': volume,
        }
        for open_, high, low, close, volume in rows
    ]


def _snapshot(**overrides) -> dict:
    snapshot = {
        'previous_close': 100.0,
        'premarket_reference_price': 102.0,
        'premarket_high': 105.0,
        'premarket_low': 95.0,
        'observation_price': 103.0,
        'frames': [
            {'timeframe': 'opaque-zeta', 'candles': _actual_candles()},
            {'timeframe': 'custom alpha', 'candles': _actual_candles(20.0)},
        ],
    }
    snapshot.update(overrides)
    return snapshot


def _scaled_snapshot(factor: float) -> dict:
    original = _snapshot()
    return {
        'previous_close': original['previous_close'] * factor,
        'premarket_reference_price': original['premarket_reference_price'] * factor,
        'premarket_high': original['premarket_high'] * factor,
        'premarket_low': original['premarket_low'] * factor,
        'observation_price': original['observation_price'] * factor,
        'frames': [
            {
                'timeframe': frame['timeframe'],
                'candles': [
                    {
                        'open': candle['open'] * factor,
                        'high': candle['high'] * factor,
                        'low': candle['low'] * factor,
                        'close': candle['close'] * factor,
                        'volume': candle['volume'],
                    }
                    for candle in frame['candles']
                ],
            }
            for frame in original['frames']
        ],
    }


def _partial_snapshot() -> dict:
    return _snapshot(frames=[
        {'timeframe': 'opaque-zeta', 'candles': _actual_candles()},
        {'timeframe': 'custom alpha', 'candles': []},
    ])


def _insufficient_snapshot() -> dict:
    return _snapshot(frames=[
        {'timeframe': 'only', 'candles': _actual_candles()},
    ])


def _malformed_snapshot() -> dict:
    snapshot = _snapshot()
    del snapshot['previous_close']
    return snapshot


def _payload(*, current=None, horizon: str = 'caller-defined-window', history=None) -> dict:
    return {
        'current_snapshot': current if current is not None else _snapshot(),
        'outcome_horizon': horizon,
        'history': history if history is not None else [],
    }


def _history_item(snapshot: dict, ratio) -> dict:
    return {
        'snapshot': snapshot,
        'forward_return_ratio': ratio,
    }


def test_t1_t4_build_and_reuse() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('53F', 'AstraEdge 53F'):
        return _fail(f'T1 exact build mismatch: {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')

    source = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'backend.analysis.premarket_structure' not in imported:
        return _fail('T2 53E2 analyze_premarket_structure import missing')
    if 'analyze_premarket_structure' not in source:
        return _fail('T2 53E2 analyze_premarket_structure reuse missing')
    _pass('T2')

    if 'backend.analysis.multi_timeframe' in imported or 'analyze_multi_timeframe' in source:
        return _fail('T3 direct 53E dependency found')
    _pass('T3')

    direct_predecessors = (
        'backend.analysis.volume_vwap',
        'backend.analysis.key_levels_supply_demand',
        'backend.analysis.price_action_structure',
        'backend.analysis.candlestick_patterns',
        'backend.analysis.candle_anatomy',
        'analyze_volume_vwap',
        'analyze_key_levels',
        'analyze_price_action_structure',
        'analyze_candlestick_patterns',
        'analyze_candle',
    )
    if any(needle in imported or needle in source for needle in direct_predecessors):
        return _fail('T4 direct 53D/53C/53B/53A2/53A dependency found')
    _pass('T4')
    return 0


def test_t5_t22_outer_validation() -> int:
    from backend.analysis.historical_setup_evidence import (
        OUTPUT_KEYS as MODULE_OUTPUT_KEYS,
        analyze_historical_setup_evidence,
    )
    import backend.analysis.historical_setup_evidence as module

    if analyze_historical_setup_evidence([])['analysis_state'] != 'MALFORMED':
        return _fail('T5 non-dict payload accepted')
    _pass('T5')

    missing_current = {'outcome_horizon': '30m', 'history': []}
    if analyze_historical_setup_evidence(missing_current)['analysis_state'] != 'MALFORMED':
        return _fail('T6 missing current_snapshot accepted')
    _pass('T6')

    if analyze_historical_setup_evidence(_payload(current=[]))['analysis_state'] != 'MALFORMED':
        return _fail('T7 non-dict current_snapshot accepted')
    _pass('T7')

    missing_horizon = {'current_snapshot': _snapshot(), 'history': []}
    if analyze_historical_setup_evidence(missing_horizon)['analysis_state'] != 'MALFORMED':
        return _fail('T8 missing outcome_horizon accepted')
    _pass('T8')

    if analyze_historical_setup_evidence(_payload(horizon=30))['analysis_state'] != 'MALFORMED':
        return _fail('T9 non-string outcome_horizon accepted')
    _pass('T9')

    if analyze_historical_setup_evidence(_payload(horizon='   '))['analysis_state'] != 'MALFORMED':
        return _fail('T10 blank outcome_horizon accepted')
    _pass('T10')

    missing_history = {'current_snapshot': _snapshot(), 'outcome_horizon': '30m'}
    if analyze_historical_setup_evidence(missing_history)['analysis_state'] != 'MALFORMED':
        return _fail('T11 missing history accepted')
    _pass('T11')

    if analyze_historical_setup_evidence(_payload(history={}))['analysis_state'] != 'MALFORMED':
        return _fail('T12 non-list history accepted')
    _pass('T12')

    if analyze_historical_setup_evidence(_payload(history=['bad']))['analysis_state'] != 'MALFORMED':
        return _fail('T13 non-dict history item accepted')
    _pass('T13')

    if analyze_historical_setup_evidence(_payload(history=[{'forward_return_ratio': 0.1}]))['analysis_state'] != 'MALFORMED':
        return _fail('T14 historical snapshot missing accepted')
    _pass('T14')

    if analyze_historical_setup_evidence(_payload(history=[{'snapshot': [], 'forward_return_ratio': 0.1}]))['analysis_state'] != 'MALFORMED':
        return _fail('T15 historical snapshot non-dict accepted')
    _pass('T15')

    if analyze_historical_setup_evidence(_payload(history=[{'snapshot': _snapshot()}]))['analysis_state'] != 'MALFORMED':
        return _fail('T16 historical outcome missing accepted')
    _pass('T16')

    if analyze_historical_setup_evidence(_payload(history=[_history_item(_snapshot(), True)]))['analysis_state'] != 'MALFORMED':
        return _fail('T17 bool outcome accepted')
    _pass('T17')

    if analyze_historical_setup_evidence(_payload(history=[_history_item(_snapshot(), float('nan'))]))['analysis_state'] != 'MALFORMED':
        return _fail('T18 NaN outcome accepted')
    _pass('T18')

    if analyze_historical_setup_evidence(_payload(history=[_history_item(_snapshot(), float('inf'))]))['analysis_state'] != 'MALFORMED':
        return _fail('T19 +inf outcome accepted')
    _pass('T19')

    if analyze_historical_setup_evidence(_payload(history=[_history_item(_snapshot(), float('-inf'))]))['analysis_state'] != 'MALFORMED':
        return _fail('T20 -inf outcome accepted')
    _pass('T20')

    valid_first = _history_item(_snapshot(), 0.1)
    malformed_second = {'snapshot': _snapshot()}
    with patch.object(module, 'analyze_premarket_structure') as analyzer:
        result = module.analyze_historical_setup_evidence(_payload(history=[valid_first, malformed_second]))
    if analyzer.call_count != 0:
        return _fail(f'T21 outer validation invoked 53E2 {analyzer.call_count} times')
    if result['analysis_state'] != 'MALFORMED':
        return _fail('T21 malformed history item did not fail closed')
    _pass('T21')

    malformed = analyze_historical_setup_evidence(None)
    if malformed != MALFORMED_OUTPUT or tuple(malformed) != OUTPUT_KEYS or MODULE_OUTPUT_KEYS != OUTPUT_KEYS:
        return _fail(f'T22 closed MALFORMED output mismatch: {malformed}')
    _pass('T22')
    return 0


def test_t23_t36_delegation_and_eligibility() -> int:
    from backend.analysis.historical_setup_evidence import analyze_historical_setup_evidence
    import backend.analysis.historical_setup_evidence as module
    import backend.analysis.premarket_structure as premarket

    current = _snapshot()
    matching = _snapshot()
    different = _snapshot(observation_price=90.0)
    excluded = _insufficient_snapshot()
    history = [
        _history_item(matching, 0.04),
        _history_item(excluded, 0.10),
        _history_item(matching, -0.02),
        _history_item(different, 0.50),
        _history_item(matching, 0.0),
        _history_item(matching, 0.01),
    ]
    payload = _payload(current=current, history=history)

    calls: list[object] = []
    returns: list[dict] = []
    real = premarket.analyze_premarket_structure

    def wrapped(snapshot):
        calls.append(snapshot)
        value = real(snapshot)
        returns.append(value)
        return value

    with patch.object(module, 'analyze_premarket_structure', side_effect=wrapped):
        result = module.analyze_historical_setup_evidence(payload)

    if len(calls) != 1 + len(history):
        return _fail(f'T23/T24 53E2 call count mismatch: {len(calls)}')
    if calls[0] is not current:
        return _fail('T25 current snapshot object was copied or rewritten')
    _pass('T23')
    _pass('T24')
    _pass('T25')

    if any(calls[index + 1] is not history[index]['snapshot'] for index in range(len(history))):
        return _fail('T26 historical snapshot objects were copied or rewritten')
    _pass('T26')

    if result['source_current'] is not returns[0]:
        return _fail('T27 source_current is not the exact returned 53E2 object')
    _pass('T27')

    if any(
        result['history_records'][index]['source_premarket'] is not returns[index + 1]
        for index in range(len(history))
    ):
        return _fail('T28 history source_premarket objects are not exact')
    _pass('T28')

    if result['analysis_state'] != 'OK' or result['matched_sample_count'] != 4:
        return _fail(f'T29 exact match did not yield OK: {result["analysis_state"]} {result["matched_sample_count"]}')
    _pass('T29')

    no_match = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[_history_item(_snapshot(observation_price=90.0), 0.2)],
    ))
    if no_match['analysis_state'] != 'NO_MATCHES' or no_match['matched_sample_count'] != 0:
        return _fail(f'T30 NO_MATCHES contract mismatch: {no_match["analysis_state"]}')
    if no_match['current_fingerprint'] is None:
        return _fail('T30 current fingerprint missing on NO_MATCHES')
    _pass('T30')

    partial = analyze_historical_setup_evidence(_payload(
        current=_partial_snapshot(),
        history=[_history_item(_snapshot(), 0.1)],
    ))
    if partial['analysis_state'] != 'SOURCE_NOT_READY':
        return _fail(f'T31 current PARTIAL was not SOURCE_NOT_READY: {partial["analysis_state"]}')
    if partial['source_current']['analysis_state'] != 'PARTIAL':
        return _fail('T31 current source state was not PARTIAL')
    if any(record['matched'] for record in partial['history_records']):
        return _fail('T31 PARTIAL current marked historical records matched')
    _pass('T31')

    insufficient = analyze_historical_setup_evidence(_payload(
        current=_insufficient_snapshot(),
        history=[_history_item(_snapshot(), 0.1)],
    ))
    if insufficient['analysis_state'] != 'SOURCE_NOT_READY':
        return _fail(f'T32 INSUFFICIENT_TIMEFRAMES was not SOURCE_NOT_READY: {insufficient["analysis_state"]}')
    if insufficient['source_current']['analysis_state'] != 'INSUFFICIENT_TIMEFRAMES':
        return _fail('T32 current source state was not INSUFFICIENT_TIMEFRAMES')
    _pass('T32')

    malformed_current = analyze_historical_setup_evidence(_payload(
        current=_malformed_snapshot(),
        history=[_history_item(_snapshot(), 0.1)],
    ))
    if malformed_current['analysis_state'] != 'SOURCE_NOT_READY':
        return _fail(f'T33 current MALFORMED was not SOURCE_NOT_READY: {malformed_current["analysis_state"]}')
    if malformed_current['source_current']['analysis_state'] != 'MALFORMED':
        return _fail('T33 current source state was not MALFORMED')
    if malformed_current['current_fingerprint'] is not None:
        return _fail('T33 SOURCE_NOT_READY still exposed a current fingerprint')
    _pass('T33')

    excluded_record = result['history_records'][1]
    if excluded_record['eligible'] or excluded_record['fingerprint'] is not None or excluded_record['matched']:
        return _fail('T34 non-OK historical source was not excluded')
    _pass('T34')

    if result['history_eligible_count'] != 5:
        return _fail(f'T35 eligible count mismatch: {result["history_eligible_count"]}')
    _pass('T35')

    if result['history_excluded_count'] != 1 or result['history_count'] != 6:
        return _fail(
            f'T36 excluded count mismatch: excluded={result["history_excluded_count"]} '
            f'count={result["history_count"]}'
        )
    _pass('T36')
    return 0


def test_t37_t48_fingerprint_and_matching() -> int:
    from backend.analysis.historical_setup_evidence import analyze_historical_setup_evidence

    current = _snapshot()
    result = analyze_historical_setup_evidence(_payload(
        current=current,
        history=[_history_item(_snapshot(), 0.04)],
    ))
    fingerprint = result['current_fingerprint']
    source = result['source_current']
    if tuple(fingerprint) != FINGERPRINT_KEYS:
        return _fail(f'T37 fingerprint keys/order mismatch: {tuple(fingerprint)}')
    _pass('T37')

    if fingerprint['gap_state'] != source['gap_state']:
        return _fail('T38 fingerprint gap_state mismatch')
    _pass('T38')

    if fingerprint['observation_vs_previous_close'] != source['observation_vs_previous_close']:
        return _fail('T39 previous-close relation mismatch')
    _pass('T39')

    if fingerprint['observation_vs_premarket_reference'] != source['observation_vs_premarket_reference']:
        return _fail('T40 reference relation mismatch')
    _pass('T40')

    if fingerprint['observation_vs_premarket_range'] != source['observation_vs_premarket_range']:
        return _fail('T41 range relation mismatch')
    _pass('T41')

    if fingerprint['timeframe_count'] != source['timeframe_count']:
        return _fail('T42 timeframe_count mismatch')
    _pass('T42')

    if (
        fingerprint['structure_alignment'] != source['structure_alignment']
        or fingerprint['structure_alignment_frame_count'] != source['structure_alignment_frame_count']
    ):
        return _fail('T43 structure alignment/count mismatch')
    _pass('T43')

    if (
        fingerprint['vwap_alignment'] != source['vwap_alignment']
        or fingerprint['vwap_alignment_frame_count'] != source['vwap_alignment_frame_count']
    ):
        return _fail('T44 VWAP alignment/count mismatch')
    _pass('T44')

    volume_counts = fingerprint['volume_state_counts']
    if tuple(volume_counts) != ('HIGH_VOLUME', 'NORMAL_VOLUME', 'LOW_VOLUME', 'UNDEFINED'):
        return _fail(f'T45 volume_state_counts key order mismatch: {tuple(volume_counts)}')
    if volume_counts != source['volume_state_counts']:
        return _fail('T45 volume_state_counts values were changed')
    if volume_counts is source['volume_state_counts']:
        return _fail('T45 volume_state_counts was not a new closed copy')
    _pass('T45')

    equal = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[_history_item(_snapshot(), 0.04)],
    ))
    if not equal['history_records'][0]['matched'] or equal['analysis_state'] != 'OK':
        return _fail('T46 exact equal fingerprints did not match')
    _pass('T46')

    different = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[_history_item(_snapshot(observation_price=90.0), 0.04)],
    ))
    historical_fp = different['history_records'][0]['fingerprint']
    if historical_fp == different['current_fingerprint']:
        return _fail('T47 observation change did not alter fingerprint')
    if different['history_records'][0]['matched'] or different['analysis_state'] != 'NO_MATCHES':
        return _fail('T47 one fingerprint field difference still matched')
    _pass('T47')

    scaled = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[_history_item(_scaled_snapshot(2.0), 0.04)],
    ))
    if scaled['current_fingerprint'] != scaled['history_records'][0]['fingerprint']:
        return _fail('T48 scaled prices changed fingerprint facts')
    if not scaled['history_records'][0]['matched'] or scaled['analysis_state'] != 'OK':
        return _fail('T48 raw price magnitude alone prevented matching')
    _pass('T48')
    return 0


def test_t49_t63_outcomes_and_order() -> int:
    from backend.analysis.historical_setup_evidence import analyze_historical_setup_evidence

    current = _snapshot()
    history = [
        _history_item(_snapshot(), 0.04),
        _history_item(_insufficient_snapshot(), 0.10),
        _history_item(_snapshot(), -0.02),
        _history_item(_snapshot(observation_price=90.0), 0.50),
        _history_item(_snapshot(), 0.0),
        _history_item(_snapshot(), 0.01),
    ]
    result = analyze_historical_setup_evidence(_payload(current=current, history=history))
    records = result['history_records']
    if records[0]['outcome_state'] != 'POSITIVE':
        return _fail('T49 positive historical outcome was not POSITIVE')
    _pass('T49')

    if records[2]['outcome_state'] != 'NEGATIVE':
        return _fail('T50 negative historical outcome was not NEGATIVE')
    _pass('T50')

    if records[4]['outcome_state'] != 'FLAT':
        return _fail('T51 zero historical outcome was not FLAT')
    _pass('T51')

    if tuple(result['outcome_counts']) != ('POSITIVE', 'NEGATIVE', 'FLAT'):
        return _fail(f'T52 outcome_counts key order mismatch: {tuple(result["outcome_counts"])}')
    if result['outcome_counts'] != {'POSITIVE': 2, 'NEGATIVE': 1, 'FLAT': 1}:
        return _fail(f'T52 outcome counts mismatch: {result["outcome_counts"]}')
    _pass('T52')

    matched_values = [0.04, -0.02, 0.0, 0.01]
    expected_mean = sum(matched_values) / len(matched_values)
    if result['mean_forward_return_ratio'] != expected_mean:
        return _fail(f'T53 mean mismatch: {result["mean_forward_return_ratio"]}')
    _pass('T53')

    odd = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[
            _history_item(_snapshot(), 0.03),
            _history_item(_snapshot(), -0.01),
            _history_item(_snapshot(), 0.07),
        ],
    ))
    if odd['median_forward_return_ratio'] != statistics.median([0.03, -0.01, 0.07]):
        return _fail(f'T54 odd-count median mismatch: {odd["median_forward_return_ratio"]}')
    _pass('T54')

    expected_even_median = statistics.median(matched_values)
    if result['median_forward_return_ratio'] != expected_even_median:
        return _fail(f'T55 even-count median mismatch: {result["median_forward_return_ratio"]}')
    _pass('T55')

    if result['min_forward_return_ratio'] != min(matched_values):
        return _fail(f'T56 min mismatch: {result["min_forward_return_ratio"]}')
    _pass('T56')

    if result['max_forward_return_ratio'] != max(matched_values):
        return _fail(f'T57 max mismatch: {result["max_forward_return_ratio"]}')
    _pass('T57')

    no_match = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[_history_item(_snapshot(observation_price=90.0), 0.2)],
    ))
    if any(
        no_match[key] is not None
        for key in (
            'mean_forward_return_ratio',
            'median_forward_return_ratio',
            'min_forward_return_ratio',
            'max_forward_return_ratio',
        )
    ) or no_match['outcome_counts'] != {'POSITIVE': 0, 'NEGATIVE': 0, 'FLAT': 0}:
        return _fail('T58 no-match metrics were not all None/zero')
    _pass('T58')

    not_ready = analyze_historical_setup_evidence(_payload(
        current=_partial_snapshot(),
        history=[_history_item(_snapshot(), 0.2)],
    ))
    if any(
        not_ready[key] is not None
        for key in (
            'mean_forward_return_ratio',
            'median_forward_return_ratio',
            'min_forward_return_ratio',
            'max_forward_return_ratio',
        )
    ) or not_ready['matched_sample_count'] != 0:
        return _fail('T59 SOURCE_NOT_READY metrics were not all None')
    _pass('T59')

    if [record['history_index'] for record in records] != list(range(6)):
        return _fail('T60 history_index did not preserve original order')
    _pass('T60')

    if [record['forward_return_ratio'] for record in records] != [item['forward_return_ratio'] for item in history]:
        return _fail('T61 history_records did not preserve original list order')
    _pass('T61')

    matched_indexes = [item['history_index'] for item in result['matched_evidence']]
    if matched_indexes != [0, 2, 4, 5]:
        return _fail(f'T62 matched_evidence order mismatch: {matched_indexes}')
    _pass('T62')

    matched_outcomes = [item['outcome_state'] for item in result['matched_evidence']]
    if matched_outcomes != ['POSITIVE', 'NEGATIVE', 'FLAT', 'POSITIVE']:
        return _fail(f'T63 matched evidence was sorted or ranked by outcome: {matched_outcomes}')
    _pass('T63')
    return 0


def test_t64_t72_closed_output_and_isolation() -> int:
    from backend.analysis.historical_setup_evidence import (
        HISTORY_RECORD_KEYS as MODULE_HISTORY_KEYS,
        MATCHED_EVIDENCE_KEYS as MODULE_MATCHED_KEYS,
        OUTPUT_KEYS as MODULE_OUTPUT_KEYS,
        analyze_historical_setup_evidence,
    )

    payload = _payload(
        current=_snapshot(),
        history=[
            _history_item(_snapshot(), 0.04),
            _history_item(_insufficient_snapshot(), 0.10),
            _history_item(_snapshot(), -0.02),
        ],
    )
    before = copy.deepcopy(payload)
    result = analyze_historical_setup_evidence(payload)

    if tuple(result) != OUTPUT_KEYS or MODULE_OUTPUT_KEYS != OUTPUT_KEYS:
        return _fail(f'T64 closed top-level keys mismatch: {tuple(result)}')
    _pass('T64')

    if any(tuple(record) != HISTORY_RECORD_KEYS for record in result['history_records']):
        return _fail('T65 closed history-record keys mismatch')
    if MODULE_HISTORY_KEYS != HISTORY_RECORD_KEYS:
        return _fail('T65 module HISTORY_RECORD_KEYS mismatch')
    _pass('T65')

    if any(tuple(record) != MATCHED_EVIDENCE_KEYS for record in result['matched_evidence']):
        return _fail('T66 closed matched-evidence keys mismatch')
    if MODULE_MATCHED_KEYS != MATCHED_EVIDENCE_KEYS:
        return _fail('T66 module MATCHED_EVIDENCE_KEYS mismatch')
    _pass('T66')

    owned = ' '.join(_owned_strings(result)).lower()
    forbidden_metrics = (
        'win-rate', 'win_rate', 'win rate', 'hit rate', 'success rate',
        'probability', 'confidence', 'expected-return', 'expected_return',
        'expected return',
    )
    if any(token in owned for token in forbidden_metrics):
        return _fail('T67 win-rate/probability/confidence/expected-return output found')
    _pass('T67')

    forbidden_trade = (
        'BUY', 'SELL', 'LONG', 'SHORT', 'ENTRY', 'STOP', 'TARGET',
        'score', 'weight', 'ranking', 'recommendation',
    )
    owned_exact = set(_owned_strings(result))
    owned_lower = {value.lower() for value in owned_exact}
    if any(token in owned_exact or token.lower() in owned_lower for token in forbidden_trade):
        return _fail('T68 BUY/SELL/trade interpretation or score/weight/ranking found')
    _pass('T68')

    if payload != before:
        return _fail('T69 payload was mutated')
    if payload['current_snapshot'] != before['current_snapshot']:
        return _fail('T69 current_snapshot was mutated')
    if payload['history'] != before['history']:
        return _fail('T69 history was mutated')
    if payload['history'][0]['snapshot'] != before['history'][0]['snapshot']:
        return _fail('T69 historical snapshot was mutated')
    if payload['current_snapshot']['frames'] != before['current_snapshot']['frames']:
        return _fail('T69 frames/candles were mutated')
    source_before = copy.deepcopy(result['source_current'])
    analyze_historical_setup_evidence(payload)
    if result['source_current'] != source_before:
        return _fail('T69 returned 53E2 source object was mutated later')
    _pass('T69')

    first = analyze_historical_setup_evidence(payload)
    second = analyze_historical_setup_evidence(payload)
    if first != second:
        return _fail('T70 repeated identical input changed output')
    reordered = {
        'history': [
            {
                'forward_return_ratio': item['forward_return_ratio'],
                'snapshot': {
                    key: item['snapshot'][key]
                    for key in reversed(tuple(item['snapshot']))
                },
            }
            for item in payload['history']
        ],
        'outcome_horizon': payload['outcome_horizon'],
        'current_snapshot': {
            key: payload['current_snapshot'][key]
            for key in reversed(tuple(payload['current_snapshot']))
        },
    }
    if analyze_historical_setup_evidence(reordered) != first:
        return _fail('T70 dictionary key order changed output')
    _pass('T70')

    changed = {
        path
        for protected_path in PROTECTED_PRODUCTION
        for path in _git_names('diff', '--name-only', 'HEAD', '--', protected_path)
    }
    if changed:
        return _fail(f'T71 protected predecessor production changed: {sorted(changed)}')
    if _git_names('status', '--short', '--', 'data'):
        return _fail('T71 repository data/ is dirty')
    _pass('T71')

    current = _snapshot()
    historical = _snapshot()
    first_run = analyze_historical_setup_evidence(_payload(
        current=current,
        history=[_history_item(historical, 0.11)],
    ))
    second_run = analyze_historical_setup_evidence(_payload(
        current=current,
        history=[_history_item(historical, -0.37)],
    ))
    first_record = first_run['history_records'][0]
    second_record = second_run['history_records'][0]
    if first_run['source_current'] != second_run['source_current']:
        return _fail('T72 source_current changed when only the outcome changed')
    if first_record['source_premarket'] != second_record['source_premarket']:
        return _fail('T72 historical source_premarket changed when only the outcome changed')
    if first_record['fingerprint'] != second_record['fingerprint']:
        return _fail('T72 historical fingerprint changed when only the outcome changed')
    if first_record['eligible'] != second_record['eligible']:
        return _fail('T72 eligible changed when only the outcome changed')
    if first_record['matched'] != second_record['matched']:
        return _fail('T72 matched changed when only the outcome changed')
    if first_run['current_fingerprint'] != second_run['current_fingerprint']:
        return _fail('T72 current fingerprint changed when only the outcome changed')
    if first_record['forward_return_ratio'] == second_record['forward_return_ratio']:
        return _fail('T72 outcome-derived fields did not change')
    if first_record['outcome_state'] == second_record['outcome_state']:
        return _fail('T72 outcome_state did not follow the recorded ratio')
    if first_run['outcome_counts'] == second_run['outcome_counts']:
        return _fail('T72 outcome_counts did not follow the recorded ratio')
    if first_run['mean_forward_return_ratio'] == second_run['mean_forward_return_ratio']:
        return _fail('T72 mean_forward_return_ratio did not follow the recorded ratio')
    _pass('T72')
    return 0


def test_large_integer_forward_return_ratio() -> int:
    from backend.analysis.historical_setup_evidence import analyze_historical_setup_evidence
    import backend.analysis.historical_setup_evidence as module
    import backend.analysis.premarket_structure as premarket

    large_ratio = 10 ** 400
    current = _snapshot()
    historical = _snapshot()
    payload = _payload(
        current=current,
        history=[_history_item(historical, large_ratio)],
    )
    calls: list[object] = []
    real = premarket.analyze_premarket_structure

    def wrapped(snapshot):
        calls.append(snapshot)
        return real(snapshot)

    try:
        with patch.object(module, 'analyze_premarket_structure', side_effect=wrapped):
            result = module.analyze_historical_setup_evidence(payload)
    except OverflowError as exc:
        return _fail(f'large integer forward_return_ratio raised OverflowError: {exc}')
    if result['analysis_state'] == 'MALFORMED':
        return _fail('large integer forward_return_ratio was rejected by outer validation')
    if len(calls) != 2:
        return _fail(f'large integer payload did not reach 53E2 analysis: {len(calls)}')
    if calls[0] is not current or calls[1] is not historical:
        return _fail('large integer payload did not pass the original snapshot objects to 53E2')
    if result['analysis_state'] != 'OK':
        return _fail(f'large integer matching did not yield OK: {result["analysis_state"]}')
    record = result['history_records'][0]
    evidence = result['matched_evidence'][0]
    if record['outcome_state'] != 'POSITIVE':
        return _fail(f'large integer outcome was not POSITIVE: {record["outcome_state"]}')
    if record['forward_return_ratio'] is not large_ratio:
        return _fail('history_records did not keep the exact original integer ratio')
    if evidence['forward_return_ratio'] is not large_ratio:
        return _fail('matched_evidence did not keep the exact original integer ratio')
    if not record['matched']:
        return _fail('large integer matched sample was not marked matched')

    first_huge = 10 ** 400
    second_huge = first_huge + 2
    pair_current = _snapshot()
    pair_first = _snapshot()
    pair_second = _snapshot()
    pair_payload = _payload(
        current=pair_current,
        history=[
            _history_item(pair_first, first_huge),
            _history_item(pair_second, second_huge),
        ],
    )
    pair_calls: list[object] = []

    def pair_wrapped(snapshot):
        pair_calls.append(snapshot)
        return real(snapshot)

    try:
        with patch.object(module, 'analyze_premarket_structure', side_effect=pair_wrapped):
            pair_result = module.analyze_historical_setup_evidence(pair_payload)
    except OverflowError as exc:
        return _fail(f'matched huge integer pair raised OverflowError: {exc}')
    if pair_result['analysis_state'] == 'MALFORMED':
        return _fail('matched huge integer pair was rejected by outer validation')
    if len(pair_calls) != 3:
        return _fail(f'matched huge integer pair did not reach 53E2 analysis: {len(pair_calls)}')
    if pair_calls[0] is not pair_current or pair_calls[1] is not pair_first or pair_calls[2] is not pair_second:
        return _fail('matched huge integer pair did not pass original snapshot objects to 53E2')
    if pair_result['analysis_state'] != 'OK':
        return _fail(f'matched huge integer pair did not yield OK: {pair_result["analysis_state"]}')
    pair_records = pair_result['history_records']
    pair_evidence = pair_result['matched_evidence']
    if len(pair_records) != 2 or len(pair_evidence) != 2:
        return _fail('matched huge integer pair did not keep both history records')
    if not all(record['eligible'] and record['matched'] for record in pair_records):
        return _fail('matched huge integer pair records were not both eligible and matched')
    if pair_result['outcome_counts'] != {'POSITIVE': 2, 'NEGATIVE': 0, 'FLAT': 0}:
        return _fail(f'matched huge integer pair outcome_counts mismatch: {pair_result["outcome_counts"]}')
    if pair_records[0]['forward_return_ratio'] is not first_huge:
        return _fail('first huge integer was not preserved in history_records')
    if pair_records[1]['forward_return_ratio'] is not second_huge:
        return _fail('second huge integer was not preserved in history_records')
    if pair_evidence[0]['forward_return_ratio'] is not first_huge:
        return _fail('first huge integer was not preserved in matched_evidence')
    if pair_evidence[1]['forward_return_ratio'] is not second_huge:
        return _fail('second huge integer was not preserved in matched_evidence')
    if pair_result['min_forward_return_ratio'] != first_huge:
        return _fail(f'huge integer min mismatch: {pair_result["min_forward_return_ratio"]}')
    if pair_result['max_forward_return_ratio'] != second_huge:
        return _fail(f'huge integer max mismatch: {pair_result["max_forward_return_ratio"]}')
    if pair_result['mean_forward_return_ratio'] != first_huge + 1:
        return _fail(f'huge integer mean mismatch: {pair_result["mean_forward_return_ratio"]}')
    if pair_result['median_forward_return_ratio'] != first_huge + 1:
        return _fail(f'huge integer median mismatch: {pair_result["median_forward_return_ratio"]}')
    return 0


def main() -> int:
    tests = (
        test_t1_t4_build_and_reuse,
        test_t5_t22_outer_validation,
        test_t23_t36_delegation_and_eligibility,
        test_t37_t48_fingerprint_and_matching,
        test_t49_t63_outcomes_and_order,
        test_t64_t72_closed_output_and_isolation,
        test_large_integer_forward_return_ratio,
    )
    for test in tests:
        result = test()
        if result:
            return result

    expected = tuple(f'T{index}' for index in range(1, 73))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('HISTORICAL_SETUP_EVIDENCE_53F_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
