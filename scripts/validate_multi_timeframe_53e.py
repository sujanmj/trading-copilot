#!/usr/bin/env python3
"""Read-only validator for AstraEdge 53E deterministic multi-timeframe analysis."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = 'f500a9413103a3bca7c5aaaeed9062472fa913c4'
CANONICAL_TREE = 'ca5201a4c2283f5fd553119b2de512c6378efe3b'
COMMITTED_53E_HEAD = 'eeaeb222fdc02a29bdda76c03de0f56d85bb3ceb'
COMMITTED_53E_TREE = '6962e5556de1f08a826f1c4eb8b8bb63ece0fd75'
COMMITTED_53E2_HEAD = 'e43be3ca8b3c2036fb8a7a85078c9e6911289f25'
COMMITTED_53E2_TREE = '66ec9e271d3851f78d593a11fa542d30cccdbcbe'
ALLOWED_HEADS = frozenset({CANONICAL_HEAD, COMMITTED_53E_HEAD, COMMITTED_53E2_HEAD})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'multi_timeframe.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'volume_vwap.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'key_levels_supply_demand.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'price_action_structure.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candlestick_patterns.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candle_anatomy.py',
    PROJECT_ROOT / 'scripts' / 'test_multi_timeframe_53e.py',
    PROJECT_ROOT / 'scripts' / 'validate_multi_timeframe_53e.py',
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
    'backend/analysis/volume_vwap.py',
}
PROTECTED_PREFIXES = (
    'backend/news/',
    'backend/collectors/',
    'backend/trading/',
    'backend/orchestration/',
    'backend/runtime/',
    'backend/telegram/',
)

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/multi_timeframe.py',
}

NEW_SOURCE = {
    'backend/analysis/multi_timeframe.py',
    'scripts/test_multi_timeframe_53e.py',
    'scripts/validate_multi_timeframe_53e.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
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

ALLOWED_REPORTS = {
    'phase53e_review.txt',
    'phase53e_diff.txt',
    'phase53e2_review.txt',
    'phase53e2_diff.txt',
    'phase53f_review.txt',
    'phase53f_diff.txt',
}
ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | NEW_SOURCE | ALLOWED_HISTORICAL_REGRESSIONS

ALLOWED_SUCCESSOR_53E2 = {
    'backend/analysis/premarket_structure.py',
    'scripts/test_premarket_structure_53e2.py',
    'scripts/validate_premarket_structure_53e2.py',
}

SUCCESSOR_53E2_COMPATIBILITY = {
    'scripts/test_multi_timeframe_53e.py',
    'scripts/validate_multi_timeframe_53e.py',
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

ALLOWED_SUCCESSOR_53F = {
    'backend/analysis/historical_setup_evidence.py',
    'scripts/test_historical_setup_evidence_53f.py',
    'scripts/validate_historical_setup_evidence_53f.py',
}

SUCCESSOR_53F_COMPATIBILITY = {
    'scripts/test_premarket_structure_53e2.py',
    'scripts/validate_premarket_structure_53e2.py',
    *SUCCESSOR_53E2_COMPATIBILITY,
}

SUCCESSOR_53F_CHANGED_SOURCE = (
    {'backend/config/build_info.py'}
    | SUCCESSOR_53F_COMPATIBILITY
    | ALLOWED_SUCCESSOR_53F
)

SUCCESSOR_53F_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/historical_setup_evidence.py',
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
    'telegram',
)
TIME_MAGIC_NEEDLES = (
    'resample',
    'aggregate_candles',
    'fill_missing',
    'timedelta',
    'datetime',
    'zoneinfo',
    'trading_calendar',
    'market_calendar',
    '09:15',
    'midnight',
    'strptime',
    'parse_timeframe',
    'timeframe_minutes',
)
FORBIDDEN_REIMPLEMENTATION = (
    'analyze_candle',
    'analyze_price_action_structure',
    'SWING_SPAN',
    'def _confirmed_swings',
    'def _break_events',
    'LEVEL_CLUSTER_TOLERANCE_RATIO',
    'def _level_groups',
    'HIGH_VOLUME_RATIO_MIN',
    'LOW_VOLUME_RATIO_MAX',
    'def _vwap_relation',
    'def _cross_tags',
)
FORBIDDEN_OUTPUT = frozenset({
    'BUY', 'SELL', 'LONG', 'SHORT', 'ENTRY', 'STOP', 'TARGET',
    'POSITION SIZE', 'TRADE SIGNAL', 'WIN PROBABILITY', 'CONFIDENCE',
    'RECOMMENDATION', 'STRONG BUY', 'STRONG SELL',
})
REQUIRED_TEST_MARKERS = tuple(f'T{index}' for index in range(1, 73)) + (
    'MULTI_TIMEFRAME_53E_PASS',
)


def _fail(message: str) -> int:
    print(f'ASTRAEDGE_PHASE_53E_MULTI_TIMEFRAME_FAIL: {message}', file=sys.stderr)
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
            f'HEAD must remain canonical 53E predecessor {CANONICAL_HEAD} '
            f'or committed 53E HEAD {COMMITTED_53E_HEAD}, got {actual_head}'
        )
    if actual_head == CANONICAL_HEAD and actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}, got {actual_tree}'
    if actual_head == COMMITTED_53E_HEAD and actual_tree != COMMITTED_53E_TREE:
        return f'committed 53E HEAD tree must remain {COMMITTED_53E_TREE}, got {actual_tree}'
    if actual_head == COMMITTED_53E2_HEAD and actual_tree != COMMITTED_53E2_TREE:
        return f'committed 53E2 HEAD tree must remain {COMMITTED_53E2_TREE}, got {actual_tree}'

    tracked_changed = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'E53_CHANGED_FILE_SCOPE '
        f'head={actual_head} '
        f'tracked={sorted(tracked_changed)} '
        f'untracked_relevant={sorted(relevant_untracked)} '
        f'reports_untracked={sorted(reports_untracked)}'
    )

    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'53E reports must remain untracked: {sorted(reports_tracked)}'

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
    elif actual_head == COMMITTED_53E_HEAD:
        expected_source_scope = SUCCESSOR_53E2_CHANGED_SOURCE
    else:
        expected_source_scope = SUCCESSOR_53F_CHANGED_SOURCE
    if actual_source_scope != expected_source_scope:
        missing = sorted(expected_source_scope - actual_source_scope)
        unexpected = sorted(actual_source_scope - expected_source_scope)
        return f'changed source scope mismatch: missing={missing} unexpected={unexpected}'

    if actual_head == CANONICAL_HEAD:
        if not NEW_SOURCE <= relevant_untracked:
            return f'53E source files must be new and untracked: {sorted(NEW_SOURCE - relevant_untracked)}'
        if not ALLOWED_HISTORICAL_REGRESSIONS <= tracked_changed:
            return (
                'missing narrow predecessor compatibility changes: '
                f'{sorted(ALLOWED_HISTORICAL_REGRESSIONS - tracked_changed)}'
            )
        expected_production = INTENDED_PRODUCTION
    elif actual_head == COMMITTED_53E_HEAD:
        if not NEW_SOURCE <= tracked_now:
            return f'missing committed 53E source files: {sorted(NEW_SOURCE - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53E2 <= relevant_untracked:
            return f'missing required 53E2 successor files: {sorted(ALLOWED_SUCCESSOR_53E2 - relevant_untracked)}'
        if 'backend/analysis/multi_timeframe.py' in tracked_changed:
            return '53E multi_timeframe.py must remain unchanged for 53E2'
        expected_production = SUCCESSOR_53E2_PRODUCTION
    else:
        committed_predecessors = NEW_SOURCE | ALLOWED_SUCCESSOR_53E2
        if not committed_predecessors <= tracked_now:
            return f'missing committed predecessor files: {sorted(committed_predecessors - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53F <= relevant_untracked:
            return f'missing required 53F successor files: {sorted(ALLOWED_SUCCESSOR_53F - relevant_untracked)}'
        if 'backend/analysis/multi_timeframe.py' in tracked_changed:
            return '53E multi_timeframe.py must remain unchanged for 53F'
        if 'backend/analysis/premarket_structure.py' in tracked_changed:
            return '53E2 premarket_structure.py must remain unchanged for 53F'
        expected_production = SUCCESSOR_53F_PRODUCTION

    production_changes = {
        path for path in actual_source_scope
        if path.startswith('backend/')
    }
    if production_changes != expected_production:
        return f'production scope must be exact: {sorted(production_changes)}'

    print('E53_CHANGED_FILE_SCOPE_OK')
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


def _key_source(bias: str) -> dict:
    return {
        'level_state': 'OK',
        'structure_bias': bias,
        'key_levels': [{'level_id': 'LEVEL:1'}],
        'level_groups': [],
        'zones': [{'zone_state': 'ACTIVE'}],
        'source_structure': {
            'structure_state': 'OK',
            'swing_points': [{'swing_id': 'SWING:1'}],
            'break_events': [],
            'candle_anatomy': [],
        },
    }


def _volume_source(relation: str, state: str) -> dict:
    return {
        'analysis_state': 'OK',
        'latest_vwap': 100.0,
        'latest_vwap_relation': relation,
        'latest_volume_ratio': 1.5,
        'latest_volume_state': state,
        'records': [],
        'candle_anatomy': [],
    }


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
        ('53E', 'AstraEdge 53E'),
        ('53E2', 'AstraEdge 53E2'),
        ('53F', 'AstraEdge 53F'),
    }:
        return _fail(f'build must be exact 53E or successor 53E2/53F pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    print('V1_BUILD_IDENTITY_OK')

    module_path = PROJECT_ROOT / 'backend' / 'analysis' / 'multi_timeframe.py'
    if not module_path.is_file():
        return _fail('missing backend/analysis/multi_timeframe.py')
    source = module_path.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'def analyze_multi_timeframe(' not in source:
        return _fail('public analyze_multi_timeframe API is missing')
    if 'backend.analysis.key_levels_supply_demand' not in imported or 'analyze_key_levels' not in source:
        return _fail('53E must import and reuse 53C analyze_key_levels')
    if 'backend.analysis.volume_vwap' not in imported or 'analyze_volume_vwap' not in source:
        return _fail('53E must import and reuse 53D analyze_volume_vwap')
    if 'backend.analysis.price_action_structure' in imported or 'backend.analysis.candle_anatomy' in imported:
        return _fail('53E must not import 53B or 53A directly')
    for needle in FORBIDDEN_REIMPLEMENTATION:
        if needle in source:
            return _fail(f'predecessor analytical logic appears duplicated: {needle}')
    print('V2_PUBLIC_API_AND_PREDECESSOR_REUSE_OK')

    from backend.analysis.multi_timeframe import (
        ALIGNMENT_SCOPE,
        FRAME_KEYS,
        MIN_ALIGNMENT_FRAMES,
        MIN_TIMEFRAMES,
        OUTPUT_KEYS,
        SCHEMA_VERSION,
        VOLUME_STATE_VALUES,
        analyze_multi_timeframe,
    )

    constants = (SCHEMA_VERSION, MIN_TIMEFRAMES, MIN_ALIGNMENT_FRAMES, ALIGNMENT_SCOPE)
    if constants != ('53E', 2, 2, 'CALLER_SUPPLIED_WINDOWS'):
        return _fail(f'constant contract mismatch: {constants}')
    expected_output_keys = (
        'schema_version', 'analysis_state', 'timeframe_count', 'alignment_scope',
        'min_timeframes', 'min_alignment_frames', 'structure_alignment',
        'structure_alignment_frame_count', 'vwap_alignment',
        'vwap_alignment_frame_count', 'volume_state_counts', 'frames',
    )
    expected_frame_keys = (
        'timeframe', 'candle_count', 'frame_state', 'structure_state',
        'structure_bias', 'confirmed_swing_count', 'break_event_count',
        'key_level_count', 'level_group_count', 'active_zone_count',
        'invalidated_zone_count', 'volume_vwap_state', 'latest_vwap',
        'latest_vwap_relation', 'latest_volume_ratio', 'latest_volume_state',
        'source_key_levels', 'source_volume_vwap',
    )
    if OUTPUT_KEYS != expected_output_keys or FRAME_KEYS != expected_frame_keys:
        return _fail('closed top-level or frame key contract mismatch')
    if VOLUME_STATE_VALUES != ('HIGH_VOLUME', 'NORMAL_VOLUME', 'LOW_VOLUME', 'UNDEFINED'):
        return _fail(f'volume-state count key order mismatch: {VOLUME_STATE_VALUES}')
    print('V3_CONSTANTS_AND_CLOSED_KEYS_OK')

    import backend.analysis.multi_timeframe as module

    frames = [
        {'timeframe': 'second supplied', 'candles': [{'opaque': 1}]},
        {'timeframe': 'first supplied', 'candles': [{'opaque': 2}]},
    ]
    key_results = [_key_source('BULLISH'), _key_source('BULLISH')]
    volume_results = [
        _volume_source('ABOVE_VWAP', 'HIGH_VOLUME'),
        _volume_source('ABOVE_VWAP', 'NORMAL_VOLUME'),
    ]
    with (
        patch.object(module, 'analyze_key_levels', side_effect=key_results) as key_analyzer,
        patch.object(module, 'analyze_volume_vwap', side_effect=volume_results) as volume_analyzer,
    ):
        sample = module.analyze_multi_timeframe(frames)
    if key_analyzer.call_count != 2 or volume_analyzer.call_count != 2:
        return _fail('53C/53D must each be called exactly once per supplied frame')
    if [row['timeframe'] for row in sample['frames']] != ['second supplied', 'first supplied']:
        return _fail('caller-supplied frame order was not preserved')
    if sample['frames'][0]['source_key_levels'] is not key_results[0]:
        return _fail('source_key_levels is not the exact 53C result')
    if sample['frames'][0]['source_volume_vwap'] is not volume_results[0]:
        return _fail('source_volume_vwap is not the exact 53D result')
    if sample['structure_alignment'] != 'ALIGNED_BULLISH':
        return _fail(f'structure alignment mismatch: {sample}')
    if sample['vwap_alignment'] != 'ALIGNED_ABOVE_VWAP':
        return _fail(f'VWAP alignment mismatch: {sample}')
    expected_counts = {
        'HIGH_VOLUME': 1,
        'NORMAL_VOLUME': 1,
        'LOW_VOLUME': 0,
        'UNDEFINED': 0,
    }
    if sample['volume_state_counts'] != expected_counts:
        return _fail(f'volume-state counts mismatch: {sample["volume_state_counts"]}')
    if tuple(sample.keys()) != OUTPUT_KEYS or any(tuple(row.keys()) != FRAME_KEYS for row in sample['frames']):
        return _fail('runtime output is not closed')
    if analyze_multi_timeframe([])['analysis_state'] != 'INSUFFICIENT_TIMEFRAMES':
        return _fail('empty-list cardinality contract mismatch')
    if analyze_multi_timeframe({})['analysis_state'] != 'MALFORMED':
        return _fail('non-list failure contract mismatch')
    malformed = analyze_multi_timeframe([
        {'timeframe': 'duplicate', 'candles': []},
        {'timeframe': ' duplicate ', 'candles': []},
    ])
    if malformed['analysis_state'] != 'MALFORMED' or malformed['frames']:
        return _fail('malformed outer-envelope contract mismatch')
    print('V4_RUNTIME_ORCHESTRATION_AND_ALIGNMENT_OK')

    for module_name in NETWORK_MODULES:
        if module_name in imported:
            return _fail(f'network import found: {module_name}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(module_name)}\b', source, re.M):
            return _fail(f'network import line found: {module_name}')
    lowered = source.lower()
    for needle in AI_NEEDLES:
        if needle in lowered:
            return _fail(f'AI dependency found: {needle}')
    for needle in WRITE_NEEDLES:
        if needle in source:
            return _fail(f'write/file path found: {needle}')
    for needle in EXTERNAL_DEPENDENCY_NEEDLES:
        if needle in lowered:
            return _fail(f'broker/news/freshness/Telegram dependency found: {needle}')
    for needle in TIME_MAGIC_NEEDLES:
        if needle in lowered:
            return _fail(f'resampling/session/timeframe parsing logic found: {needle}')
    if re.search(r"['\"](?:1m|5m|15m|1h|1d)['\"]", source, re.I):
        return _fail('hard-coded timeframe hierarchy found')
    emitted = {value.strip().upper() for value in _emitted_strings(sample)}
    forbidden = sorted(FORBIDDEN_OUTPUT & emitted)
    if forbidden:
        return _fail(f'forbidden trade interpretation output: {forbidden}')
    print('V5_NO_EFFECTS_TIME_MAGIC_OR_TRADE_INTERPRETATION_OK')

    for path in sorted(PROTECTED_PRODUCTION):
        if _git_paths('diff', '--name-only', 'HEAD', '--', path):
            return _fail(f'protected predecessor production changed: {path}')
    protected_prefix_hits = {
        path for path in _git_paths('diff', '--name-only', 'HEAD', '--')
        if path.startswith(PROTECTED_PREFIXES)
    }
    if protected_prefix_hits:
        return _fail(f'protected production prefix changed: {sorted(protected_prefix_hits)}')
    print('V6_PROTECTED_PRODUCTION_UNCHANGED_OK')

    focused_error, focused_output = _run_script(
        'scripts/test_multi_timeframe_53e.py',
        'MULTI_TIMEFRAME_53E_PASS',
        'focused 53E tests',
    )
    if focused_error:
        return _fail(focused_error)
    output_lines = {line.strip() for line in focused_output.splitlines()}
    missing_markers = [marker for marker in REQUIRED_TEST_MARKERS if marker not in output_lines]
    if missing_markers:
        return _fail(f'focused marker verification failed: missing={missing_markers}')
    print('V7_FOCUSED_53E_OK')

    regressions = (
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
        print(f'V8_{label}_REGRESSION_OK')

    compile_targets = [
        'backend/config/build_info.py',
        'backend/analysis/multi_timeframe.py',
        'backend/analysis/volume_vwap.py',
        'backend/analysis/key_levels_supply_demand.py',
        'backend/analysis/price_action_structure.py',
        'backend/analysis/candlestick_patterns.py',
        'backend/analysis/candle_anatomy.py',
        'scripts/test_multi_timeframe_53e.py',
        'scripts/validate_multi_timeframe_53e.py',
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
        (COMMITTED_53E_HEAD, COMMITTED_53E_TREE),
        (COMMITTED_53E2_HEAD, COMMITTED_53E2_TREE),
    }
    if (final_head, final_tree) not in allowed_final_states:
        return _fail(f'final HEAD/tree changed: {final_head} / {final_tree}')

    print('PHASE_53E_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
