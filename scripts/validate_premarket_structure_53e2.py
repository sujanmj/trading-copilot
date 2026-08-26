#!/usr/bin/env python3
"""Independent read-only validator for AstraEdge 53E2 premarket structure."""

from __future__ import annotations

import ast
import copy
import hashlib
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_HEAD = 'eeaeb222fdc02a29bdda76c03de0f56d85bb3ceb'
BASELINE_TREE = '6962e5556de1f08a826f1c4eb8b8bb63ece0fd75'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

MODULE_PATH = PROJECT_ROOT / 'backend' / 'analysis' / 'premarket_structure.py'

COMPATIBILITY_FILES = {
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
    'backend/analysis/premarket_structure.py',
    'scripts/test_premarket_structure_53e2.py',
    'scripts/validate_premarket_structure_53e2.py',
}

ALLOWED_REPORTS = {
    'phase53e2_review.txt',
    'phase53e2_diff.txt',
    'phase53f_review.txt',
    'phase53f_diff.txt',
}

COMMITTED_53E2_HEAD = 'e43be3ca8b3c2036fb8a7a85078c9e6911289f25'
COMMITTED_53E2_TREE = '66ec9e271d3851f78d593a11fa542d30cccdbcbe'

ALLOWED_SUCCESSOR_53F = {
    'backend/analysis/historical_setup_evidence.py',
    'scripts/test_historical_setup_evidence_53f.py',
    'scripts/validate_historical_setup_evidence_53f.py',
}

SUCCESSOR_53F_TRACKED_CHANGES = (
    {'backend/config/build_info.py'}
    | COMPATIBILITY_FILES
    | {
        'scripts/test_premarket_structure_53e2.py',
        'scripts/validate_premarket_structure_53e2.py',
    }
)

SUCCESSOR_53F_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/historical_setup_evidence.py',
}

PROTECTED_PRODUCTION = {
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/analysis/price_action_structure.py',
    'backend/analysis/key_levels_supply_demand.py',
    'backend/analysis/volume_vwap.py',
    'backend/analysis/multi_timeframe.py',
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
    | ALLOWED_SUCCESSOR_53F
    | ALLOWED_REPORTS
    | PROTECTED_PRODUCTION
)

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'premarket_scope',
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
    'timeframe_count',
    'structure_alignment',
    'structure_alignment_frame_count',
    'vwap_alignment',
    'vwap_alignment_frame_count',
    'volume_state_counts',
    'source_multi_timeframe',
)

ZERO_VOLUME_COUNTS = {
    'HIGH_VOLUME': 0,
    'NORMAL_VOLUME': 0,
    'LOW_VOLUME': 0,
    'UNDEFINED': 0,
}

MALFORMED_OUTPUT = {
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
    'volume_state_counts': ZERO_VOLUME_COUNTS,
    'source_multi_timeframe': None,
}

REQUIRED_FOCUSED_MARKERS = tuple(f'T{index}' for index in range(1, 73)) + (
    'PREMARKET_STRUCTURE_53E2_PASS',
)

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})


def _fail(message: str) -> int:
    print(f'ASTRAEDGE_PHASE_53E2_PREMARKET_STRUCTURE_FAIL: {message}', file=sys.stderr)
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


def _source_result(
    *,
    state: str = 'OK',
    counts: dict[str, int] | None = None,
) -> dict:
    return {
        'schema_version': '53E',
        'analysis_state': state,
        'timeframe_count': 7,
        'alignment_scope': 'CALLER_SUPPLIED_WINDOWS',
        'min_timeframes': 2,
        'min_alignment_frames': 2,
        'structure_alignment': 'ARBITRARY_STRUCTURE_FACT',
        'structure_alignment_frame_count': 5,
        'vwap_alignment': 'ARBITRARY_VWAP_FACT',
        'vwap_alignment_frame_count': 4,
        'volume_state_counts': counts if counts is not None else {
            'HIGH_VOLUME': 1,
            'NORMAL_VOLUME': 2,
            'LOW_VOLUME': 3,
            'UNDEFINED': 1,
        },
        'frames': [
            {'timeframe': 'caller-second'},
            {'timeframe': 'caller-first'},
        ],
    }


