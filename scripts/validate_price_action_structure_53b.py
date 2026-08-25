#!/usr/bin/env python3
"""Read-only validator for AstraEdge 53B price-action structure."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = '2a2414010aed70e2a34741534d6b66b6300b593c'
CANONICAL_TREE = 'd5876f3c78e2c7f0d29f2ec20721475ab11b91a5'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'price_action_structure.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candle_anatomy.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candlestick_patterns.py',
    PROJECT_ROOT / 'scripts' / 'test_price_action_structure_53b.py',
    PROJECT_ROOT / 'scripts' / 'validate_price_action_structure_53b.py',
    PROJECT_ROOT / 'scripts' / 'test_candlestick_patterns_53a2.py',
    PROJECT_ROOT / 'scripts' / 'validate_candlestick_patterns_53a2.py',
    PROJECT_ROOT / 'scripts' / 'test_candle_anatomy_53a.py',
    PROJECT_ROOT / 'scripts' / 'validate_candle_anatomy_53a.py',
    PROJECT_ROOT / 'scripts' / 'test_event_age_freshness_52r_d2.py',
    PROJECT_ROOT / 'scripts' / 'validate_event_age_freshness_52r_d2.py',
)

PROTECTED_PRODUCTION = {
    'backend/analysis/candle_anatomy.py',
    'backend/analysis/candlestick_patterns.py',
    'backend/collectors/live_news_tracker.py',
    'backend/trading/market_freshness_guard.py',
    'backend/trading/opening_session_freshness.py',
    'backend/orchestration/alert_freshness_gate.py',
    'backend/runtime/snapshot_freshness_monitor.py',
}

PROTECTED_PREFIXES = (
    'backend/news/',
)

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/price_action_structure.py',
}

NEW_SOURCE = {
    'backend/analysis/price_action_structure.py',
    'scripts/test_price_action_structure_53b.py',
    'scripts/validate_price_action_structure_53b.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
    'scripts/test_candlestick_patterns_53a2.py',
    'scripts/validate_candlestick_patterns_53a2.py',
    'scripts/test_candle_anatomy_53a.py',
    'scripts/validate_candle_anatomy_53a.py',
    'scripts/test_event_age_freshness_52r_d2.py',
    'scripts/validate_event_age_freshness_52r_d2.py',
}

ALLOWED_REPORTS = {
    'phase53b_review.txt',
    'phase53b_diff.txt',
}

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | NEW_SOURCE | ALLOWED_HISTORICAL_REGRESSIONS

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
FORBIDDEN_OUTPUT = (
    'buy',
    'sell',
    'long',
    'short',
    'entry',
    'stop',
    'target',
    'position_size',
    'trade_signal',
    'win_probability',
    'confidence',
    'recommendation',
)
REQUIRED_TEST_MARKERS = tuple(f'T{index}' for index in range(1, 56)) + (
    'PRICE_ACTION_STRUCTURE_53B_PASS',
)


def _fail(message: str) -> int:
    print(f'ASTRAEDGE_PHASE_53B_PRICE_ACTION_STRUCTURE_FAIL: {message}', file=sys.stderr)
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
    if isinstance(value, str):
        return [value]
    return []


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
    if actual_head != CANONICAL_HEAD:
        return f'HEAD must remain canonical 53B baseline {CANONICAL_HEAD}, got {actual_head}'
    if actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}, got {actual_tree}'

    tracked_changed = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'B53_CHANGED_FILE_SCOPE '
        f'head={actual_head} '
        f'tracked={sorted(tracked_changed)} '
        f'untracked_relevant={sorted(relevant_untracked)} '
        f'reports_untracked={sorted(reports_untracked)}'
    )

    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'53B reports must remain untracked: {sorted(reports_tracked)}'

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
    for path in PROTECTED_PRODUCTION:
        diff = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (diff.stdout or '').strip():
            return f'protected file changed: {path}'

    unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
    if unexpected:
        return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    if 'backend/config/build_info.py' not in tracked_changed:
        return 'backend/config/build_info.py must change for the 53B build bump'
    for path in NEW_SOURCE:
        if path not in relevant_untracked and path not in tracked_changed:
            return f'missing required 53B file: {path}'

    production_changes = {
        path for path in actual_source_scope
        if path.startswith('backend/')
    }
    if production_changes != INTENDED_PRODUCTION:
        return f'production scope must be exact: {sorted(production_changes)}'

    print('B53_CHANGED_FILE_SCOPE_OK')
    return None


def _run_script(path: str, marker: str, label: str) -> str | None:
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
        return f'{label} exited {proc.returncode}'
    if marker not in output:
        return f'{label} missing marker {marker}'
    return None


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

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('53B', 'AstraEdge 53B'):
        return _fail(f'build must be exact 53B / AstraEdge 53B, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    print('V1_BUILD_IDENTITY_OK')

    module_path = PROJECT_ROOT / 'backend' / 'analysis' / 'price_action_structure.py'
    if not module_path.is_file():
        return _fail('missing backend/analysis/price_action_structure.py')
    source = module_path.read_text(encoding='utf-8')
    imported = _imported_names(source)
    if 'def analyze_price_action_structure(' not in source:
        return _fail('public analyze_price_action_structure API is missing')
    if 'from backend.analysis.candle_anatomy import' not in source or 'analyze_candle' not in source:
        return _fail('53B must import and reuse 53A analyze_candle')
    if 'def analyze_candle(' in source:
        return _fail('53B must not reimplement analyze_candle')
    print('V2_PUBLIC_API_AND_53A_REUSE_OK')

    from backend.analysis.price_action_structure import (
        EVENT_TAG_ORDER,
        MIN_STRUCTURE_CANDLES,
        SWING_KIND_ORDER,
        SWING_SPAN,
        analyze_price_action_structure,
    )

    if SWING_SPAN != 2 or MIN_STRUCTURE_CANDLES != 5:
        return _fail(f'cardinality constants mismatch: span={SWING_SPAN} minimum={MIN_STRUCTURE_CANDLES}')
    if SWING_KIND_ORDER != ('HIGH', 'LOW'):
        return _fail(f'swing ordering mismatch: {SWING_KIND_ORDER}')
    expected_tags = (
        'BREAK_ABOVE_SWING_HIGH',
        'BREAK_BELOW_SWING_LOW',
        'BULLISH_BOS_LIKE',
        'BEARISH_BOS_LIKE',
        'BULLISH_CHOCH_LIKE',
        'BEARISH_CHOCH_LIKE',
    )
    if EVENT_TAG_ORDER != expected_tags:
        return _fail(f'event-tag ordering mismatch: {EVENT_TAG_ORDER}')
    required_literals = (
        'OK', 'INSUFFICIENT_CANDLES', 'MALFORMED',
        'FIRST_HIGH', 'HIGHER_HIGH', 'LOWER_HIGH', 'EQUAL_HIGH',
        'FIRST_LOW', 'HIGHER_LOW', 'LOWER_LOW', 'EQUAL_LOW',
        'BULLISH', 'BEARISH', 'MIXED', 'UNDEFINED',
        *expected_tags,
    )
    for literal in required_literals:
        if literal not in source:
            return _fail(f'missing required state/relation/tag literal: {literal}')
    print('V3_CONSTANTS_RELATIONS_AND_TAGS_OK')

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

    sample = analyze_price_action_structure([
        {'open': 5, 'high': 6, 'low': 4, 'close': 5},
        {'open': 6, 'high': 8, 'low': 5, 'close': 6},
        {'open': 7, 'high': 10, 'low': 6, 'close': 7},
        {'open': 6, 'high': 8, 'low': 5, 'close': 6},
        {'open': 5, 'high': 7, 'low': 4, 'close': 5},
    ])
    emitted = {value.strip().lower() for value in _emitted_strings(sample)}
    for token in FORBIDDEN_OUTPUT:
        if token in emitted:
            return _fail(f'forbidden interpretation token in output: {token}')
    print('V5_DESCRIPTIVE_OUTPUT_ONLY_OK')

    for path in ('backend/analysis/candle_anatomy.py', 'backend/analysis/candlestick_patterns.py'):
        changed = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (changed.stdout or '').strip():
            return _fail(f'protected analysis module changed: {path}')
    print('V6_53A_53A2_MODULES_UNCHANGED_OK')

    focused_error = _run_script(
        'scripts/test_price_action_structure_53b.py',
        'PRICE_ACTION_STRUCTURE_53B_PASS',
        'focused 53B tests',
    )
    if focused_error:
        return _fail(focused_error)
    focused_output = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_price_action_structure_53b.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f'{focused_output.stdout or ""}{focused_output.stderr or ""}'
    missing = [marker for marker in REQUIRED_TEST_MARKERS if marker not in combined]
    if focused_output.returncode != 0 or missing:
        return _fail(f'focused marker verification failed: missing={missing}')
    print('V7_FOCUSED_53B_OK')

    regressions = (
        ('scripts/validate_candlestick_patterns_53a2.py', 'PHASE_53A2_VALIDATION_PASS', '53A2 regression'),
        ('scripts/validate_candle_anatomy_53a.py', 'PHASE_53A_VALIDATION_PASS', '53A regression'),
        ('scripts/validate_event_age_freshness_52r_d2.py', 'PHASE_52R_D2_VALIDATION_PASS', '52R-D2 regression'),
    )
    for path, marker, label in regressions:
        error = _run_script(path, marker, label)
        if error:
            return _fail(error)
        print(f'V8_{label.replace("-", "_").replace(" ", "_").upper()}_OK')

    compile_targets = [
        'backend/config/build_info.py',
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
        'backend/analysis/price_action_structure.py',
        'scripts/test_price_action_structure_53b.py',
        'scripts/validate_price_action_structure_53b.py',
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

    print('PHASE_53B_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
