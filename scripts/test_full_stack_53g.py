#!/usr/bin/env python3
"""Focused tests for AstraEdge 53G deterministic full-stack facade."""

from __future__ import annotations

import ast
import copy
import math
import os
import re
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

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'full_stack.py'
PASS_MARKERS: list[str] = []

BASELINE_HEAD = '52dc868d5cf1aad2ffb179a5f4ad2ad674eb276f'
BASELINE_TREE = 'e17ffb3b7069baee7786ead330795ecfad252054'

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'source_historical_setup_evidence',
)

PROTECTED_PRODUCTION = (
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/analysis/price_action_structure.py',
    'backend/analysis/key_levels_supply_demand.py',
    'backend/analysis/volume_vwap.py',
    'backend/analysis/multi_timeframe.py',
    'backend/analysis/premarket_structure.py',
    'backend/analysis/historical_setup_evidence.py',
)

PROTECTED_PREFIXES = (
    'backend/news/',
    'backend/collectors/',
    'backend/trading/',
    'backend/runtime/',
    'backend/telegram/',
)

PREDECESSOR_VALIDATORS = (
    ('scripts/validate_historical_setup_evidence_53f.py', 'PHASE_53F_VALIDATION_PASS', '53F'),
    ('scripts/validate_premarket_structure_53e2.py', 'PHASE_53E2_VALIDATION_PASS', '53E2'),
    ('scripts/validate_multi_timeframe_53e.py', 'PHASE_53E_VALIDATION_PASS', '53E'),
    ('scripts/validate_volume_vwap_53d.py', 'PHASE_53D_VALIDATION_PASS', '53D'),
    ('scripts/validate_key_levels_supply_demand_53c.py', 'PHASE_53C_VALIDATION_PASS', '53C'),
    ('scripts/validate_price_action_structure_53b.py', 'PHASE_53B_VALIDATION_PASS', '53B'),
    ('scripts/validate_candlestick_patterns_53a2.py', 'PHASE_53A2_VALIDATION_PASS', '53A2'),
    ('scripts/validate_candle_anatomy_53a.py', 'PHASE_53A_VALIDATION_PASS', '53A'),
    ('scripts/validate_event_age_freshness_52r_d2.py', 'PHASE_52R_D2_VALIDATION_PASS', '52R_D2'),
)

COMPILE_TARGETS = (
    'backend/analysis/full_stack.py',
    'scripts/test_full_stack_53g.py',
    'scripts/validate_full_stack_53g.py',
    'backend/config/build_info.py',
    *PROTECTED_PRODUCTION,
)


def _fail(message: str) -> int:
    print(f'FULL_STACK_53G_FAIL: {message}', file=sys.stderr)
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


