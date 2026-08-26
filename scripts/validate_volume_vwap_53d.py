#!/usr/bin/env python3
"""Read-only validator for AstraEdge 53D deterministic volume and VWAP."""

from __future__ import annotations

import ast
import hashlib
import math
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = 'd8419ef6296928fa7ffe6cbaae3916c77435fefa'
CANONICAL_TREE = '8b3008e6db85ead22dda60029775bfd1448a77d1'
COMMITTED_53D_HEAD = 'f500a9413103a3bca7c5aaaeed9062472fa913c4'
COMMITTED_53D_TREE = 'ca5201a4c2283f5fd553119b2de512c6378efe3b'
COMMITTED_53E_HEAD = 'eeaeb222fdc02a29bdda76c03de0f56d85bb3ceb'
COMMITTED_53E_TREE = '6962e5556de1f08a826f1c4eb8b8bb63ece0fd75'
ALLOWED_HEADS = frozenset({CANONICAL_HEAD, COMMITTED_53D_HEAD, COMMITTED_53E_HEAD})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'volume_vwap.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candle_anatomy.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candlestick_patterns.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'price_action_structure.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'key_levels_supply_demand.py',
    PROJECT_ROOT / 'scripts' / 'test_volume_vwap_53d.py',
    PROJECT_ROOT / 'scripts' / 'validate_volume_vwap_53d.py',
    PROJECT_ROOT / 'scripts' / 'test_key_levels_supply_demand_53c.py',
    PROJECT_ROOT / 'scripts' / 'validate_key_levels_supply_demand_53c.py',
    PROJECT_ROOT / 'scripts' / 'test_price_action_structure_53b.py',
    PROJECT_ROOT / 'scripts' / 'validate_price_action_structure_53b.py',
    PROJECT_ROOT / 'scripts' / 'test_candlestick_patterns_53a2.py',
    PROJECT_ROOT / 'scripts' / 'validate_candlestick_patterns_53a2.py',
    PROJECT_ROOT / 'scripts' / 'test_candle_anatomy_53a.py',
    PROJECT_ROOT / 'scripts' / 'validate_candle_anatomy_53a.py',
    PROJECT_ROOT / 'scripts' / 'test_event_age_freshness_52r_d2.py',
    PROJECT_ROOT / 'scripts' / 'validate_event_age_freshness_52r_d2.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'premarket_structure.py',
    PROJECT_ROOT / 'scripts' / 'test_premarket_structure_53e2.py',
    PROJECT_ROOT / 'scripts' / 'validate_premarket_structure_53e2.py',
)

PROTECTED_PRODUCTION = {
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/analysis/price_action_structure.py',
    'backend/analysis/key_levels_supply_demand.py',
    'backend/collectors/live_news_tracker.py',
    'backend/trading/market_freshness_guard.py',
    'backend/trading/opening_session_freshness.py',
    'backend/orchestration/alert_freshness_gate.py',
    'backend/runtime/snapshot_freshness_monitor.py',
}
PROTECTED_PREFIXES = ('backend/news/',)

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/volume_vwap.py',
}

NEW_SOURCE = {
    'backend/analysis/volume_vwap.py',
    'scripts/test_volume_vwap_53d.py',
    'scripts/validate_volume_vwap_53d.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
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

ALLOWED_REPORTS = {
    'phase53d_review.txt',
    'phase53d_diff.txt',
    'phase53e_review.txt',
    'phase53e_diff.txt',
    'phase53e2_review.txt',
    'phase53e2_diff.txt',
}

ALLOWED_SUCCESSOR_53E = {
    'backend/analysis/multi_timeframe.py',
    'scripts/test_multi_timeframe_53e.py',
    'scripts/validate_multi_timeframe_53e.py',
}

SUCCESSOR_53E_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/multi_timeframe.py',
}

SUCCESSOR_53E_COMPATIBILITY = {
    'scripts/test_volume_vwap_53d.py',
    'scripts/validate_volume_vwap_53d.py',
}

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | NEW_SOURCE | ALLOWED_HISTORICAL_REGRESSIONS
SUCCESSOR_53E_CHANGED_SOURCE = (
    {'backend/config/build_info.py'}
    | SUCCESSOR_53E_COMPATIBILITY
    | ALLOWED_HISTORICAL_REGRESSIONS
    | ALLOWED_SUCCESSOR_53E
)

