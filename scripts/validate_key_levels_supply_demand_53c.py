#!/usr/bin/env python3
"""Read-only validator for AstraEdge 53C deterministic levels and zones."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = '7df88790ad9ada1a81b0f5613caafb05a0c217d5'
CANONICAL_TREE = '91f784a344655723cbc5f322703029f67aa0f544'
COMMITTED_53C_HEAD = 'd8419ef6296928fa7ffe6cbaae3916c77435fefa'
COMMITTED_53C_TREE = '8b3008e6db85ead22dda60029775bfd1448a77d1'
COMMITTED_53D_HEAD = 'f500a9413103a3bca7c5aaaeed9062472fa913c4'
COMMITTED_53D_TREE = 'ca5201a4c2283f5fd553119b2de512c6378efe3b'
COMMITTED_53E_HEAD = 'eeaeb222fdc02a29bdda76c03de0f56d85bb3ceb'
COMMITTED_53E_TREE = '6962e5556de1f08a826f1c4eb8b8bb63ece0fd75'
COMMITTED_53E2_HEAD = 'e43be3ca8b3c2036fb8a7a85078c9e6911289f25'
COMMITTED_53E2_TREE = '66ec9e271d3851f78d593a11fa542d30cccdbcbe'
ALLOWED_HEADS = frozenset({
    CANONICAL_HEAD,
    COMMITTED_53C_HEAD,
    COMMITTED_53D_HEAD,
    COMMITTED_53E_HEAD,
    COMMITTED_53E2_HEAD,
})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'key_levels_supply_demand.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'price_action_structure.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candle_anatomy.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candlestick_patterns.py',
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
    'backend/analysis/price_action_structure.py',
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/collectors/live_news_tracker.py',
    'backend/trading/market_freshness_guard.py',
    'backend/trading/opening_session_freshness.py',
    'backend/orchestration/alert_freshness_gate.py',
    'backend/runtime/snapshot_freshness_monitor.py',
}

PROTECTED_PREFIXES = ('backend/news/',)

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/key_levels_supply_demand.py',
}

NEW_SOURCE = {
    'backend/analysis/key_levels_supply_demand.py',
    'scripts/test_key_levels_supply_demand_53c.py',
    'scripts/validate_key_levels_supply_demand_53c.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
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
    'phase53c_review.txt',
    'phase53c_diff.txt',
    'phase53d_review.txt',
    'phase53d_diff.txt',
    'phase53e_review.txt',
    'phase53e_diff.txt',
    'phase53e2_review.txt',
    'phase53e2_diff.txt',
    'phase53f_review.txt',
    'phase53f_diff.txt',
}

ALLOWED_SUCCESSOR_53D = {
    'backend/analysis/volume_vwap.py',
    'scripts/test_volume_vwap_53d.py',
    'scripts/validate_volume_vwap_53d.py',
}

SUCCESSOR_53D_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/volume_vwap.py',
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
    'scripts/test_key_levels_supply_demand_53c.py',
    'scripts/validate_key_levels_supply_demand_53c.py',
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

ALLOWED_CHANGED_SOURCE = (
    INTENDED_PRODUCTION
    | NEW_SOURCE
    | ALLOWED_HISTORICAL_REGRESSIONS
    | ALLOWED_SUCCESSOR_53D
    | ALLOWED_SUCCESSOR_53E
)

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
FORBIDDEN_REIMPLEMENTATION = (
    'SWING_SPAN',
    'def _confirmed_swings',
    'def _high_relation',
    'def _low_relation',
    'def _break_events',
    'previous_close',
    'analyze_candle',
    'from backend.analysis.candle_anatomy',
)
FORBIDDEN_OUTPUT = frozenset({
    'buy', 'sell', 'long', 'short', 'entry', 'stop', 'target',
    'position size', 'position_size', 'trade signal', 'trade_signal',
    'win probability', 'win_probability', 'confidence', 'recommendation',
    'strong buy', 'strong sell',
})
REQUIRED_TEST_MARKERS = tuple(f'T{index}' for index in range(1, 78)) + (
    'KEY_LEVELS_SUPPLY_DEMAND_53C_PASS',
)


def _fail(message: str) -> int:
    print(f'ASTRAEDGE_PHASE_53C_KEY_LEVELS_FAIL: {message}', file=sys.stderr)
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
        strings = [str(key) for key in value]
        for item in value.values():
            strings.extend(_emitted_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_emitted_strings(item))
        return strings
    return [value] if isinstance(value, str) else []


def _validate_changed_file_scope() -> str | None:
    head = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    tree = subprocess.run(
        ['git', 'rev-parse', 'HEAD^{tree}'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    actual_head = (head.stdout or '').strip()
    actual_tree = (tree.stdout or '').strip()
    if actual_head not in ALLOWED_HEADS:
        return (
            f'HEAD must remain canonical 53C baseline {CANONICAL_HEAD} '
            f'or committed 53C HEAD {COMMITTED_53C_HEAD}, got {actual_head}'
        )
    if actual_head == CANONICAL_HEAD and actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}, got {actual_tree}'
    if actual_head == COMMITTED_53C_HEAD and actual_tree != COMMITTED_53C_TREE:
        return f'committed 53C HEAD tree must remain {COMMITTED_53C_TREE}, got {actual_tree}'
    if actual_head == COMMITTED_53D_HEAD and actual_tree != COMMITTED_53D_TREE:
        return f'committed 53D HEAD tree must remain {COMMITTED_53D_TREE}, got {actual_tree}'
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
        'C53_CHANGED_FILE_SCOPE '
        f'head={actual_head} '
        f'tracked={sorted(tracked_changed)} '
        f'untracked_relevant={sorted(relevant_untracked)} '
        f'reports_untracked={sorted(reports_untracked)}'
    )

    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'53C reports must remain untracked: {sorted(reports_tracked)}'

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

    if actual_head == COMMITTED_53E_HEAD:
        if actual_source_scope != SUCCESSOR_53E2_CHANGED_SOURCE:
            missing = sorted(SUCCESSOR_53E2_CHANGED_SOURCE - actual_source_scope)
            unexpected = sorted(actual_source_scope - SUCCESSOR_53E2_CHANGED_SOURCE)
            return f'53E2 changed source scope mismatch: missing={missing} unexpected={unexpected}'
    elif actual_head == COMMITTED_53E2_HEAD:
        if actual_source_scope != SUCCESSOR_53F_CHANGED_SOURCE:
            missing = sorted(SUCCESSOR_53F_CHANGED_SOURCE - actual_source_scope)
            unexpected = sorted(actual_source_scope - SUCCESSOR_53F_CHANGED_SOURCE)
            return f'53F changed source scope mismatch: missing={missing} unexpected={unexpected}'
    else:
        unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
        if unexpected:
            return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    if 'backend/config/build_info.py' not in tracked_changed:
        return 'backend/config/build_info.py must change for the active build bump'
    if actual_head == CANONICAL_HEAD:
        for path in NEW_SOURCE:
            if path not in relevant_untracked and path not in tracked_changed:
                return f'missing required 53C file: {path}'
        expected_production = INTENDED_PRODUCTION
    elif actual_head == COMMITTED_53C_HEAD:
        for path in NEW_SOURCE:
            if path not in tracked_now:
                return f'missing committed 53C file: {path}'
        for path in ALLOWED_SUCCESSOR_53D:
            if path not in relevant_untracked and path not in tracked_changed:
                return f'missing required 53D successor file: {path}'
        if 'backend/analysis/key_levels_supply_demand.py' in tracked_changed:
            return '53C key_levels_supply_demand.py must remain unchanged for 53D'
        expected_production = SUCCESSOR_53D_PRODUCTION
    elif actual_head == COMMITTED_53D_HEAD:
        for path in NEW_SOURCE | ALLOWED_SUCCESSOR_53D:
            if path not in tracked_now:
                return f'missing committed predecessor file: {path}'
        for path in ALLOWED_SUCCESSOR_53E:
            if path not in relevant_untracked and path not in tracked_changed:
                return f'missing required 53E successor file: {path}'
        if 'backend/analysis/key_levels_supply_demand.py' in tracked_changed:
            return '53C key_levels_supply_demand.py must remain unchanged for 53E'
        if 'backend/analysis/volume_vwap.py' in tracked_changed:
            return '53D volume_vwap.py must remain unchanged for 53E'
        expected_production = SUCCESSOR_53E_PRODUCTION
    elif actual_head == COMMITTED_53E_HEAD:
        committed_predecessors = NEW_SOURCE | ALLOWED_SUCCESSOR_53D | ALLOWED_SUCCESSOR_53E
        if not committed_predecessors <= tracked_now:
            return f'missing committed predecessor files: {sorted(committed_predecessors - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53E2 <= relevant_untracked:
            return f'missing required 53E2 successor files: {sorted(ALLOWED_SUCCESSOR_53E2 - relevant_untracked)}'
        for path in (
            'backend/analysis/key_levels_supply_demand.py',
            'backend/analysis/volume_vwap.py',
            'backend/analysis/multi_timeframe.py',
        ):
            if path in tracked_changed:
                return f'predecessor production must remain unchanged for 53E2: {path}'
        expected_production = SUCCESSOR_53E2_PRODUCTION
    else:
        committed_predecessors = NEW_SOURCE | ALLOWED_SUCCESSOR_53D | ALLOWED_SUCCESSOR_53E | ALLOWED_SUCCESSOR_53E2
        if not committed_predecessors <= tracked_now:
            return f'missing committed predecessor files: {sorted(committed_predecessors - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53F <= relevant_untracked:
            return f'missing required 53F successor files: {sorted(ALLOWED_SUCCESSOR_53F - relevant_untracked)}'
        for path in (
            'backend/analysis/key_levels_supply_demand.py',
            'backend/analysis/volume_vwap.py',
            'backend/analysis/multi_timeframe.py',
            'backend/analysis/premarket_structure.py',
        ):
            if path in tracked_changed:
                return f'predecessor production must remain unchanged for 53F: {path}'
        expected_production = SUCCESSOR_53F_PRODUCTION

    production_changes = {
        path for path in actual_source_scope
        if path.startswith('backend/')
    }
    if production_changes != expected_production:
        return f'production scope must be exact: {sorted(production_changes)}'

    print('C53_CHANGED_FILE_SCOPE_OK')
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
    if proc.stdout:
        print(proc.stdout, end='' if proc.stdout.endswith('\n') else '\n')
    if proc.stderr:
        print(proc.stderr, end='' if proc.stderr.endswith('\n') else '\n', file=sys.stderr)
    if proc.returncode != 0:
        return f'{label} exited {proc.returncode}', output
    if marker not in {line.strip() for line in output.splitlines()}:
        return f'{label} missing marker {marker}', output
    return None, output


def main() -> int:
    before = {str(path): _file_digest(path) for path in WATCHED_PATHS}

    data_before = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if (data_before.stdout or '').strip():
        return _fail('repository data/ is not clean before validation')

    try:
        scope_error = _validate_changed_file_scope()
    except RuntimeError as exc:
        return _fail(f'Git changed-file scope collection failed: {exc}')
    if scope_error:
        return _fail(scope_error)

    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('53C', 'AstraEdge 53C'),
        ('53D', 'AstraEdge 53D'),
        ('53E', 'AstraEdge 53E'),
        ('53E2', 'AstraEdge 53E2'),
        ('53F', 'AstraEdge 53F'),
    }:
        return _fail(f'build must be exact 53C or successor 53D/53E/53E2/53F pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    print('V1_BUILD_IDENTITY_OK')

    module_path = PROJECT_ROOT / 'backend' / 'analysis' / 'key_levels_supply_demand.py'
    if not module_path.is_file():
        return _fail('missing backend/analysis/key_levels_supply_demand.py')
    source = module_path.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'def analyze_key_levels(' not in source:
        return _fail('public analyze_key_levels API is missing')
    if 'backend.analysis.price_action_structure' not in imported:
        return _fail('53C must import the 53B price-action structure module')
    if 'analyze_price_action_structure' not in source:
        return _fail('53C must reuse analyze_price_action_structure')
    if 'def analyze_price_action_structure(' in source:
        return _fail('53C must not reimplement the 53B analyzer')
    for needle in FORBIDDEN_REIMPLEMENTATION:
        if needle in source:
            return _fail(f'53B swing/break/anatomy logic appears duplicated: {needle}')
    print('V2_PUBLIC_API_AND_53B_REUSE_OK')

    from backend.analysis.key_levels_supply_demand import (
        KEY_LEVEL_KEYS,
        LEVEL_CLUSTER_TOLERANCE_RATIO,
        LEVEL_GROUP_KEYS,
        MIN_LEVEL_CANDLES,
        MIN_LEVEL_GROUP_MEMBERS,
        OUTPUT_KEYS,
        ZONE_KEYS,
        analyze_key_levels,
    )

    if MIN_LEVEL_CANDLES != 5:
        return _fail(f'MIN_LEVEL_CANDLES must be 5, got {MIN_LEVEL_CANDLES}')
    if LEVEL_CLUSTER_TOLERANCE_RATIO != 0.0025:
        return _fail(f'LEVEL_CLUSTER_TOLERANCE_RATIO must be 0.0025, got {LEVEL_CLUSTER_TOLERANCE_RATIO}')
    if MIN_LEVEL_GROUP_MEMBERS != 2:
        return _fail(f'MIN_LEVEL_GROUP_MEMBERS must be 2, got {MIN_LEVEL_GROUP_MEMBERS}')
    required_literals = (
        'OK', 'INSUFFICIENT_CANDLES', 'MALFORMED',
        'SWING_HIGH_LEVEL', 'SWING_LOW_LEVEL',
        'UNBROKEN', 'BROKEN_ABOVE', 'BROKEN_BELOW',
        'SUPPLY_LIKE', 'DEMAND_LIKE', 'ACTIVE', 'INVALIDATED',
    )
    for literal in required_literals:
        if literal not in source:
            return _fail(f'missing required level/group/zone state: {literal}')
    expected_output_keys = (
        'schema_version', 'level_state', 'candle_count', 'cluster_tolerance_ratio',
        'structure_bias', 'key_levels', 'level_groups', 'zones', 'source_structure',
    )
    if OUTPUT_KEYS != expected_output_keys:
        return _fail(f'top-level output keys mismatch: {OUTPUT_KEYS}')
    if len(KEY_LEVEL_KEYS) != 10 or len(LEVEL_GROUP_KEYS) != 9 or len(ZONE_KEYS) != 11:
        return _fail('closed record key counts do not match the 53C contract')
    print('V3_CONSTANTS_STATES_AND_CLOSED_KEYS_OK')

    for module in NETWORK_MODULES:
        if module in imported:
            return _fail(f'network import found: {module}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(module)}\b', source, re.M):
            return _fail(f'network import line found: {module}')
    for needle in AI_NEEDLES:
        if needle in source.lower():
            return _fail(f'AI dependency found: {needle}')
    for needle in WRITE_NEEDLES:
        if needle in source:
            return _fail(f'write/file path found: {needle}')
    for needle in EXTERNAL_DEPENDENCY_NEEDLES:
        if needle in source.lower():
            return _fail(f'broker/news/freshness dependency found: {needle}')
    print('V4_NO_EXTERNAL_EFFECTS_OK')

    sample = analyze_key_levels([
        {'open': 5, 'high': 6, 'low': 4, 'close': 5},
        {'open': 6, 'high': 8, 'low': 5, 'close': 6},
        {'open': 7, 'high': 10, 'low': 6, 'close': 7},
        {'open': 6, 'high': 8, 'low': 5, 'close': 6},
        {'open': 5, 'high': 7, 'low': 4, 'close': 5},
    ])
    emitted = {value.strip().lower() for value in _emitted_strings(sample)}
    forbidden = sorted(FORBIDDEN_OUTPUT & emitted)
    if forbidden:
        return _fail(f'forbidden trade interpretation output: {forbidden}')
    if sample['schema_version'] != '53C' or sample['level_state'] != 'OK':
        return _fail(f'basic analyzer result mismatch: {sample}')
    print('V5_DESCRIPTIVE_OUTPUT_ONLY_OK')

    for path in sorted(PROTECTED_PRODUCTION):
        changed = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (changed.stdout or '').strip():
            return _fail(f'protected production changed: {path}')
    protected_prefix_hits = {
        path for path in _git_paths('diff', '--name-only', 'HEAD', '--')
        if path.startswith(PROTECTED_PREFIXES)
    }
    if protected_prefix_hits:
        return _fail(f'protected production prefix changed: {sorted(protected_prefix_hits)}')
    print('V6_PROTECTED_PRODUCTION_UNCHANGED_OK')

    focused_error, focused_output = _run_script(
        'scripts/test_key_levels_supply_demand_53c.py',
        'KEY_LEVELS_SUPPLY_DEMAND_53C_PASS',
        'focused 53C tests',
    )
    if focused_error:
        return _fail(focused_error)
    output_lines = {line.strip() for line in focused_output.splitlines()}
    missing = [marker for marker in REQUIRED_TEST_MARKERS if marker not in output_lines]
    if missing:
        return _fail(f'focused marker verification failed: missing={missing}')
    print('V7_FOCUSED_53C_OK')

    regressions = (
        ('scripts/validate_price_action_structure_53b.py', 'PHASE_53B_VALIDATION_PASS', '53B regression'),
        ('scripts/validate_candlestick_patterns_53a2.py', 'PHASE_53A2_VALIDATION_PASS', '53A2 regression'),
        ('scripts/validate_candle_anatomy_53a.py', 'PHASE_53A_VALIDATION_PASS', '53A regression'),
        ('scripts/validate_event_age_freshness_52r_d2.py', 'PHASE_52R_D2_VALIDATION_PASS', '52R-D2 regression'),
    )
    for path, marker, label in regressions:
        error, _ = _run_script(path, marker, label)
        if error:
            return _fail(error)
        print(f'V8_{label.replace("-", "_").replace(" ", "_").upper()}_OK')

    compile_targets = [
        'backend/config/build_info.py',
        'backend/analysis/key_levels_supply_demand.py',
        'backend/analysis/price_action_structure.py',
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
        'scripts/test_key_levels_supply_demand_53c.py',
        'scripts/validate_key_levels_supply_demand_53c.py',
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

    staged = _git_paths('diff', '--cached', '--name-only')
    if staged:
        return _fail(f'nothing may be staged: {sorted(staged)}')
    data_after = _git_paths('status', '--short', '--', 'data')
    if data_after:
        return _fail(f'repository data/ is dirty: {sorted(data_after)}')

    print('PHASE_53C_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