def _git_value(*args: str) -> str:
    proc = subprocess.run(
        ['git', *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or 'git command failed')
    return (proc.stdout or '').strip()


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


def _insufficient_snapshot() -> dict:
    return _snapshot(frames=[
        {'timeframe': 'only', 'candles': _actual_candles()},
    ])


def _history_item(snapshot: dict, ratio) -> dict:
    return {
        'snapshot': snapshot,
        'forward_return_ratio': ratio,
    }


def _payload(*, current=None, horizon: str = 'caller-defined-window', history=None) -> dict:
    return {
        'current_snapshot': current if current is not None else _snapshot(),
        'outcome_horizon': horizon,
        'history': history if history is not None else [],
    }


def _source(result: dict) -> dict:
    return result['source_historical_setup_evidence']


def _lineage(result: dict) -> tuple[dict, dict, dict, list]:
    historical = _source(result)
    current = historical['source_current']
    multi = current['source_multi_timeframe']
    frames = multi['frames']
    return historical, current, multi, frames


def test_t1_t18_contract_and_delegation() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD
    import backend.analysis.full_stack as module
    from backend.analysis.full_stack import OUTPUT_KEYS as MODULE_OUTPUT_KEYS, analyze_full_stack

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('53G', 'AstraEdge 53G'):
        return _fail(f'T1 exact build mismatch: {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T1')

    source = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'def analyze_full_stack(payload: dict) -> dict:' not in source:
        return _fail('T2 public analyze_full_stack(payload: dict) -> dict API is missing')
    _pass('T2')

    if 'backend.analysis.historical_setup_evidence' not in imported:
        return _fail('T3 mandatory 53F import missing')
    if 'analyze_historical_setup_evidence' not in source:
        return _fail('T3 mandatory 53F analyze_historical_setup_evidence reuse missing')
    _pass('T3')

    forbidden_imports = (
        'backend.analysis.premarket_structure',
        'backend.analysis.multi_timeframe',
        'backend.analysis.volume_vwap',
        'backend.analysis.key_levels_supply_demand',
        'backend.analysis.price_action_structure',
        'backend.analysis.candlestick_patterns',
        'backend.analysis.candle_anatomy',
    )
    if imported & set(forbidden_imports):
        return _fail(f'T4 direct 53E2/lower import found: {sorted(imported & set(forbidden_imports))}')
    forbidden_calls = (
        'analyze_premarket_structure',
        'analyze_multi_timeframe',
        'analyze_volume_vwap',
        'analyze_key_levels',
        'analyze_price_action_structure',
        'analyze_candlestick_patterns',
        'analyze_candle',
    )
    if any(name in source for name in forbidden_calls):
        return _fail('T4 direct 53E2/lower call found')
    _pass('T4')

    tree = ast.parse(source)
    f_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'analyze_historical_setup_evidence'
    ]
    if len(f_calls) != 1:
        return _fail(f'T5 expected exactly one 53F call site, found {len(f_calls)}')
    _pass('T5')

    payload = _payload(current=_snapshot(), history=[_history_item(_snapshot(), 0.04)])
    captured: list[object] = []
    sentinel = {
        'schema_version': '53F',
        'analysis_state': 'OK',
        'matched_sample_count': 1,
    }

    def wrapped(argument):
        captured.append(argument)
        return sentinel

    with patch.object(module, 'analyze_historical_setup_evidence', side_effect=wrapped):
        result = module.analyze_full_stack(payload)
    if len(captured) != 1:
        return _fail(f'T6 53F was not called exactly once: {len(captured)}')
    if captured[0] is not payload:
        return _fail('T6 original payload object was not passed through')
    _pass('T6')

    if result['source_historical_setup_evidence'] is not sentinel:
        return _fail('T7 source object is not the exact 53F return')
    _pass('T7')

    if tuple(result) != OUTPUT_KEYS or MODULE_OUTPUT_KEYS != OUTPUT_KEYS:
        return _fail(f'T8 closed output keys mismatch: {tuple(result)}')
    _pass('T8')

    if result['schema_version'] != '53G':
        return _fail(f'T9 schema_version mismatch: {result["schema_version"]}')
    _pass('T9')

    if result['analysis_state'] != sentinel['analysis_state']:
        return _fail('T10 analysis_state was not copied exactly from 53F')
    _pass('T10')

    states = (
        ('T11', 'MALFORMED', None),
        ('T12', 'SOURCE_NOT_READY', _payload(current=_insufficient_snapshot(), history=[])),
        ('T13', 'NO_MATCHES', _payload(current=_snapshot(), history=[])),
        ('T14', 'OK', {'schema_version': '53F', 'analysis_state': 'OK'}),
    )
    for marker, state, canned in states:
        delegated = {'schema_version': '53F', 'analysis_state': state}
        with patch.object(module, 'analyze_historical_setup_evidence', return_value=delegated):
            propagated = module.analyze_full_stack(canned if isinstance(canned, dict) and 'current_snapshot' in canned else payload)
        if propagated['analysis_state'] != state:
            return _fail(f'{marker} did not propagate {state}: {propagated["analysis_state"]}')
        if propagated['source_historical_setup_evidence'] is not delegated:
            return _fail(f'{marker} did not keep the exact 53F object')
        _pass(marker)

    malformed_payload = {'not': 'a valid envelope'}
    malformed_calls: list[object] = []

    def malformed_wrapped(argument):
        malformed_calls.append(argument)
        return {'schema_version': '53F', 'analysis_state': 'MALFORMED'}

    with patch.object(module, 'analyze_historical_setup_evidence', side_effect=malformed_wrapped):
        malformed_result = module.analyze_full_stack(malformed_payload)
    if len(malformed_calls) != 1 or malformed_calls[0] is not malformed_payload:
        return _fail('T15 53G applied duplicate payload validation or skipped 53F')
    if malformed_result['analysis_state'] != 'MALFORMED':
        return _fail('T15 malformed payload was not delegated')
    _pass('T15')

    calculation_needles = (
        'gap_points', 'gap_ratio', 'vwap', 'volume_ratio', 'swing', 'bos', 'choch',
        'statistics', 'probability', 'confidence', 'score', 'mean_forward',
        'sum(', 'median(',
    )
    lowered = source.lower()
    if any(needle in lowered for needle in calculation_needles):
        return _fail('T16 new market calculations found in 53G facade')
    _pass('T16')

    owned_keys = {key.lower() for key in result}
    forbidden_fields = {
        'buy', 'sell', 'long', 'short', 'entry', 'stop', 'target', 'position size',
        'signal', 'confidence', 'probability', 'win rate', 'score', 'weight',
        'rank', 'recommendation', 'expected return',
    }
    if owned_keys & forbidden_fields:
        return _fail(f'T17 forbidden 53G-owned field: {sorted(owned_keys & forbidden_fields)}')
    if re.search(r'\b(buy|sell|long|short|entry|stop|target|signal|confidence|probability|win rate|score|weight|rank|recommendation|expected return)\b', source.lower()):
        return _fail('T17 trade/score/recommendation wording found in 53G source')
    _pass('T17')

    network_modules = {
        'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
    }
    model_modules = {
        'sklearn', 'numpy', 'pandas', 'joblib', 'torch', 'tensorflow', 'xgboost',
        'openai', 'anthropic',
    }
    if imported & network_modules:
        return _fail(f'T18 network import found: {sorted(imported & network_modules)}')
    if imported & model_modules:
        return _fail(f'T18 model/AI import found: {sorted(imported & model_modules)}')
    for needle in ('broker', 'telegram', 'sqlite', 'redis', 'write_text', 'write_bytes', 'open('):
        if needle in lowered:
            return _fail(f'T18 side-effect dependency found: {needle}')
    _pass('T18')
    return 0


