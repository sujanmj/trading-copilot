#!/usr/bin/env python3
"""Independent read-only validator for AstraEdge 53F historical setup evidence."""

from __future__ import annotations

import ast
import copy
import hashlib
import math
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_HEAD = 'e43be3ca8b3c2036fb8a7a85078c9e6911289f25'
BASELINE_TREE = '66ec9e271d3851f78d593a11fa542d30cccdbcbe'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'historical_setup_evidence.py'

COMPATIBILITY_FILES = {
    'scripts/test_premarket_structure_53e2.py',
    'scripts/validate_premarket_structure_53e2.py',
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

EXPECTED_TRACKED_CHANGES = {'backend/config/build_info.py'} | COMPATIBILITY_FILES

NEW_SOURCE = {
    'backend/analysis/historical_setup_evidence.py',
    'scripts/test_historical_setup_evidence_53f.py',
    'scripts/validate_historical_setup_evidence_53f.py',
}

ALLOWED_REPORTS = {'phase53f_review.txt', 'phase53f_diff.txt'}

PROTECTED_PRODUCTION = {
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/analysis/price_action_structure.py',
    'backend/analysis/key_levels_supply_demand.py',
    'backend/analysis/volume_vwap.py',
    'backend/analysis/multi_timeframe.py',
    'backend/analysis/premarket_structure.py',
}

PROTECTED_PREFIXES = (
    'backend/news/',
    'backend/collectors/',
    'backend/trading/',
    'backend/orchestration/',
    'backend/runtime/',
    'backend/telegram/',
)

WATCHED_RELATIVE = (
    EXPECTED_TRACKED_CHANGES
    | NEW_SOURCE
    | ALLOWED_REPORTS
    | PROTECTED_PRODUCTION
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

REQUIRED_FOCUSED_MARKERS = tuple(f'T{index}' for index in range(1, 73)) + (
    'HISTORICAL_SETUP_EVIDENCE_53F_PASS',
)

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
MODEL_MODULES = frozenset({
    'sklearn', 'numpy', 'pandas', 'joblib', 'torch', 'tensorflow', 'xgboost',
})


def _fail(message: str) -> int:
    print(f'ASTRAEDGE_PHASE_53F_HISTORICAL_SETUP_EVIDENCE_FAIL: {message}', file=sys.stderr)
    return 1


def _digest(path: Path) -> str:
    if not path.is_file():
        return 'missing'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_paths(*args: str) -> set[str]:
    proc = subprocess.run(
        ['git', *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or 'unknown Git error').strip())
    return {
        line.strip().replace('\\', '/')
        for line in (proc.stdout or '').splitlines()
        if line.strip()
    }


def _git_value(*args: str) -> str:
    proc = subprocess.run(
        ['git', *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or 'unknown Git error').strip())
    return (proc.stdout or '').strip()


def _run_script(path: str, marker: str, label: str) -> tuple[str | None, str]:
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    output = f'{proc.stdout or ""}{proc.stderr or ""}'
    output_lines = {line.strip() for line in output.splitlines()}
    if proc.returncode != 0 or marker not in output_lines:
        if output:
            print(output, end='' if output.endswith('\n') else '\n', file=sys.stderr)
        if proc.returncode != 0:
            return f'{label} exited {proc.returncode}', output
        return f'{label} missing marker {marker}', output
    return None, output


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


def _payload(*, current=None, horizon: str = '1h', history=None) -> dict:
    return {
        'current_snapshot': current if current is not None else _snapshot(),
        'outcome_horizon': horizon,
        'history': history if history is not None else [],
    }


def _validate_repository_scope() -> str | None:
    head = _git_value('rev-parse', 'HEAD')
    tree = _git_value('rev-parse', 'HEAD^{tree}')
    if head != BASELINE_HEAD:
        return f'HEAD must remain {BASELINE_HEAD}, got {head}'
    if tree != BASELINE_TREE:
        return f'HEAD tree must remain {BASELINE_TREE}, got {tree}'

    tracked = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    staged = _git_paths('diff', '--cached', '--name-only')
    if tracked != EXPECTED_TRACKED_CHANGES:
        missing = sorted(EXPECTED_TRACKED_CHANGES - tracked)
        unexpected = sorted(tracked - EXPECTED_TRACKED_CHANGES)
        return f'tracked change scope mismatch: missing={missing} unexpected={unexpected}'
    if not NEW_SOURCE <= untracked:
        return f'53F source files must be new and untracked: {sorted(NEW_SOURCE - untracked)}'
    unexpected_untracked = untracked - NEW_SOURCE - ALLOWED_REPORTS
    if unexpected_untracked:
        return f'unexpected untracked files: {sorted(unexpected_untracked)}'
    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'53F reports must remain untracked: {sorted(reports_tracked)}'
    if staged:
        return f'nothing may be staged: {sorted(staged)}'

    data_changes = {
        path for path in tracked | untracked
        if path == 'data' or path.startswith('data/')
    }
    if data_changes:
        return f'data/ changes are not allowed: {sorted(data_changes)}'

    protected_hits = {
        path for path in tracked
        if path in PROTECTED_PRODUCTION or path.startswith(PROTECTED_PREFIXES)
    }
    if protected_hits:
        return f'protected production changed: {sorted(protected_hits)}'

    production_changes = {
        path for path in tracked | untracked
        if path.startswith('backend/')
    }
    expected_production = {
        'backend/config/build_info.py',
        'backend/analysis/historical_setup_evidence.py',
    }
    if production_changes != expected_production:
        return f'production change scope must be exact: {sorted(production_changes)}'

    print(
        'F53_SCOPE_OK '
        f'head={head} tree={tree} '
        f'tracked={sorted(tracked)} untracked={sorted(untracked)}'
    )
    return None


def _validate_source_contract() -> str | None:
    if not MODULE_PATH.is_file():
        return 'missing backend/analysis/historical_setup_evidence.py'
    source = MODULE_PATH.read_text(encoding='utf-8')
    tree = ast.parse(source)
    imported = _imported_names(source)

    if 'def analyze_historical_setup_evidence(payload: dict) -> dict:' not in source:
        return 'public analyze_historical_setup_evidence(payload: dict) -> dict API is missing'
    if 'backend.analysis.premarket_structure' not in imported:
        return 'mandatory 53E2 premarket_structure import is missing'
    if 'analyze_premarket_structure' not in source:
        return 'mandatory 53E2 analyze_premarket_structure reuse is missing'

    direct_predecessors = {
        'backend.analysis.multi_timeframe',
        'backend.analysis.volume_vwap',
        'backend.analysis.key_levels_supply_demand',
        'backend.analysis.price_action_structure',
        'backend.analysis.candlestick_patterns',
        'backend.analysis.candle_anatomy',
    }
    if imported & direct_predecessors:
        return f'direct predecessor import found: {sorted(imported & direct_predecessors)}'
    forbidden_calls = {
        'analyze_multi_timeframe',
        'analyze_volume_vwap',
        'analyze_key_levels',
        'analyze_price_action_structure',
        'analyze_candlestick_patterns',
        'analyze_candle',
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if called_names & forbidden_calls:
        return f'direct predecessor call found: {sorted(called_names & forbidden_calls)}'
    e2_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'analyze_premarket_structure'
    ]
    if len(e2_calls) != 2:
        return f'source must contain two 53E2 call sites, found {len(e2_calls)}'

    mutable_globals = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
            mutable_globals.append(getattr(node, 'lineno', 0))
    if mutable_globals:
        return f'global mutable learning state found at lines {mutable_globals}'

    if imported & NETWORK_MODULES:
        return f'network import found: {sorted(imported & NETWORK_MODULES)}'
    if imported & MODEL_MODULES:
        return f'model/ML import found: {sorted(imported & MODEL_MODULES)}'
    lowered = source.lower()
    forbidden_dependencies = (
        'openai', 'anthropic', 'groq', 'ai_router', 'backend.news',
        'backend.collectors', 'backend.trading', 'backend.telegram',
        'broker', 'freshness', 'telegram', 'sklearn', 'joblib', 'pickle',
        'sqlite', 'redis',
    )
    for needle in forbidden_dependencies:
        if needle in lowered:
            return f'forbidden external dependency found: {needle}'
    write_needles = ('write_text', 'write_bytes', 'atomic_write', 'open(')
    for needle in write_needles:
        if needle in source:
            return f'filesystem write path found: {needle}'
    session_needles = (
        'datetime', 'zoneinfo', 'market_calendar', 'trading_calendar',
        'session_open', 'previous trading date', '09:00', '09:08', '09:15',
        'resample', 'aggregate_candles', 'timeframe_minutes', 'parse_timeframe',
        'current_time',
    )
    for needle in session_needles:
        if needle in lowered:
            return f'session/timeframe inference found: {needle}'
    forbidden_analytics = (
        'moving average', 'ema', 'rsi', 'macd', 'atr', 'bollinger', 'obv',
        'mfi', 'volume profile', 'order block', 'liquidity sweep',
        'score', 'weight', 'vote', 'ranking', 'probability', 'confidence',
        'recommendation', 'trade signal', 'position size', 'win rate',
        'expected return', 'nearest neighbor', 'clustering', 'regression',
        'classifier', 'random forest', 'xgboost', 'neural network',
        'cosine similarity', 'embedding',
    )
    for needle in forbidden_analytics:
        if re.search(rf'\b{re.escape(needle)}\b', lowered):
            return f'forbidden analytic, model, or trade interpretation found: {needle}'
    return None


def _validate_runtime_contract() -> str | None:
    import backend.analysis.historical_setup_evidence as module
    from backend.analysis.historical_setup_evidence import (
        FINGERPRINT_KEYS as MODULE_FINGERPRINT_KEYS,
        FINGERPRINT_VERSION,
        HISTORY_RECORD_KEYS as MODULE_HISTORY_KEYS,
        MATCH_SCOPE,
        MATCHED_EVIDENCE_KEYS as MODULE_MATCHED_KEYS,
        OUTCOME_SCOPE,
        OUTPUT_KEYS as MODULE_OUTPUT_KEYS,
        SCHEMA_VERSION,
        analyze_historical_setup_evidence,
    )
    import backend.analysis.premarket_structure as premarket

    if (SCHEMA_VERSION, MATCH_SCOPE, OUTCOME_SCOPE, FINGERPRINT_VERSION) != (
        '53F',
        'EXACT_53E2_FACT_FINGERPRINT',
        'CALLER_SUPPLIED_FORWARD_RETURN_RATIO',
        '53F-1',
    ):
        return 'constant contract mismatch'
    if MODULE_OUTPUT_KEYS != OUTPUT_KEYS:
        return f'closed key constant mismatch: {MODULE_OUTPUT_KEYS}'
    if MODULE_FINGERPRINT_KEYS != FINGERPRINT_KEYS:
        return f'fingerprint key constant mismatch: {MODULE_FINGERPRINT_KEYS}'
    if MODULE_HISTORY_KEYS != HISTORY_RECORD_KEYS:
        return f'history-record key constant mismatch: {MODULE_HISTORY_KEYS}'
    if MODULE_MATCHED_KEYS != MATCHED_EVIDENCE_KEYS:
        return f'matched-evidence key constant mismatch: {MODULE_MATCHED_KEYS}'

    malformed_inputs: list[object] = [
        None, [], 'payload', 1, True,
        {'outcome_horizon': '1h', 'history': []},
        {'current_snapshot': [], 'outcome_horizon': '1h', 'history': []},
        {'current_snapshot': _snapshot(), 'history': []},
        {'current_snapshot': _snapshot(), 'outcome_horizon': 1, 'history': []},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '  ', 'history': []},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h'},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': {}},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': ['bad']},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'forward_return_ratio': 0.1}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': [], 'forward_return_ratio': 0.1}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': _snapshot()}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': _snapshot(), 'forward_return_ratio': True}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': _snapshot(), 'forward_return_ratio': None}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': _snapshot(), 'forward_return_ratio': '0.1'}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': _snapshot(), 'forward_return_ratio': math.nan}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': _snapshot(), 'forward_return_ratio': math.inf}]},
        {'current_snapshot': _snapshot(), 'outcome_horizon': '1h', 'history': [{'snapshot': _snapshot(), 'forward_return_ratio': -math.inf}]},
        {
            'current_snapshot': _snapshot(),
            'outcome_horizon': '1h',
            'history': [
                {'snapshot': _snapshot(), 'forward_return_ratio': 0.1},
                {'snapshot': _snapshot()},
            ],
        },
    ]
    with patch.object(module, 'analyze_premarket_structure') as analyzer:
        for candidate in malformed_inputs:
            result = analyze_historical_setup_evidence(candidate)
            if result != MALFORMED_OUTPUT or tuple(result) != OUTPUT_KEYS:
                return f'outer malformed contract mismatch for {candidate!r}: {result!r}'
    if analyzer.call_count != 0:
        return 'outer malformed inputs called 53E2'

    large_ratio = 10 ** 400
    large_current = _snapshot()
    large_historical = _snapshot()
    large_payload = _payload(
        current=large_current,
        history=[{'snapshot': large_historical, 'forward_return_ratio': large_ratio}],
    )
    large_calls: list[object] = []
    large_real = premarket.analyze_premarket_structure

    def large_wrapped(snapshot):
        large_calls.append(snapshot)
        return large_real(snapshot)

    try:
        with patch.object(module, 'analyze_premarket_structure', side_effect=large_wrapped):
            large_result = module.analyze_historical_setup_evidence(large_payload)
    except OverflowError as exc:
        return f'large integer forward_return_ratio raised OverflowError: {exc}'
    if large_result['analysis_state'] == 'MALFORMED':
        return 'large integer forward_return_ratio was rejected by outer validation'
    if len(large_calls) != 2:
        return f'large integer payload did not reach 53E2 analysis: {len(large_calls)}'
    if large_calls[0] is not large_current or large_calls[1] is not large_historical:
        return 'large integer payload did not pass the original snapshot objects to 53E2'
    if large_result['analysis_state'] != 'OK':
        return f'large integer matching did not yield OK: {large_result["analysis_state"]}'
    large_record = large_result['history_records'][0]
    large_evidence = large_result['matched_evidence'][0]
    if large_record['outcome_state'] != 'POSITIVE':
        return f'large integer outcome was not POSITIVE: {large_record["outcome_state"]}'
    if large_record['forward_return_ratio'] is not large_ratio:
        return 'history_records did not keep the exact original integer ratio'
    if large_evidence['forward_return_ratio'] is not large_ratio:
        return 'matched_evidence did not keep the exact original integer ratio'
    if not large_record['matched']:
        return 'large integer matched sample was not marked matched'

    first_huge = 10 ** 400
    second_huge = first_huge + 2
    pair_current = _snapshot()
    pair_first = _snapshot()
    pair_second = _snapshot()
    pair_payload = _payload(
        current=pair_current,
        history=[
            {'snapshot': pair_first, 'forward_return_ratio': first_huge},
            {'snapshot': pair_second, 'forward_return_ratio': second_huge},
        ],
    )
    pair_calls: list[object] = []

    def pair_wrapped(snapshot):
        pair_calls.append(snapshot)
        return large_real(snapshot)

    try:
        with patch.object(module, 'analyze_premarket_structure', side_effect=pair_wrapped):
            pair_result = module.analyze_historical_setup_evidence(pair_payload)
    except OverflowError as exc:
        return f'matched huge integer pair raised OverflowError: {exc}'
    if pair_result['analysis_state'] == 'MALFORMED':
        return 'matched huge integer pair was rejected by outer validation'
    if len(pair_calls) != 3:
        return f'matched huge integer pair did not reach 53E2 analysis: {len(pair_calls)}'
    if pair_calls[0] is not pair_current or pair_calls[1] is not pair_first or pair_calls[2] is not pair_second:
        return 'matched huge integer pair did not pass original snapshot objects to 53E2'
    if pair_result['analysis_state'] != 'OK':
        return f'matched huge integer pair did not yield OK: {pair_result["analysis_state"]}'
    pair_records = pair_result['history_records']
    pair_evidence = pair_result['matched_evidence']
    if len(pair_records) != 2 or len(pair_evidence) != 2:
        return 'matched huge integer pair did not keep both history records'
    if not all(record['eligible'] and record['matched'] for record in pair_records):
        return 'matched huge integer pair records were not both eligible and matched'
    if pair_result['outcome_counts'] != {'POSITIVE': 2, 'NEGATIVE': 0, 'FLAT': 0}:
        return f'matched huge integer pair outcome_counts mismatch: {pair_result["outcome_counts"]}'
    if pair_records[0]['forward_return_ratio'] is not first_huge:
        return 'first huge integer was not preserved in history_records'
    if pair_records[1]['forward_return_ratio'] is not second_huge:
        return 'second huge integer was not preserved in history_records'
    if pair_evidence[0]['forward_return_ratio'] is not first_huge:
        return 'first huge integer was not preserved in matched_evidence'
    if pair_evidence[1]['forward_return_ratio'] is not second_huge:
        return 'second huge integer was not preserved in matched_evidence'
    if pair_result['min_forward_return_ratio'] != first_huge:
        return f'huge integer min mismatch: {pair_result["min_forward_return_ratio"]}'
    if pair_result['max_forward_return_ratio'] != second_huge:
        return f'huge integer max mismatch: {pair_result["max_forward_return_ratio"]}'
    if pair_result['mean_forward_return_ratio'] != first_huge + 1:
        return f'huge integer mean mismatch: {pair_result["mean_forward_return_ratio"]}'
    if pair_result['median_forward_return_ratio'] != first_huge + 1:
        return f'huge integer median mismatch: {pair_result["median_forward_return_ratio"]}'

    current = _snapshot()
    historical = _snapshot()
    excluded = _snapshot(frames=[{'timeframe': 'only', 'candles': _actual_candles()}])
    payload = _payload(current=current, history=[
        {'snapshot': historical, 'forward_return_ratio': 0.04},
        {'snapshot': excluded, 'forward_return_ratio': -0.02},
        {'snapshot': historical, 'forward_return_ratio': 0.0},
    ])
    calls: list[object] = []
    real = premarket.analyze_premarket_structure

    def wrapped(snapshot):
        calls.append(snapshot)
        return real(snapshot)

    with patch.object(module, 'analyze_premarket_structure', side_effect=wrapped):
        result = module.analyze_historical_setup_evidence(payload)
    if len(calls) != 4:
        return f'valid payload must call 53E2 once per snapshot, got {len(calls)}'
    if calls[0] is not current or calls[1] is not historical or calls[2] is not excluded:
        return '53E2 did not receive the exact original snapshot objects'

    if result['analysis_state'] != 'OK':
        return f'exact match did not yield OK: {result["analysis_state"]}'
    if result['source_current']['analysis_state'] != 'OK':
        return 'current source was not eligible OK'
    fingerprint = result['current_fingerprint']
    if tuple(fingerprint) != FINGERPRINT_KEYS:
        return f'fingerprint key contract mismatch: {tuple(fingerprint)}'
    if fingerprint['volume_state_counts'] is result['source_current']['volume_state_counts']:
        return 'volume_state_counts was not copied into a new fingerprint dict'
    if not result['history_records'][0]['matched'] or result['history_records'][1]['matched']:
        return 'exact-match-only semantics failed'
    if result['history_records'][0]['fingerprint'] != fingerprint:
        return 'matched historical fingerprint was not exactly equal'
    if result['history_eligible_count'] != 2 or result['history_excluded_count'] != 1:
        return 'eligible/excluded counts are inexact'

    first = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[{'snapshot': _snapshot(), 'forward_return_ratio': 0.11}],
    ))
    second = analyze_historical_setup_evidence(_payload(
        current=_snapshot(),
        history=[{'snapshot': _snapshot(), 'forward_return_ratio': -0.37}],
    ))
    if first['current_fingerprint'] != second['current_fingerprint']:
        return 'outcome leaked into the current fingerprint'
    if first['history_records'][0]['fingerprint'] != second['history_records'][0]['fingerprint']:
        return 'outcome leaked into the historical fingerprint'
    if first['history_records'][0]['matched'] != second['history_records'][0]['matched']:
        return 'outcome leaked into the matched boolean'
    if first['history_records'][0]['eligible'] != second['history_records'][0]['eligible']:
        return 'outcome leaked into eligible status'
    if first['outcome_counts'] == second['outcome_counts']:
        return 'outcome counts did not follow the recorded ratio'
    if first['history_records'][0]['outcome_state'] != 'POSITIVE':
        return 'positive ratio was not POSITIVE'
    if second['history_records'][0]['outcome_state'] != 'NEGATIVE':
        return 'negative ratio was not NEGATIVE'
    if result['history_records'][2]['outcome_state'] != 'FLAT':
        return 'zero ratio was not FLAT'

    matched_values = [0.04, 0.0]
    if result['mean_forward_return_ratio'] != sum(matched_values) / len(matched_values):
        return 'mean_forward_return_ratio is inexact'
    if result['median_forward_return_ratio'] != statistics.median(matched_values):
        return 'median_forward_return_ratio is inexact'
    if result['min_forward_return_ratio'] != min(matched_values):
        return 'min_forward_return_ratio is inexact'
    if result['max_forward_return_ratio'] != max(matched_values):
        return 'max_forward_return_ratio is inexact'

    owned_keys = list(result) + list(fingerprint) + list(result['history_records'][0]) + list(result['matched_evidence'][0])
    forbidden_keys = {
        'win_rate', 'hit_rate', 'success_rate', 'probability', 'confidence',
        'expected_return', 'expected_profit', 'score', 'weight', 'ranking',
        'recommendation',
    }
    if forbidden_keys & {key.lower() for key in owned_keys}:
        return f'probability/win-rate/confidence/expected-return key found: {owned_keys}'

    if tuple(result) != OUTPUT_KEYS:
        return f'runtime output is not closed or ordered: {tuple(result)}'
    if any(tuple(record) != HISTORY_RECORD_KEYS for record in result['history_records']):
        return 'history records are not closed'
    if any(tuple(record) != MATCHED_EVIDENCE_KEYS for record in result['matched_evidence']):
        return 'matched evidence records are not closed'

    original = _payload(
        current=_snapshot(),
        history=[{'snapshot': _snapshot(), 'forward_return_ratio': 0.04}],
    )
    before = copy.deepcopy(original)
    first_run = analyze_historical_setup_evidence(original)
    second_run = analyze_historical_setup_evidence(original)
    if original != before:
        return 'analyzer mutated the input payload or nested snapshots'
    if first_run != second_run:
        return 'same full input did not produce identical output'
    reordered = {
        'history': original['history'],
        'outcome_horizon': original['outcome_horizon'],
        'current_snapshot': {
            key: original['current_snapshot'][key]
            for key in reversed(tuple(original['current_snapshot']))
        },
    }
    if analyze_historical_setup_evidence(reordered) != first_run:
        return 'payload dictionary key order changed output'
    return None