ALLOWED_SUCCESSOR_53E2 = {
    'backend/analysis/premarket_structure.py',
    'scripts/test_premarket_structure_53e2.py',
    'scripts/validate_premarket_structure_53e2.py',
}

SUCCESSOR_53E2_COMPATIBILITY = {
    'scripts/test_multi_timeframe_53e.py',
    'scripts/validate_multi_timeframe_53e.py',
    'scripts/test_volume_vwap_53d.py',
    'scripts/validate_volume_vwap_53d.py',
    *ALLOWED_HISTORICAL_REGRESSIONS,
}

SUCCESSOR_53E2_CHANGED_SOURCE = (
    {'backend/config/build_info.py'}
    | SUCCESSOR_53E2_COMPATIBILITY
    | ALLOWED_SUCCESSOR_53E2
)

SUCCESSOR_53E2_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/premarket_structure.py',
}

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
AI_NEEDLES = ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai')
WRITE_NEEDLES = ('write_text', 'write_bytes', 'atomic_write', 'open(')
EXTERNAL_DEPENDENCY_NEEDLES = (
    'backend.news',
    'backend.collectors',
    'backend.trading',
    'backend.telegram',
    'broker',
    'freshness',
)
SESSION_MAGIC_NEEDLES = (
    '09:15',
    'midnight',
    'zoneinfo',
    'trading_calendar',
    'market_calendar',
    'session_open',
    'reset_vwap',
)
FORBIDDEN_REIMPLEMENTATION = (
    'def analyze_candle(',
    'def _finite_number(',
    'DIRECTION_BULLISH',
    'DOJI_BODY_RATIO_MAX',
    'upper_wick',
    'lower_wick',
)
FORBIDDEN_OUTPUT = frozenset({
    'BUY', 'SELL', 'LONG', 'SHORT', 'ENTRY', 'STOP', 'TARGET',
    'POSITION SIZE', 'TRADE SIGNAL', 'WIN PROBABILITY', 'CONFIDENCE',
    'RECOMMENDATION', 'STRONG BUY', 'STRONG SELL',
})
REQUIRED_TEST_MARKERS = tuple(f'T{index}' for index in range(1, 78)) + (
    'VOLUME_VWAP_53D_PASS',
)


def _fail(message: str) -> int:
    print(f'ASTRAEDGE_PHASE_53D_VOLUME_VWAP_FAIL: {message}', file=sys.stderr)
    return 1


def _file_digest(path: Path) -> str:
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
        detail = (proc.stderr or proc.stdout or 'unknown git error').strip()
        raise RuntimeError(detail)
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
        detail = (proc.stderr or proc.stdout or 'unknown git error').strip()
        raise RuntimeError(detail)
    return (proc.stdout or '').strip()


def _is_relevant_untracked(path: str) -> bool:
    normalized = path.replace('\\', '/')
    lower = normalized.lower()
    name = lower.rsplit('/', 1)[-1]
    return (
        normalized.startswith(('backend/', 'scripts/', 'data/'))
        or lower in {'.env', 'keys.env', 'config/keys.env'}
        or name.endswith('.env')
        or name.startswith('requirements')
        or name in {'railway.json', 'railway.toml', 'procfile', 'nixpacks.toml'}
        or lower.startswith('.railway/')
    )


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