def test_t19_t21_immutability_and_determinism() -> int:
    from backend.analysis.full_stack import analyze_full_stack

    payload = _payload(
        current=_snapshot(),
        history=[
            _history_item(_snapshot(), 0.04),
            _history_item(_insufficient_snapshot(), 0.10),
            _history_item(_snapshot(), -0.02),
        ],
    )
    before = copy.deepcopy(payload)
    first = analyze_full_stack(payload)
    if payload != before:
        return _fail('T19 payload, snapshots, frames, or candles were mutated')
    _pass('T19')

    second = analyze_full_stack(payload)
    if first != second:
        return _fail('T20 repeated invocation was not deterministic')
    _pass('T20')

    reordered = {
        'history': payload['history'],
        'outcome_horizon': payload['outcome_horizon'],
        'current_snapshot': payload['current_snapshot'],
    }
    if analyze_full_stack(reordered) != first:
        return _fail('T21 payload dictionary key order changed the result')
    _pass('T21')
    return 0


def test_t22_t37_real_lineage_and_outcomes() -> int:
    from backend.analysis.full_stack import analyze_full_stack

    current = _snapshot()
    matching = _snapshot()
    non_matching = _snapshot(observation_price=90.0)
    excluded = _insufficient_snapshot()
    payload = _payload(
        current=current,
        history=[
            _history_item(matching, 0.04),
            _history_item(excluded, 0.10),
            _history_item(_snapshot(), -0.02),
            _history_item(non_matching, 0.50),
            _history_item(_snapshot(), 0.0),
            _history_item(_snapshot(), 0.01),
        ],
    )
    result = analyze_full_stack(payload)
    historical, e2, e_source, frames = _lineage(result)

    if historical['schema_version'] != '53F':
        return _fail(f'T22 real payload did not reach 53F: {historical.get("schema_version")}')
    if result['analysis_state'] != historical['analysis_state']:
        return _fail('T22 53G state diverged from 53F')
    _pass('T22')

    if e2 is None or e2.get('schema_version') != '53E2':
        return _fail('T23 real lineage did not reach 53E2')
    if e2['analysis_state'] != 'OK':
        return _fail(f'T23 current 53E2 was not OK: {e2["analysis_state"]}')
    _pass('T23')

    if e_source is None or e_source.get('schema_version') != '53E':
        return _fail('T24 real lineage did not reach 53E')
    if e_source['analysis_state'] != 'OK':
        return _fail(f'T24 current 53E was not OK: {e_source["analysis_state"]}')
    _pass('T24')

    if not frames or frames[0].get('source_key_levels', {}).get('schema_version') != '53C':
        return _fail('T25 real lineage did not expose 53C source')
    if frames[0]['source_key_levels'].get('source_structure', {}).get('schema_version') != '53B':
        return _fail('T25 53C lineage did not expose predecessor structure facts')
    _pass('T25')

    volume = frames[0].get('source_volume_vwap')
    if not volume or volume.get('schema_version') != '53D':
        return _fail('T26 real lineage did not expose 53D source')
    if 'records' not in volume or 'latest_vwap' not in volume:
        return _fail('T26 53D lineage did not expose VWAP/volume facts')
    _pass('T26')

    if [frame['timeframe'] for frame in frames] != ['opaque-zeta', 'custom alpha']:
        return _fail(f'T27 frame order was not preserved: {[frame["timeframe"] for frame in frames]}')
    _pass('T27')

    indexes = [record['history_index'] for record in historical['history_records']]
    if indexes != list(range(6)):
        return _fail(f'T28 history order was not preserved: {indexes}')
    _pass('T28')

    if result['analysis_state'] != 'OK' or historical['analysis_state'] != 'OK':
        return _fail(f'T29 exact fingerprint match did not survive full stack: {result["analysis_state"]}')
    if historical['matched_sample_count'] != 4:
        return _fail(f'T29 matched_sample_count mismatch: {historical["matched_sample_count"]}')
    if not historical['history_records'][0]['matched']:
        return _fail('T29 matching historical record was not matched')
    _pass('T29')

    no_match = analyze_full_stack(_payload(
        current=_snapshot(),
        history=[_history_item(non_matching, 0.50)],
    ))
    if no_match['analysis_state'] != 'NO_MATCHES':
        return _fail(f'T30 non-match did not remain NO_MATCHES: {no_match["analysis_state"]}')
    if _source(no_match)['matched_sample_count'] != 0:
        return _fail('T30 non-match still produced matched samples')
    _pass('T30')

    excluded_record = historical['history_records'][1]
    if excluded_record['eligible'] or excluded_record['matched']:
        return _fail('T31 excluded historical source did not remain excluded')
    if excluded_record['source_state'] == 'OK':
        return _fail('T31 excluded historical source was marked OK')
    _pass('T31')

    if historical['history_records'][0]['outcome_state'] != 'POSITIVE':
        return _fail('T32 positive outcome was not preserved')
    _pass('T32')

    if historical['history_records'][2]['outcome_state'] != 'NEGATIVE':
        return _fail('T33 negative outcome was not preserved')
    _pass('T33')

    if historical['history_records'][4]['outcome_state'] != 'FLAT':
        return _fail('T34 flat outcome was not preserved')
    _pass('T34')

    matched_values = [0.04, -0.02, 0.0, 0.01]
    if historical['mean_forward_return_ratio'] != sum(matched_values) / len(matched_values):
        return _fail(f'T35 ordinary mean mismatch: {historical["mean_forward_return_ratio"]}')
    tiny = analyze_full_stack(_payload(
        current=_snapshot(),
        history=[_history_item(_snapshot(), 1e-20), _history_item(_snapshot(), 2e-20)],
    ))
    if _source(tiny)['mean_forward_return_ratio'] != (1e-20 + 2e-20) / 2:
        return _fail('T35 very small finite float mean was not preserved')
    large = analyze_full_stack(_payload(
        current=_snapshot(),
        history=[_history_item(_snapshot(), 1e308)],
    ))
    if _source(large)['mean_forward_return_ratio'] != 1e308:
        return _fail('T35 very large finite float was not preserved')
    if analyze_full_stack(_payload(history=[_history_item(_snapshot(), math.nan)]))['analysis_state'] != 'MALFORMED':
        return _fail('T35 NaN outcome was accepted')
    if analyze_full_stack(_payload(history=[_history_item(_snapshot(), math.inf)]))['analysis_state'] != 'MALFORMED':
        return _fail('T35 +inf outcome was accepted')
    _pass('T35')

    if historical['median_forward_return_ratio'] != statistics.median(matched_values):
        return _fail(f'T36 ordinary median mismatch: {historical["median_forward_return_ratio"]}')
    _pass('T36')

    if historical['min_forward_return_ratio'] != min(matched_values):
        return _fail(f'T37 min mismatch: {historical["min_forward_return_ratio"]}')
    if historical['max_forward_return_ratio'] != max(matched_values):
        return _fail(f'T37 max mismatch: {historical["max_forward_return_ratio"]}')
    _pass('T37')
    return 0