def _snapshot(**overrides) -> dict:
    value = {
        'previous_close': 100,
        'premarket_reference_price': 102,
        'premarket_high': 105,
        'premarket_low': 95,
        'observation_price': 103,
        'frames': [
            {'timeframe': 'caller-second', 'candles': []},
            {'timeframe': 'caller-first', 'candles': []},
        ],
    }
    value.update(overrides)
    return value


def _analyze_with_source(snapshot: dict, source: dict | None = None) -> tuple[dict, object]:
    import backend.analysis.premarket_structure as module

    delegated = source if source is not None else _source_result()
    with patch.object(module, 'analyze_multi_timeframe', return_value=delegated) as analyzer:
        result = module.analyze_premarket_structure(snapshot)
    return result, analyzer


def _validate_repository_scope() -> str | None:
    head = _git_value('rev-parse', 'HEAD')
    tree = _git_value('rev-parse', 'HEAD^{tree}')
    successor_mode = head == COMMITTED_53E2_HEAD
    if successor_mode:
        if tree != COMMITTED_53E2_TREE:
            return f'committed 53E2 HEAD tree must remain {COMMITTED_53E2_TREE}, got {tree}'
    else:
        if head != BASELINE_HEAD:
            return f'HEAD must remain {BASELINE_HEAD}, got {head}'
        if tree != BASELINE_TREE:
            return f'HEAD tree must remain {BASELINE_TREE}, got {tree}'

    tracked = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    staged = _git_paths('diff', '--cached', '--name-only')
    expected_tracked = SUCCESSOR_53F_TRACKED_CHANGES if successor_mode else EXPECTED_TRACKED_CHANGES
    if tracked != expected_tracked:
        missing = sorted(expected_tracked - tracked)
        unexpected = sorted(tracked - expected_tracked)
        return f'tracked change scope mismatch: missing={missing} unexpected={unexpected}'
    if successor_mode:
        if not NEW_SOURCE <= tracked_now:
            return f'missing committed 53E2 source files: {sorted(NEW_SOURCE - tracked_now)}'
        if 'backend/analysis/premarket_structure.py' in tracked:
            return 'backend/analysis/premarket_structure.py must remain unchanged for 53F'
        if not ALLOWED_SUCCESSOR_53F <= untracked:
            return f'missing required 53F successor files: {sorted(ALLOWED_SUCCESSOR_53F - untracked)}'
        unexpected_untracked = untracked - ALLOWED_SUCCESSOR_53F - ALLOWED_REPORTS
    else:
        if not NEW_SOURCE <= untracked:
            return f'53E2 source files must be new and untracked: {sorted(NEW_SOURCE - untracked)}'
        unexpected_untracked = untracked - NEW_SOURCE - ALLOWED_REPORTS
    if unexpected_untracked:
        return f'unexpected untracked files: {sorted(unexpected_untracked)}'
    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'53E2 reports must remain untracked: {sorted(reports_tracked)}'
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
    expected_production = SUCCESSOR_53F_PRODUCTION if successor_mode else {
        'backend/config/build_info.py',
        'backend/analysis/premarket_structure.py',
    }
    if production_changes != expected_production:
        return f'production change scope must be exact: {sorted(production_changes)}'

    print(
        'E2_SCOPE_OK '
        f'head={head} tree={tree} '
        f'tracked={sorted(tracked)} untracked={sorted(untracked)}'
    )
    return None


