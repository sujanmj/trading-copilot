#!/usr/bin/env python3
"""Independent read-only validator for AstraEdge 53G full-stack facade."""

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
BASELINE_HEAD = '52dc868d5cf1aad2ffb179a5f4ad2ad674eb276f'
BASELINE_TREE = 'e17ffb3b7069baee7786ead330795ecfad252054'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'full_stack.py'

COMPATIBILITY_FILES = {
    'scripts/test_historical_setup_evidence_53f.py',
    'scripts/validate_historical_setup_evidence_53f.py',
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
    'backend/analysis/full_stack.py',
    'scripts/test_full_stack_53g.py',
    'scripts/validate_full_stack_53g.py',
}

ALLOWED_REPORTS = {'phase53g_review.txt', 'phase53g_diff.txt'}

PROTECTED_PRODUCTION = {
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/analysis/price_action_structure.py',
    'backend/analysis/key_levels_supply_demand.py',
    'backend/analysis/volume_vwap.py',
    'backend/analysis/multi_timeframe.py',
    'backend/analysis/premarket_structure.py',
    'backend/analysis/historical_setup_evidence.py',
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
    'source_historical_setup_evidence',
)

REQUIRED_FOCUSED_MARKERS = tuple(f'T{index}' for index in range(1, 61)) + (
    'FULL_STACK_53G_PASS',
)

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
MODEL_MODULES = frozenset({
    'sklearn', 'numpy', 'pandas', 'joblib', 'torch', 'tensorflow', 'xgboost',
})


def _fail(message: str) -> int:
    print(f'ASTRAEDGE_PHASE_53G_FULL_STACK_FAIL: {message}', file=sys.stderr)
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


def _insufficient_snapshot() -> dict:
    return _snapshot(frames=[
        {'timeframe': 'only', 'candles': _actual_candles()},
    ])


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
        return f'53G source files must be new and untracked: {sorted(NEW_SOURCE - untracked)}'
    unexpected_untracked = untracked - NEW_SOURCE - ALLOWED_REPORTS
    if unexpected_untracked:
        return f'unexpected untracked files: {sorted(unexpected_untracked)}'
    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'53G reports must remain untracked: {sorted(reports_tracked)}'
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
        'backend/analysis/full_stack.py',
    }
    if production_changes != expected_production:
        return f'production change scope must be exact: {sorted(production_changes)}'
    if 'backend/analysis/historical_setup_evidence.py' in tracked:
        return 'backend/analysis/historical_setup_evidence.py must remain byte-identical'

    print(
        'G53_SCOPE_OK '
        f'head={head} tree={tree} '
        f'tracked={sorted(tracked)} untracked={sorted(untracked)}'
    )
    return None