def test_t38_t44_numeric_and_boundary() -> int:
    from backend.analysis.full_stack import analyze_full_stack

    first_huge = 10 ** 400
    second_huge = first_huge + 2
    try:
        huge = analyze_full_stack(_payload(
            current=_snapshot(),
            history=[
                _history_item(_snapshot(), first_huge),
                _history_item(_snapshot(), second_huge),
            ],
        ))
    except OverflowError as exc:
        return _fail(f'T38 huge integer pair raised OverflowError: {exc}')
    historical = _source(huge)
    if huge['analysis_state'] != 'OK' or historical['analysis_state'] != 'OK':
        return _fail(f'T38 huge integer pair did not yield OK: {huge["analysis_state"]}')
    if historical['history_records'][0]['forward_return_ratio'] is not first_huge:
        return _fail('T38 first huge integer was not preserved')
    _pass('T38')

    if historical['history_records'][1]['forward_return_ratio'] is not second_huge:
        return _fail('T39 second huge integer was not preserved')
    if historical['matched_sample_count'] != 2:
        return _fail(f'T39 matched count mismatch: {historical["matched_sample_count"]}')
    _pass('T39')

    if historical['mean_forward_return_ratio'] != first_huge + 1:
        return _fail(f'T40 huge pair mean mismatch: {historical["mean_forward_return_ratio"]}')
    _pass('T40')

    if historical['median_forward_return_ratio'] != first_huge + 1:
        return _fail(f'T41 huge pair median mismatch: {historical["median_forward_return_ratio"]}')
    _pass('T41')

    if historical['min_forward_return_ratio'] != first_huge:
        return _fail(f'T42 huge pair min mismatch: {historical["min_forward_return_ratio"]}')
    if historical['max_forward_return_ratio'] != second_huge:
        return _fail(f'T42 huge pair max mismatch: {historical["max_forward_return_ratio"]}')
    _pass('T42')

    zero_close = _snapshot(
        previous_close=0.0,
        premarket_reference_price=3.0,
        premarket_high=4.0,
        premarket_low=2.0,
        observation_price=3.0,
    )
    zero_result = analyze_full_stack(_payload(
        current=zero_close,
        history=[_history_item(copy.deepcopy(zero_close), 0.04)],
    ))
    zero_e2 = _source(zero_result)['source_current']
    if zero_result['analysis_state'] != 'OK':
        return _fail(f'T43 previous_close zero did not survive: {zero_result["analysis_state"]}')
    if zero_e2['previous_close'] != 0.0 or zero_e2['gap_ratio'] is not None:
        return _fail('T43 previous_close zero 53E2 facts were not preserved')
    _pass('T43')

    zero_width = _snapshot(
        premarket_high=102.0,
        premarket_low=102.0,
        premarket_reference_price=102.0,
        observation_price=102.0,
    )
    width_result = analyze_full_stack(_payload(
        current=zero_width,
        history=[_history_item(copy.deepcopy(zero_width), -0.01)],
    ))
    width_e2 = _source(width_result)['source_current']
    if width_result['analysis_state'] != 'OK':
        return _fail(f'T44 zero-width premarket range did not survive: {width_result["analysis_state"]}')
    if width_e2['premarket_range_points'] != 0.0:
        return _fail('T44 zero-width range points were not preserved')
    _pass('T44')
    return 0