def _validate_source_contract() -> str | None:
    if not MODULE_PATH.is_file():
        return 'missing backend/analysis/premarket_structure.py'
    source = MODULE_PATH.read_text(encoding='utf-8')
    tree = ast.parse(source)
    imported = _imported_names(source)

    if 'def analyze_premarket_structure(snapshot: dict) -> dict:' not in source:
        return 'public analyze_premarket_structure(snapshot: dict) -> dict API is missing'
    if 'backend.analysis.multi_timeframe' not in imported:
        return 'mandatory 53E multi_timeframe import is missing'
    direct_predecessors = {
        'backend.analysis.candle_anatomy',
        'backend.analysis.candlestick_patterns',
        'backend.analysis.price_action_structure',
        'backend.analysis.key_levels_supply_demand',
        'backend.analysis.volume_vwap',
    }
    if imported & direct_predecessors:
        return f'direct predecessor import found: {sorted(imported & direct_predecessors)}'
    forbidden_calls = {
        'analyze_candle',
        'analyze_candlestick_patterns',
        'analyze_price_action_structure',
        'analyze_key_levels',
        'analyze_volume_vwap',
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if called_names & forbidden_calls:
        return f'direct predecessor call found: {sorted(called_names & forbidden_calls)}'
    mtf_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'analyze_multi_timeframe'
    ]
    if len(mtf_calls) != 1:
        return f'source must contain one 53E call site, found {len(mtf_calls)}'

    mutable_globals = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
            mutable_globals.append(getattr(node, 'lineno', 0))
    if mutable_globals:
        return f'global mutable state found at lines {mutable_globals}'

    if imported & NETWORK_MODULES:
        return f'network import found: {sorted(imported & NETWORK_MODULES)}'
    lowered = source.lower()
    forbidden_dependencies = (
        'openai', 'anthropic', 'groq', 'ai_router', 'backend.news',
        'backend.collectors', 'backend.trading', 'backend.telegram',
        'broker', 'freshness', 'telegram',
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
    )
    for needle in session_needles:
        if needle in lowered:
            return f'session/timeframe inference found: {needle}'
    forbidden_analytics = (
        'moving average', 'ema', 'rsi', 'macd', 'atr', 'bollinger', 'obv',
        'mfi', 'volume profile', 'order block', 'liquidity sweep',
        'score', 'weight', 'vote', 'ranking', 'probability', 'confidence',
        'recommendation', 'trade signal', 'position size', 'risk-on', 'risk-off',
    )
    for needle in forbidden_analytics:
        if re.search(rf'\b{re.escape(needle)}\b', lowered):
            return f'forbidden analytic or trade interpretation found: {needle}'
    return None