def main() -> int:
    watched_paths = [PROJECT_ROOT / path for path in sorted(WATCHED_RELATIVE)]
    before = {str(path): _digest(path) for path in watched_paths}

    try:
        if _git_paths('status', '--short', '--', 'data'):
            return _fail('repository data/ is dirty before validation')
        scope_error = _validate_repository_scope()
    except RuntimeError as exc:
        return _fail(f'Git scope collection failed: {exc}')
    if scope_error:
        return _fail(scope_error)
    print('V1_BASELINE_SCOPE_BUILD_INPUTS_OK')

    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('53F', 'AstraEdge 53F'):
        return _fail(f'build must be exact 53F / AstraEdge 53F, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')

    source_error = _validate_source_contract()
    if source_error:
        return _fail(source_error)
    print('V2_API_REUSE_DEPENDENCY_EFFECT_BOUNDARIES_OK')

    runtime_error = _validate_runtime_contract()
    if runtime_error:
        return _fail(runtime_error)
    print('V3_ELIGIBILITY_FINGERPRINT_MATCH_AND_OUTCOME_OK')

    for path in sorted(PROTECTED_PRODUCTION):
        if _git_paths('diff', '--name-only', 'HEAD', '--', path):
            return _fail(f'protected predecessor production changed: {path}')
    prefix_hits = {
        path for path in _git_paths('diff', '--name-only', 'HEAD', '--')
        if path.startswith(PROTECTED_PREFIXES)
    }
    if prefix_hits:
        return _fail(f'protected production prefix changed: {sorted(prefix_hits)}')
    print('V4_PROTECTED_PRODUCTION_UNCHANGED_OK')

    focused_error, focused_output = _run_script(
        'scripts/test_historical_setup_evidence_53f.py',
        'HISTORICAL_SETUP_EVIDENCE_53F_PASS',
        'focused 53F tests',
    )
    if focused_error:
        return _fail(focused_error)
    focused_lines = {line.strip() for line in focused_output.splitlines()}
    missing_markers = [marker for marker in REQUIRED_FOCUSED_MARKERS if marker not in focused_lines]
    if missing_markers:
        return _fail(f'focused marker verification failed: missing={missing_markers}')
    print('V5_FOCUSED_T1_T72_OK')

    regressions = (
        ('scripts/validate_premarket_structure_53e2.py', 'PHASE_53E2_VALIDATION_PASS', '53E2'),
        ('scripts/validate_multi_timeframe_53e.py', 'PHASE_53E_VALIDATION_PASS', '53E'),
        ('scripts/validate_volume_vwap_53d.py', 'PHASE_53D_VALIDATION_PASS', '53D'),
        ('scripts/validate_key_levels_supply_demand_53c.py', 'PHASE_53C_VALIDATION_PASS', '53C'),
        ('scripts/validate_price_action_structure_53b.py', 'PHASE_53B_VALIDATION_PASS', '53B'),
        ('scripts/validate_candlestick_patterns_53a2.py', 'PHASE_53A2_VALIDATION_PASS', '53A2'),
        ('scripts/validate_candle_anatomy_53a.py', 'PHASE_53A_VALIDATION_PASS', '53A'),
        ('scripts/validate_event_age_freshness_52r_d2.py', 'PHASE_52R_D2_VALIDATION_PASS', '52R_D2'),
    )
    for path, marker, label in regressions:
        error, _ = _run_script(path, marker, f'{label} regression')
        if error:
            return _fail(error)
        print(f'V6_{label}_REGRESSION_OK')

    compile_targets = sorted(
        EXPECTED_TRACKED_CHANGES
        | NEW_SOURCE
        | PROTECTED_PRODUCTION
    )
    compiled = subprocess.run(
        [sys.executable, '-m', 'py_compile', *compile_targets],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return _fail(f'py_compile failed: {compiled.stderr or compiled.stdout}')
    print('V7_PY_COMPILE_OK')

    diff_check = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        return _fail(f'git diff --check failed: {diff_check.stdout or diff_check.stderr}')
    print('V8_GIT_DIFF_CHECK_OK')

    after = {str(path): _digest(path) for path in watched_paths}
    if before != after:
        changed = sorted(path for path in before if before[path] != after[path])
        return _fail(f'validator mutated watched files: {changed}')

    try:
        staged = _git_paths('diff', '--cached', '--name-only')
        data_after = _git_paths('status', '--short', '--', 'data')
        final_head = _git_value('rev-parse', 'HEAD')
        final_tree = _git_value('rev-parse', 'HEAD^{tree}')
    except RuntimeError as exc:
        return _fail(f'final Git state collection failed: {exc}')
    if staged:
        return _fail(f'nothing may be staged: {sorted(staged)}')
    if data_after:
        return _fail(f'repository data/ is dirty: {sorted(data_after)}')
    if (final_head, final_tree) != (BASELINE_HEAD, BASELINE_TREE):
        return _fail(f'final HEAD/tree changed: {final_head} / {final_tree}')
    print('V9_FINAL_REPOSITORY_STATE_OK')

    print('PHASE_53F_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