def test_t45_t54_leakage_lookahead_and_isolation() -> int:
    from backend.analysis.full_stack import analyze_full_stack
    import backend.analysis.full_stack as module

    current = _snapshot()
    historical_snapshot = _snapshot()
    first = analyze_full_stack(_payload(
        current=current,
        history=[_history_item(historical_snapshot, 0.04)],
    ))
    second = analyze_full_stack(_payload(
        current=current,
        history=[_history_item(historical_snapshot, -0.07)],
    ))
    first_source = _source(first)
    second_source = _source(second)
    if first_source['current_fingerprint'] != second_source['current_fingerprint']:
        return _fail('T45 outcome-only mutation altered the fingerprint')
    if first_source['history_records'][0]['fingerprint'] != second_source['history_records'][0]['fingerprint']:
        return _fail('T45 historical fingerprint changed with outcome')
    _pass('T45')

    if first_source['history_records'][0]['matched'] != second_source['history_records'][0]['matched']:
        return _fail('T46 outcome-only mutation altered the match boolean')
    if first_source['history_records'][0]['eligible'] != second_source['history_records'][0]['eligible']:
        return _fail('T46 outcome-only mutation altered eligible')
    _pass('T46')

    if first_source['source_current'] != second_source['source_current']:
        return _fail('T47 outcome-only mutation altered 53E2 source')
    first_e = first_source['source_current']['source_multi_timeframe']
    second_e = second_source['source_current']['source_multi_timeframe']
    if first_e != second_e:
        return _fail('T47 outcome-only mutation altered 53E source')
    if first_e['frames'][0]['source_key_levels'] != second_e['frames'][0]['source_key_levels']:
        return _fail('T47 outcome-only mutation altered 53C source records')
    if first_e['frames'][0]['source_volume_vwap'] != second_e['frames'][0]['source_volume_vwap']:
        return _fail('T47 outcome-only mutation altered 53D source records')
    _pass('T47')

    baseline_payload = _payload(
        current=_snapshot(),
        history=[_history_item(_snapshot(), 0.04)],
    )
    baseline = analyze_full_stack(copy.deepcopy(baseline_payload))
    extended_payload = copy.deepcopy(baseline_payload)
    prefix_count = len(extended_payload['current_snapshot']['frames'][0]['candles'])
    extended_payload['current_snapshot']['frames'][0]['candles'].append({
        'open': 6.5,
        'high': 7.8,
        'low': 5.2,
        'close': 7.2,
        'volume': 500.0,
    })
    extended = analyze_full_stack(extended_payload)
    _, _, baseline_e, baseline_frames = _lineage(baseline)
    _, _, extended_e, extended_frames = _lineage(extended)
    if baseline_frames[1] != extended_frames[1]:
        return _fail('T48 appending to frame A changed frame B source output')
    _pass('T48')

    baseline_key = baseline_frames[0]['source_key_levels']
    extended_key = extended_frames[0]['source_key_levels']
    baseline_structure = baseline_key['source_structure']
    extended_structure = extended_key['source_structure']
    if extended_structure['candle_anatomy'][:prefix_count] != baseline_structure['candle_anatomy']:
        return _fail('T49 future candle changed earlier 53C anatomy records')
    if extended_structure['swing_points'][:len(baseline_structure['swing_points'])] != baseline_structure['swing_points']:
        return _fail('T49 future candle changed earlier 53C swing records')
    if extended_structure['break_events'][:len(baseline_structure['break_events'])] != baseline_structure['break_events']:
        return _fail('T49 future candle changed earlier 53C break records')
    if extended_key['key_levels'][:len(baseline_key['key_levels'])] != baseline_key['key_levels']:
        return _fail('T49 future candle changed earlier 53C level records')
    _pass('T49')

    baseline_volume = baseline_frames[0]['source_volume_vwap']['records']
    extended_volume = extended_frames[0]['source_volume_vwap']['records']
    if extended_volume[:prefix_count] != baseline_volume:
        return _fail('T50 future candle changed earlier 53D records')
    _pass('T50')

    real_source = {'schema_version': '53F', 'analysis_state': 'OK', 'probe': object()}
    with patch.object(module, 'analyze_historical_setup_evidence', return_value=real_source):
        identity = module.analyze_full_stack(_payload())
    if identity['source_historical_setup_evidence'] is not real_source:
        return _fail('T51 53F source identity was copied')
    _pass('T51')

    live_payload = _payload(current=_snapshot(), history=[_history_item(_snapshot(), 0.04)])
    live_calls: list[dict] = []

    def live_wrapped(argument):
        from backend.analysis.historical_setup_evidence import analyze_historical_setup_evidence
        produced = analyze_historical_setup_evidence(argument)
        live_calls.append(copy.deepcopy(produced))
        return produced

    with patch.object(module, 'analyze_historical_setup_evidence', side_effect=live_wrapped):
        live = module.analyze_full_stack(live_payload)
    if live['source_historical_setup_evidence'] != live_calls[0]:
        return _fail('T52 returned 53F source was mutated')
    _pass('T52')

    source = MODULE_PATH.read_text(encoding='utf-8')
    tree = ast.parse(source)
    mutable_globals = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
            mutable_globals.append(getattr(node, 'lineno', 0))
    if mutable_globals:
        return _fail(f'T53 global mutable cache/state found at lines {mutable_globals}')
    _pass('T53')

    lowered = source.lower()
    session_needles = (
        'datetime', 'zoneinfo', 'market_calendar', 'trading_calendar',
        'session_open', 'current_time', '09:15', 'time.time',
    )
    if any(needle in lowered for needle in session_needles):
        return _fail('T54 current-time/session inference found')
    _pass('T54')
    return 0