def _validate_runtime_contract() -> str | None:
    import backend.analysis.premarket_structure as module
    from backend.analysis.premarket_structure import (
        OUTPUT_KEYS as MODULE_OUTPUT_KEYS,
        PREMARKET_SCOPE,
        SCHEMA_VERSION,
        analyze_premarket_structure,
    )

    if (SCHEMA_VERSION, PREMARKET_SCOPE) != (
        '53E2',
        'CALLER_SUPPLIED_PREMARKET_SNAPSHOT',
    ):
        return f'constant contract mismatch: {SCHEMA_VERSION!r} / {PREMARKET_SCOPE!r}'
    if MODULE_OUTPUT_KEYS != OUTPUT_KEYS:
        return f'closed key constant mismatch: {MODULE_OUTPUT_KEYS}'

    malformed_inputs: list[object] = [None, [], 'snapshot', 1, True]
    required = (
        'previous_close', 'premarket_reference_price', 'premarket_high',
        'premarket_low', 'observation_price', 'frames',
    )
    for key in required:
        candidate = _snapshot()
        del candidate[key]
        malformed_inputs.append(candidate)
    invalid_numbers = (True, None, '100', math.nan, math.inf, -math.inf)
    for key in required[:-1]:
        for invalid in invalid_numbers:
            malformed_inputs.append(_snapshot(**{key: invalid}))
    malformed_inputs.extend((
        _snapshot(frames={}),
        _snapshot(premarket_high=94),
        _snapshot(premarket_reference_price=94),
        _snapshot(premarket_reference_price=106),
    ))
    with patch.object(module, 'analyze_multi_timeframe') as analyzer:
        for candidate in malformed_inputs:
            result = analyze_premarket_structure(candidate)
            if result != MALFORMED_OUTPUT or tuple(result) != OUTPUT_KEYS:
                return f'outer malformed contract mismatch for {candidate!r}: {result!r}'
    if analyzer.call_count != 0:
        return 'outer malformed inputs called 53E'

    frames = _snapshot()['frames']
    snapshot = _snapshot(frames=frames)
    source = _source_result()
    with patch.object(module, 'analyze_multi_timeframe', return_value=source) as analyzer:
        result = analyze_premarket_structure(snapshot)
    if analyzer.call_count != 1:
        return f'valid snapshot must call 53E exactly once, got {analyzer.call_count}'
    if analyzer.call_args.args != (frames,) or analyzer.call_args.args[0] is not frames:
        return 'valid snapshot did not pass the exact original frames object to 53E'
    if result['source_multi_timeframe'] is not source:
        return 'source_multi_timeframe is not the exact 53E result object'
    if tuple(result) != OUTPUT_KEYS:
        return f'runtime output is not closed or ordered: {tuple(result)}'

    for state in ('OK', 'PARTIAL', 'INSUFFICIENT_TIMEFRAMES', 'MALFORMED'):
        delegated = _source_result(state=state)
        propagated, analyzer = _analyze_with_source(_snapshot(), delegated)
        if analyzer.call_count != 1 or propagated['analysis_state'] != state:
            return f'53E state was reinterpreted: {state} -> {propagated["analysis_state"]}'
        if propagated['gap_points'] != 2 or propagated['premarket_range_points'] != 10:
            return f'valid scalar facts were erased for delegated state {state}'

    counts = {'HIGH_VOLUME': 9, 'NORMAL_VOLUME': 8, 'LOW_VOLUME': 7, 'UNDEFINED': 6}
    delegated = _source_result(counts=counts)
    propagated, _ = _analyze_with_source(_snapshot(), delegated)
    expected_aggregates = (
        delegated['timeframe_count'],
        delegated['structure_alignment'],
        delegated['structure_alignment_frame_count'],
        delegated['vwap_alignment'],
        delegated['vwap_alignment_frame_count'],
    )
    actual_aggregates = (
        propagated['timeframe_count'],
        propagated['structure_alignment'],
        propagated['structure_alignment_frame_count'],
        propagated['vwap_alignment'],
        propagated['vwap_alignment_frame_count'],
    )
    if actual_aggregates != expected_aggregates:
        return f'53E aggregate propagation mismatch: {actual_aggregates}'
    if propagated['volume_state_counts'] is not counts:
        return 'volume_state_counts was recalculated or copied instead of propagated exactly'

    cases = (
        (_snapshot(), (2, 0.02, 'GAP_UP', 10, 0.1)),
        (_snapshot(premarket_reference_price=98), (-2, -0.02, 'GAP_DOWN', 10, 0.1)),
        (_snapshot(premarket_reference_price=100), (0, 0.0, 'FLAT', 10, 0.1)),
        (
            _snapshot(
                previous_close=0,
                premarket_reference_price=2,
                premarket_high=3,
                premarket_low=1,
            ),
            (2, None, 'GAP_UP', 2, None),
        ),
        (
            _snapshot(
                previous_close=-100,
                premarket_reference_price=-97,
                premarket_high=-95,
                premarket_low=-105,
                observation_price=-96,
            ),
            (3, 0.03, 'GAP_UP', 10, 0.1),
        ),
    )
    for candidate, expected in cases:
        value, _ = _analyze_with_source(candidate)
        actual = (
            value['gap_points'], value['gap_ratio'], value['gap_state'],
            value['premarket_range_points'], value['premarket_range_ratio'],
        )
        if actual != expected:
            return f'gap/range math mismatch: expected={expected} actual={actual}'

    relation_cases = (
        (_snapshot(observation_price=106), 'ABOVE_PREVIOUS_CLOSE', 'ABOVE_PREMARKET_REFERENCE', 'ABOVE_PREMARKET_RANGE'),
        (_snapshot(observation_price=94), 'BELOW_PREVIOUS_CLOSE', 'BELOW_PREMARKET_REFERENCE', 'BELOW_PREMARKET_RANGE'),
        (_snapshot(observation_price=100), 'AT_PREVIOUS_CLOSE', 'BELOW_PREMARKET_REFERENCE', 'INSIDE_PREMARKET_RANGE'),
        (_snapshot(observation_price=102), 'ABOVE_PREVIOUS_CLOSE', 'AT_PREMARKET_REFERENCE', 'INSIDE_PREMARKET_RANGE'),
        (_snapshot(observation_price=105), 'ABOVE_PREVIOUS_CLOSE', 'ABOVE_PREMARKET_REFERENCE', 'AT_PREMARKET_HIGH'),
        (_snapshot(observation_price=95), 'BELOW_PREVIOUS_CLOSE', 'BELOW_PREMARKET_REFERENCE', 'AT_PREMARKET_LOW'),
        (
            _snapshot(
                premarket_reference_price=100,
                premarket_high=100,
                premarket_low=100,
                observation_price=100,
            ),
            'AT_PREVIOUS_CLOSE',
            'AT_PREMARKET_REFERENCE',
            'AT_PREMARKET_RANGE',
        ),
    )
    for candidate, previous_relation, reference_relation, range_relation in relation_cases:
        value, _ = _analyze_with_source(candidate)
        actual = (
            value['observation_vs_previous_close'],
            value['observation_vs_premarket_reference'],
            value['observation_vs_premarket_range'],
        )
        expected = (previous_relation, reference_relation, range_relation)
        if actual != expected:
            return f'observation relation mismatch: expected={expected} actual={actual}'

    original = _snapshot()
    before = copy.deepcopy(original)
    first, _ = _analyze_with_source(original)
    second, _ = _analyze_with_source(original)
    if original != before:
        return 'analyzer mutated the input snapshot or frames'
    if first != second:
        return 'same full input did not produce identical output'
    reordered = {key: original[key] for key in reversed(tuple(original))}
    reordered_result, _ = _analyze_with_source(reordered)
    if reordered_result != first:
        return 'snapshot dictionary key order changed output'
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

    actual_head = _git_value('rev-parse', 'HEAD')
    allowed_builds = {('53E2', 'AstraEdge 53E2')}
    if actual_head == COMMITTED_53E2_HEAD:
        allowed_builds.add(('53F', 'AstraEdge 53F'))
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed_builds:
        return _fail(f'build must be exact 53E2 / AstraEdge 53E2, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')

    source_error = _validate_source_contract()
    if source_error:
        return _fail(source_error)
    print('V2_API_REUSE_DEPENDENCY_EFFECT_BOUNDARIES_OK')

    runtime_error = _validate_runtime_contract()
    if runtime_error:
        return _fail(runtime_error)
    print('V3_SCALARS_RELATIONS_STATE_AND_AGGREGATES_OK')

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
        'scripts/test_premarket_structure_53e2.py',
        'PREMARKET_STRUCTURE_53E2_PASS',
        'focused 53E2 tests',
    )
    if focused_error:
        return _fail(focused_error)
    focused_lines = {line.strip() for line in focused_output.splitlines()}
    missing_markers = [marker for marker in REQUIRED_FOCUSED_MARKERS if marker not in focused_lines]
    if missing_markers:
        return _fail(f'focused marker verification failed: missing={missing_markers}')
    print('V5_FOCUSED_T1_T72_OK')

    regressions = (
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
    allowed_final_states = {
        (BASELINE_HEAD, BASELINE_TREE),
        (COMMITTED_53E2_HEAD, COMMITTED_53E2_TREE),
    }
    if (final_head, final_tree) not in allowed_final_states:
        return _fail(f'final HEAD/tree changed: {final_head} / {final_tree}')
    print('V9_FINAL_REPOSITORY_STATE_OK')

    print('PHASE_53E2_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