def _validate_changed_file_scope() -> str | None:
    actual_head = _git_value('rev-parse', 'HEAD')
    actual_tree = _git_value('rev-parse', 'HEAD^{tree}')
    if actual_head not in ALLOWED_HEADS:
        return (
            f'HEAD must remain canonical 53D baseline {CANONICAL_HEAD} '
            f'or committed 53D HEAD {COMMITTED_53D_HEAD}, got {actual_head}'
        )
    if actual_head == CANONICAL_HEAD and actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}, got {actual_tree}'
    if actual_head == COMMITTED_53D_HEAD and actual_tree != COMMITTED_53D_TREE:
        return f'committed 53D HEAD tree must remain {COMMITTED_53D_TREE}, got {actual_tree}'
    if actual_head == COMMITTED_53E_HEAD and actual_tree != COMMITTED_53E_TREE:
        return f'committed 53E HEAD tree must remain {COMMITTED_53E_TREE}, got {actual_tree}'

    tracked_changed = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'D53_CHANGED_FILE_SCOPE '
        f'head={actual_head} '
        f'tracked={sorted(tracked_changed)} '
        f'untracked_relevant={sorted(relevant_untracked)} '
        f'reports_untracked={sorted(reports_untracked)}'
    )

    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'53D reports must remain untracked: {sorted(reports_tracked)}'

    staged = _git_paths('diff', '--cached', '--name-only')
    if staged:
        return f'nothing may be staged: {sorted(staged)}'

    data_changes = {
        path for path in (tracked_changed | untracked)
        if path == 'data' or path.startswith('data/')
    }
    if data_changes:
        return f'data/ changes are never allowed: {sorted(data_changes)}'

    protected_hits = {
        path for path in tracked_changed
        if path in PROTECTED_PRODUCTION or path.startswith(PROTECTED_PREFIXES)
    }
    if protected_hits:
        return f'protected production files changed: {sorted(protected_hits)}'

    if actual_head == CANONICAL_HEAD:
        expected_source_scope = ALLOWED_CHANGED_SOURCE
    elif actual_head == COMMITTED_53D_HEAD:
        expected_source_scope = SUCCESSOR_53E_CHANGED_SOURCE
    else:
        expected_source_scope = SUCCESSOR_53E2_CHANGED_SOURCE
    if actual_source_scope != expected_source_scope:
        missing = sorted(expected_source_scope - actual_source_scope)
        unexpected = sorted(actual_source_scope - expected_source_scope)
        return f'changed source scope mismatch: missing={missing} unexpected={unexpected}'

    if actual_head == CANONICAL_HEAD:
        if not NEW_SOURCE <= relevant_untracked:
            return f'53D source files must be new and untracked: {sorted(NEW_SOURCE - relevant_untracked)}'
        if not ALLOWED_HISTORICAL_REGRESSIONS <= tracked_changed:
            return (
                'missing narrow predecessor compatibility changes: '
                f'{sorted(ALLOWED_HISTORICAL_REGRESSIONS - tracked_changed)}'
            )
        expected_production = INTENDED_PRODUCTION
    elif actual_head == COMMITTED_53D_HEAD:
        if not NEW_SOURCE <= tracked_now:
            return f'missing committed 53D source files: {sorted(NEW_SOURCE - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53E <= relevant_untracked:
            return f'missing required 53E successor files: {sorted(ALLOWED_SUCCESSOR_53E - relevant_untracked)}'
        if 'backend/analysis/volume_vwap.py' in tracked_changed:
            return '53D volume_vwap.py must remain unchanged for 53E'
        expected_production = SUCCESSOR_53E_PRODUCTION
    else:
        committed_predecessors = NEW_SOURCE | ALLOWED_SUCCESSOR_53E
        if not committed_predecessors <= tracked_now:
            return f'missing committed predecessor files: {sorted(committed_predecessors - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53E2 <= relevant_untracked:
            return f'missing required 53E2 successor files: {sorted(ALLOWED_SUCCESSOR_53E2 - relevant_untracked)}'
        if 'backend/analysis/volume_vwap.py' in tracked_changed:
            return '53D volume_vwap.py must remain unchanged for 53E2'
        if 'backend/analysis/multi_timeframe.py' in tracked_changed:
            return '53E multi_timeframe.py must remain unchanged for 53E2'
        expected_production = SUCCESSOR_53E2_PRODUCTION

    production_changes = {
        path for path in actual_source_scope
        if path.startswith('backend/')
    }
    if production_changes != expected_production:
        return f'production scope must be exact: {sorted(production_changes)}'

    print('D53_CHANGED_FILE_SCOPE_OK')
    return None


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
    if proc.returncode != 0 or marker not in {line.strip() for line in output.splitlines()}:
        if output:
            print(output, end='' if output.endswith('\n') else '\n', file=sys.stderr)
        if proc.returncode != 0:
            return f'{label} exited {proc.returncode}', output
        return f'{label} missing marker {marker}', output
    return None, output