def test_t55_t60_protection_and_final_state() -> int:
    changed = {
        path
        for protected_path in PROTECTED_PRODUCTION
        for path in _git_names('diff', '--name-only', 'HEAD', '--', protected_path)
    }
    if changed:
        return _fail(f'T55 protected production analyzers changed: {sorted(changed)}')
    _pass('T55')

    prefix_hits = {
        path for path in _git_names('diff', '--name-only', 'HEAD', '--')
        if path.startswith(PROTECTED_PREFIXES)
    }
    if prefix_hits:
        return _fail(f'T56 protected runtime/trading/news/Telegram changed: {sorted(prefix_hits)}')
    _pass('T56')

    if _git_names('status', '--short', '--', 'data'):
        return _fail('T57 repository data/ is dirty')
    _pass('T57')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    for path, marker, label in PREDECESSOR_VALIDATORS:
        proc = subprocess.run(
            [sys.executable, '-u', str(PROJECT_ROOT / path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        output = f'{proc.stdout or ""}{proc.stderr or ""}'
        if proc.returncode != 0 or marker not in {line.strip() for line in output.splitlines()}:
            if output:
                print(output, end='' if output.endswith('\n') else '\n', file=sys.stderr)
            return _fail(f'T58 {label} predecessor validator failed')
    _pass('T58')

    compiled = subprocess.run(
        [sys.executable, '-m', 'py_compile', *COMPILE_TARGETS],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return _fail(f'T59 py_compile failed: {compiled.stderr or compiled.stdout}')
    diff_check = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        return _fail(f'T59 git diff --check failed: {diff_check.stdout or diff_check.stderr}')
    _pass('T59')

    if _git_names('diff', '--cached', '--name-only'):
        return _fail('T60 files are staged')
    head = _git_value('rev-parse', 'HEAD')
    tree = _git_value('rev-parse', 'HEAD^{tree}')
    if (head, tree) != (BASELINE_HEAD, BASELINE_TREE):
        return _fail(f'T60 HEAD/tree changed: {head} / {tree}')
    _pass('T60')
    return 0


def main() -> int:
    tests = (
        test_t1_t18_contract_and_delegation,
        test_t19_t21_immutability_and_determinism,
        test_t22_t37_real_lineage_and_outcomes,
        test_t38_t44_numeric_and_boundary,
        test_t45_t54_leakage_lookahead_and_isolation,
        test_t55_t60_protection_and_final_state,
    )
    for test in tests:
        result = test()
        if result:
            return result

    expected = tuple(f'T{index}' for index in range(1, 61))
    missing = [marker for marker in expected if marker not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('FULL_STACK_53G_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