def _validate_source_contract() -> str | None:
    if not MODULE_PATH.is_file():
        return 'missing backend/analysis/full_stack.py'
    source = MODULE_PATH.read_text(encoding='utf-8')
    tree = ast.parse(source)
    imported = _imported_names(source)

    if 'def analyze_full_stack(payload: dict) -> dict:' not in source:
        return 'public analyze_full_stack(payload: dict) -> dict API is missing'
    if 'backend.analysis.historical_setup_evidence' not in imported:
        return 'mandatory 53F historical_setup_evidence import is missing'
    if 'analyze_historical_setup_evidence' not in source:
        return 'mandatory 53F analyze_historical_setup_evidence reuse is missing'

    direct_predecessors = {
        'backend.analysis.premarket_structure',
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
        'analyze_premarket_structure',
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
    f_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'analyze_historical_setup_evidence'
    ]
    if len(f_calls) != 1:
        return f'source must contain one 53F call site, found {len(f_calls)}'

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
    import backend.analysis.full_stack as module
    from backend.analysis.full_stack import (
        OUTPUT_KEYS as MODULE_OUTPUT_KEYS,
        SCHEMA_VERSION,
        analyze_full_stack,
    )

    if SCHEMA_VERSION != '53G':
        return f'schema_version constant mismatch: {SCHEMA_VERSION}'
    if MODULE_OUTPUT_KEYS != OUTPUT_KEYS:
        return f'closed key constant mismatch: {MODULE_OUTPUT_KEYS}'

    payload = _payload(
        current=_snapshot(),
        history=[{'snapshot': _snapshot(), 'forward_return_ratio': 0.04}],
    )
    calls: list[object] = []
    sentinel = {'schema_version': '53F', 'analysis_state': 'OK', 'token': object()}

    def wrapped(argument):
        calls.append(argument)
        return sentinel

    with patch.object(module, 'analyze_historical_setup_evidence', side_effect=wrapped):
        result = module.analyze_full_stack(payload)
    if len(calls) != 1 or calls[0] is not payload:
        return '53G did not pass the original payload object to 53F exactly once'
    if tuple(result) != OUTPUT_KEYS:
        return f'closed output keys mismatch: {tuple(result)}'
    if result['schema_version'] != '53G':
        return f'schema_version mismatch: {result["schema_version"]}'
    if result['analysis_state'] != 'OK':
        return 'analysis_state was not copied from 53F'
    if result['source_historical_setup_evidence'] is not sentinel:
        return 'source_historical_setup_evidence is not the exact 53F object'

    for state in ('MALFORMED', 'SOURCE_NOT_READY', 'NO_MATCHES', 'OK'):
        delegated = {'schema_version': '53F', 'analysis_state': state}
        with patch.object(module, 'analyze_historical_setup_evidence', return_value=delegated):
            propagated = module.analyze_full_stack({'garbage': True})
        if propagated['analysis_state'] != state:
            return f'{state} was not propagated exactly'
        if propagated['source_historical_setup_evidence'] is not delegated:
            return f'{state} did not keep the exact 53F object'

    real = analyze_full_stack(_payload(
        current=_snapshot(),
        history=[
            {'snapshot': _snapshot(), 'forward_return_ratio': 0.04},
            {'snapshot': _insufficient_snapshot(), 'forward_return_ratio': 0.10},
            {'snapshot': _snapshot(), 'forward_return_ratio': -0.02},
            {'snapshot': _snapshot(observation_price=90.0), 'forward_return_ratio': 0.50},
            {'snapshot': _snapshot(), 'forward_return_ratio': 0.0},
        ],
    ))
    historical = real['source_historical_setup_evidence']
    if real['analysis_state'] != historical['analysis_state']:
        return '53G analysis_state diverged from 53F'
    if historical.get('schema_version') != '53F':
        return 'real invocation did not reach 53F'
    current = historical.get('source_current') or {}
    if current.get('schema_version') != '53E2':
        return 'real lineage did not reach 53E2'
    multi = current.get('source_multi_timeframe') or {}
    if multi.get('schema_version') != '53E':
        return 'real lineage did not reach 53E'
    frames = multi.get('frames') or []
    if not frames or frames[0].get('source_key_levels', {}).get('schema_version') != '53C':
        return 'real lineage did not expose 53C'
    if frames[0]['source_key_levels'].get('source_structure', {}).get('schema_version') != '53B':
        return '53C lineage did not expose predecessor structure facts'
    volume = frames[0].get('source_volume_vwap') or {}
    if volume.get('schema_version') != '53D':
        return 'real lineage did not expose 53D'
    if [frame['timeframe'] for frame in frames] != ['opaque-zeta', 'custom alpha']:
        return 'frame order was not preserved'
    if [record['history_index'] for record in historical['history_records']] != list(range(5)):
        return 'history order was not preserved'
    if historical['matched_sample_count'] != 3:
        return f'matched_sample_count mismatch: {historical["matched_sample_count"]}'
    matched_values = [0.04, -0.02, 0.0]
    if historical['mean_forward_return_ratio'] != sum(matched_values) / 3:
        return 'ordinary mean mismatch'
    if historical['median_forward_return_ratio'] != statistics.median(matched_values):
        return 'ordinary median mismatch'
    if historical['min_forward_return_ratio'] != min(matched_values):
        return 'min mismatch'
    if historical['max_forward_return_ratio'] != max(matched_values):
        return 'max mismatch'

    before = copy.deepcopy(payload)
    analyze_full_stack(payload)
    if payload != before:
        return 'payload was mutated'

    first = analyze_full_stack(payload)
    second = analyze_full_stack(payload)
    if first != second:
        return 'repeated invocation was not deterministic'
    reordered = {
        'history': payload['history'],
        'outcome_horizon': payload['outcome_horizon'],
        'current_snapshot': payload['current_snapshot'],
    }
    if analyze_full_stack(reordered) != first:
        return 'payload dictionary key order changed the result'

    first_huge = 10 ** 400
    second_huge = first_huge + 2
    try:
        huge = analyze_full_stack(_payload(
            current=_snapshot(),
            history=[
                {'snapshot': _snapshot(), 'forward_return_ratio': first_huge},
                {'snapshot': _snapshot(), 'forward_return_ratio': second_huge},
            ],
        ))
    except OverflowError as exc:
        return f'matched huge integer pair raised OverflowError: {exc}'
    huge_source = huge['source_historical_setup_evidence']
    if huge['analysis_state'] != 'OK' or huge_source['matched_sample_count'] != 2:
        return 'huge integer pair did not yield OK with two matches'
    if huge_source['mean_forward_return_ratio'] != first_huge + 1:
        return 'huge integer mean mismatch'
    if huge_source['median_forward_return_ratio'] != first_huge + 1:
        return 'huge integer median mismatch'
    if huge_source['min_forward_return_ratio'] != first_huge:
        return 'huge integer min mismatch'
    if huge_source['max_forward_return_ratio'] != second_huge:
        return 'huge integer max mismatch'

    leak_current = _snapshot()
    leak_history = _snapshot()
    leak_a = analyze_full_stack(_payload(
        current=leak_current,
        history=[{'snapshot': leak_history, 'forward_return_ratio': 0.04}],
    ))
    leak_b = analyze_full_stack(_payload(
        current=leak_current,
        history=[{'snapshot': leak_history, 'forward_return_ratio': -0.07}],
    ))
    source_a = leak_a['source_historical_setup_evidence']
    source_b = leak_b['source_historical_setup_evidence']
    if source_a['current_fingerprint'] != source_b['current_fingerprint']:
        return 'outcome-only mutation altered fingerprint'
    if source_a['history_records'][0]['matched'] != source_b['history_records'][0]['matched']:
        return 'outcome-only mutation altered match boolean'
    if source_a['source_current'] != source_b['source_current']:
        return 'outcome-only mutation altered analytical lineage'

    baseline_payload = _payload(
        current=_snapshot(),
        history=[{'snapshot': _snapshot(), 'forward_return_ratio': 0.04}],
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
    baseline_frames = baseline['source_historical_setup_evidence']['source_current']['source_multi_timeframe']['frames']
    extended_frames = extended['source_historical_setup_evidence']['source_current']['source_multi_timeframe']['frames']
    if baseline_frames[1] != extended_frames[1]:
        return 'future candle on frame A changed frame B'
    baseline_key = baseline_frames[0]['source_key_levels']
    extended_key = extended_frames[0]['source_key_levels']
    if extended_key['source_structure']['candle_anatomy'][:prefix_count] != baseline_key['source_structure']['candle_anatomy']:
        return 'future candle changed earlier 53C anatomy records'
    if extended_frames[0]['source_volume_vwap']['records'][:prefix_count] != baseline_frames[0]['source_volume_vwap']['records']:
        return 'future candle changed earlier 53D records'

    if analyze_full_stack(_payload(history=[{'snapshot': _snapshot(), 'forward_return_ratio': math.nan}]))['analysis_state'] != 'MALFORMED':
        return 'NaN outcome was accepted'
    if analyze_full_stack(_payload(history=[{'snapshot': _snapshot(), 'forward_return_ratio': math.inf}]))['analysis_state'] != 'MALFORMED':
        return '+inf outcome was accepted'
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

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('53G', 'AstraEdge 53G'):
        return _fail(f'build must be exact 53G / AstraEdge 53G, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')

    source_error = _validate_source_contract()
    if source_error:
        return _fail(source_error)
    print('V2_API_REUSE_DEPENDENCY_EFFECT_BOUNDARIES_OK')

    runtime_error = _validate_runtime_contract()
    if runtime_error:
        return _fail(runtime_error)
    print('V3_DELEGATION_LINEAGE_AND_HARDENING_OK')

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
        'scripts/test_full_stack_53g.py',
        'FULL_STACK_53G_PASS',
        'focused 53G tests',
    )
    if focused_error:
        return _fail(focused_error)
    focused_lines = {line.strip() for line in focused_output.splitlines()}
    missing_markers = [marker for marker in REQUIRED_FOCUSED_MARKERS if marker not in focused_lines]
    if missing_markers:
        return _fail(f'focused marker verification failed: missing={missing_markers}')
    print('V5_FOCUSED_T1_T60_OK')

    regressions = (
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

    print('PHASE_53G_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