def main() -> int:
    before = {str(path): _file_digest(path) for path in WATCHED_PATHS}

    try:
        if _git_paths('status', '--short', '--', 'data'):
            return _fail('repository data/ is not clean before validation')
        scope_error = _validate_changed_file_scope()
    except RuntimeError as exc:
        return _fail(f'Git changed-file scope collection failed: {exc}')
    if scope_error:
        return _fail(scope_error)

    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53D', 'AstraEdge 53D'),
        ('53E', 'AstraEdge 53E'),
        ('53E2', 'AstraEdge 53E2'),
    }:
        return _fail(f'build must be exact 53D or successor 53E/53E2 pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    print('V1_BUILD_IDENTITY_OK')

    module_path = PROJECT_ROOT / 'backend' / 'analysis' / 'volume_vwap.py'
    if not module_path.is_file():
        return _fail('missing backend/analysis/volume_vwap.py')
    source = module_path.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'def analyze_volume_vwap(' not in source:
        return _fail('public analyze_volume_vwap API is missing')
    if 'backend.analysis.candle_anatomy' not in imported or 'analyze_candle' not in source:
        return _fail('53D must import and reuse 53A analyze_candle')
    for needle in FORBIDDEN_REIMPLEMENTATION:
        if needle in source:
            return _fail(f'53A candle analysis appears duplicated: {needle}')
    print('V2_PUBLIC_API_AND_53A_REUSE_OK')

    from backend.analysis.volume_vwap import (
        EVENT_TAG_ORDER,
        HIGH_VOLUME_RATIO_MIN,
        LOW_VOLUME_RATIO_MAX,
        MIN_VOLUME_BASELINE_SAMPLES,
        MIN_VOLUME_VWAP_CANDLES,
        OUTPUT_KEYS,
        RECORD_KEYS,
        SCHEMA_VERSION,
        VOLUME_LOOKBACK,
        VWAP_SCOPE,
        analyze_volume_vwap,
    )

    constants = (
        SCHEMA_VERSION,
        MIN_VOLUME_VWAP_CANDLES,
        VOLUME_LOOKBACK,
        MIN_VOLUME_BASELINE_SAMPLES,
        HIGH_VOLUME_RATIO_MIN,
        LOW_VOLUME_RATIO_MAX,
        VWAP_SCOPE,
    )
    expected_constants = ('53D', 1, 20, 3, 1.50, 0.50, 'SUPPLIED_WINDOW')
    if constants != expected_constants:
        return _fail(f'constant contract mismatch: {constants}')
    if EVENT_TAG_ORDER != ('CROSS_ABOVE_VWAP', 'CROSS_BELOW_VWAP'):
        return _fail(f'event-tag order mismatch: {EVENT_TAG_ORDER}')
    expected_output_keys = (
        'schema_version', 'analysis_state', 'candle_count', 'vwap_scope',
        'vwap_anchor_index', 'volume_lookback', 'min_volume_baseline_samples',
        'high_volume_ratio_min', 'low_volume_ratio_max', 'latest_vwap',
        'latest_vwap_relation', 'latest_volume_ratio', 'latest_volume_state',
        'records', 'candle_anatomy',
    )
    expected_record_keys = (
        'index', 'volume', 'baseline_volume', 'baseline_sample_count',
        'volume_ratio', 'volume_state', 'typical_price', 'cumulative_volume',
        'vwap', 'close', 'vwap_relation', 'vwap_distance',
        'vwap_distance_ratio', 'event_tags',
    )
    if OUTPUT_KEYS != expected_output_keys or RECORD_KEYS != expected_record_keys:
        return _fail('closed output or record key contract mismatch')
    print('V3_CONSTANTS_AND_CLOSED_KEYS_OK')

    sample_candles = [
        {'open': 2, 'high': 4, 'low': 1, 'close': 3, 'volume': 2},
        {'open': 6, 'high': 8, 'low': 2, 'close': 7, 'volume': 4},
    ]
    sample = analyze_volume_vwap(sample_candles)
    first_typical = (4.0 + 1.0 + 3.0) / 3.0
    second_typical = (8.0 + 2.0 + 7.0) / 3.0
    expected_vwap = (first_typical * 2.0 + second_typical * 4.0) / 6.0
    if sample['analysis_state'] != 'OK' or sample['vwap_anchor_index'] != 0:
        return _fail(f'basic supplied-window result mismatch: {sample}')
    if sample['records'][0]['typical_price'] != first_typical:
        return _fail('typical-price formula is not exact HLC3')
    if not math.isclose(sample['records'][1]['vwap'], expected_vwap, rel_tol=0.0, abs_tol=0.0):
        return _fail('cumulative supplied-window VWAP formula mismatch')
    if analyze_volume_vwap([])['analysis_state'] != 'INSUFFICIENT_CANDLES':
        return _fail('empty-list cardinality contract mismatch')
    if analyze_volume_vwap({})['analysis_state'] != 'MALFORMED':
        return _fail('non-list failure contract mismatch')
    missing = analyze_volume_vwap([
        {'open': 1, 'high': 2, 'low': 0, 'close': 1},
    ])
    if missing['analysis_state'] != 'MISSING_VOLUME' or missing['records']:
        return _fail('missing-volume failure contract mismatch')
    zero = analyze_volume_vwap([
        {'open': 1, 'high': 2, 'low': 0, 'close': 1, 'volume': 0},
        {'open': 2, 'high': 3, 'low': 1, 'close': 2, 'volume': 5},
    ])
    if zero['records'][0]['vwap'] is not None or zero['records'][1]['vwap'] != 2.0:
        return _fail('zero-volume VWAP behavior mismatch')
    print('V4_HLC3_VOLUME_AND_WINDOW_VWAP_OK')

    for module in NETWORK_MODULES:
        if module in imported:
            return _fail(f'network import found: {module}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(module)}\b', source, re.M):
            return _fail(f'network import line found: {module}')
    lowered = source.lower()
    for needle in AI_NEEDLES:
        if needle in lowered:
            return _fail(f'AI dependency found: {needle}')
    for needle in WRITE_NEEDLES:
        if needle in source:
            return _fail(f'write/file path found: {needle}')
    for needle in EXTERNAL_DEPENDENCY_NEEDLES:
        if needle in lowered:
            return _fail(f'broker/news/freshness dependency found: {needle}')
    for needle in SESSION_MAGIC_NEEDLES:
        if needle in lowered:
            return _fail(f'guessed session-reset dependency found: {needle}')
    emitted = {value.strip().upper() for value in _emitted_strings(sample)}
    forbidden = sorted(FORBIDDEN_OUTPUT & emitted)
    if forbidden:
        return _fail(f'forbidden trade interpretation output: {forbidden}')
    print('V5_NO_EXTERNAL_EFFECTS_OR_SESSION_MAGIC_OK')

    for path in sorted(PROTECTED_PRODUCTION):
        if _git_paths('diff', '--name-only', 'HEAD', '--', path):
            return _fail(f'protected production changed: {path}')
    protected_prefix_hits = {
        path for path in _git_paths('diff', '--name-only', 'HEAD', '--')
        if path.startswith(PROTECTED_PREFIXES)
    }
    if protected_prefix_hits:
        return _fail(f'protected production prefix changed: {sorted(protected_prefix_hits)}')
    print('V6_PROTECTED_PRODUCTION_UNCHANGED_OK')

    focused_error, focused_output = _run_script(
        'scripts/test_volume_vwap_53d.py',
        'VOLUME_VWAP_53D_PASS',
        'focused 53D tests',
    )
    if focused_error:
        return _fail(focused_error)
    output_lines = {line.strip() for line in focused_output.splitlines()}
    missing_markers = [marker for marker in REQUIRED_TEST_MARKERS if marker not in output_lines]
    if missing_markers:
        return _fail(f'focused marker verification failed: missing={missing_markers}')
    print('V7_FOCUSED_53D_OK')

    regressions = (
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
        print(f'V8_{label}_REGRESSION_OK')

    compile_targets = [
        'backend/config/build_info.py',
        'backend/analysis/volume_vwap.py',
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
        'backend/analysis/price_action_structure.py',
        'backend/analysis/key_levels_supply_demand.py',
        'scripts/test_volume_vwap_53d.py',
        'scripts/validate_volume_vwap_53d.py',
        *sorted(ALLOWED_HISTORICAL_REGRESSIONS),
    ]
    compiled = subprocess.run(
        [sys.executable, '-m', 'py_compile', *compile_targets],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return _fail(f'py_compile failed: {compiled.stderr or compiled.stdout}')
    print('V9_PY_COMPILE_OK')

    diff_check = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        return _fail(f'git diff --check failed: {diff_check.stdout or diff_check.stderr}')
    print('V10_DIFF_CHECK_OK')

    after = {str(path): _file_digest(path) for path in WATCHED_PATHS}
    if before != after:
        return _fail('validator mutated watched files')

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
        (CANONICAL_HEAD, CANONICAL_TREE),
        (COMMITTED_53D_HEAD, COMMITTED_53D_TREE),
        (COMMITTED_53E_HEAD, COMMITTED_53E_TREE),
    }
    if (final_head, final_tree) not in allowed_final_states:
        return _fail(f'final HEAD/tree changed: {final_head} / {final_tree}')

    print('PHASE_53D_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
