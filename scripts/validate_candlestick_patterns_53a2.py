#!/usr/bin/env python3
"""Validator — AstraEdge 53A2 deterministic candlestick-pattern grammar (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = '7596540a797432c24e01dcb79f2bd663c9f837cb'
CANONICAL_TREE = '0e056cec28e7f42322c87a8a8fb563ba2952e8eb'
COMMITTED_53A2_HEAD = '2a2414010aed70e2a34741534d6b66b6300b593c'
COMMITTED_53A2_TREE = 'd5876f3c78e2c7f0d29f2ec20721475ab11b91a5'
COMMITTED_53B_HEAD = '7df88790ad9ada1a81b0f5613caafb05a0c217d5'
COMMITTED_53B_TREE = '91f784a344655723cbc5f322703029f67aa0f544'
COMMITTED_53C_HEAD = 'd8419ef6296928fa7ffe6cbaae3916c77435fefa'
COMMITTED_53C_TREE = '8b3008e6db85ead22dda60029775bfd1448a77d1'
COMMITTED_53D_HEAD = 'f500a9413103a3bca7c5aaaeed9062472fa913c4'
COMMITTED_53D_TREE = 'ca5201a4c2283f5fd553119b2de512c6378efe3b'
COMMITTED_53E_HEAD = 'eeaeb222fdc02a29bdda76c03de0f56d85bb3ceb'
COMMITTED_53E_TREE = '6962e5556de1f08a826f1c4eb8b8bb63ece0fd75'
COMMITTED_53E2_HEAD = 'e43be3ca8b3c2036fb8a7a85078c9e6911289f25'
COMMITTED_53E2_TREE = '66ec9e271d3851f78d593a11fa542d30cccdbcbe'
COMMITTED_53F_HEAD = '52dc868d5cf1aad2ffb179a5f4ad2ad674eb276f'
COMMITTED_53F_TREE = 'e17ffb3b7069baee7786ead330795ecfad252054'
ALLOWED_HEADS = frozenset({
    CANONICAL_HEAD,
    COMMITTED_53A2_HEAD,
    COMMITTED_53B_HEAD,
    COMMITTED_53C_HEAD,
    COMMITTED_53D_HEAD,
    COMMITTED_53E_HEAD,
    COMMITTED_53E2_HEAD,
    COMMITTED_53F_HEAD,
})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'candlestick_patterns.py',
    PROJECT_ROOT / 'scripts' / 'test_candlestick_patterns_53a2.py',
    PROJECT_ROOT / 'scripts' / 'validate_candlestick_patterns_53a2.py',
    PROJECT_ROOT / 'backend' / 'analysis' / 'premarket_structure.py',
    PROJECT_ROOT / 'scripts' / 'test_premarket_structure_53e2.py',
    PROJECT_ROOT / 'scripts' / 'validate_premarket_structure_53e2.py',
)

PROTECTED_PRODUCTION = {
    'backend/analysis/candle_anatomy.py',
    'backend/news/broker_discovery_foundation.py',
    'backend/news/source_time_provenance.py',
    'backend/news/verified_intelligence_store.py',
    'backend/news/verified_intelligence_classifier.py',
    'backend/news/primary_source_verifier.py',
    'backend/news/automatic_primary_verification.py',
    'backend/news/news_pipeline_reliability.py',
    'backend/news/event_freshness_projection.py',
    'backend/news/rss_discovery_adapter.py',
    'backend/collectors/news_provider_registry.py',
    'backend/collectors/live_news_tracker.py',
    'backend/trading/market_freshness_guard.py',
    'backend/trading/opening_session_freshness.py',
    'backend/orchestration/alert_freshness_gate.py',
    'backend/runtime/snapshot_freshness_monitor.py',
}

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/analysis/candlestick_patterns.py',
}

NEW_SOURCE = {
    'backend/analysis/candlestick_patterns.py',
    'scripts/test_candlestick_patterns_53a2.py',
    'scripts/validate_candlestick_patterns_53a2.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
    'scripts/test_candle_anatomy_53a.py',
    'scripts/validate_candle_anatomy_53a.py',
    'scripts/test_broker_discovery_foundation_52r_a1.py',
    'scripts/validate_broker_discovery_foundation_52r_a1.py',
    'scripts/test_rss_discovery_adapter_52r_a2.py',
    'scripts/validate_rss_discovery_adapter_52r_a2.py',
    'scripts/test_primary_source_verifier_52r_b1.py',
    'scripts/validate_primary_source_verifier_52r_b1.py',
    'scripts/test_nse_authoritative_rss_ingest_52r_b2n.py',
    'scripts/validate_nse_authoritative_rss_ingest_52r_b2n.py',
    'scripts/test_automatic_primary_verification_52r_b2.py',
    'scripts/validate_automatic_primary_verification_52r_b2.py',
    'scripts/test_verified_intelligence_store_52r_c1a.py',
    'scripts/validate_verified_intelligence_store_52r_c1a.py',
    'scripts/test_verified_intelligence_classifier_52r_c1b.py',
    'scripts/validate_verified_intelligence_classifier_52r_c1b.py',
    'scripts/test_news_pipeline_reliability_52r_d.py',
    'scripts/validate_news_pipeline_reliability_52r_d.py',
    'scripts/test_source_time_provenance_52r_d2p.py',
    'scripts/validate_source_time_provenance_52r_d2p.py',
    'scripts/test_event_age_freshness_52r_d2.py',
    'scripts/validate_event_age_freshness_52r_d2.py',
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_REPORTS = {
    'phase53a2_review.txt',
    'phase53a2_diff.txt',
    'phase53a_review.txt',
    'phase53a_diff.txt',
    'phase52r_d2_diff.txt',
    'phase52r_d2_integration_audit.txt',
    'phase52r_d2_validation.txt',
    'phase53b_review.txt',
    'phase53b_diff.txt',
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
    'phase53g_review.txt',
    'phase53g_diff.txt',
}

ALLOWED_SUCCESSOR_53B = {
    'backend/analysis/price_action_structure.py',
    'scripts/test_price_action_structure_53b.py',
    'scripts/validate_price_action_structure_53b.py',
}

ALLOWED_SUCCESSOR_53C = {
    'backend/analysis/key_levels_supply_demand.py',
    'scripts/test_key_levels_supply_demand_53c.py',
    'scripts/validate_key_levels_supply_demand_53c.py',
}

ALLOWED_SUCCESSOR_53D = {
    'backend/analysis/volume_vwap.py',
    'scripts/test_volume_vwap_53d.py',
    'scripts/validate_volume_vwap_53d.py',
}

ALLOWED_SUCCESSOR_53E = {
    'backend/analysis/multi_timeframe.py',
    'scripts/test_multi_timeframe_53e.py',
    'scripts/validate_multi_timeframe_53e.py',
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
    'scripts/test_price_action_structure_53b.py',
    'scripts/validate_price_action_structure_53b.py',
    'scripts/test_candlestick_patterns_53a2.py',
    'scripts/validate_candlestick_patterns_53a2.py',
    'scripts/test_candle_anatomy_53a.py',
    'scripts/validate_candle_anatomy_53a.py',
    'scripts/test_event_age_freshness_52r_d2.py',
    'scripts/validate_event_age_freshness_52r_d2.py',
}

SUCCESSOR_53E2_CHANGED_SOURCE = (
    {'backend/config/build_info.py'}
    | SUCCESSOR_53E2_COMPATIBILITY
    | ALLOWED_SUCCESSOR_53E2
)

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

ALLOWED_SUCCESSOR_53G = {
    'backend/analysis/full_stack.py',
    'scripts/test_full_stack_53g.py',
    'scripts/validate_full_stack_53g.py',
}

SUCCESSOR_53G_COMPATIBILITY = {
    'scripts/test_historical_setup_evidence_53f.py',
    'scripts/validate_historical_setup_evidence_53f.py',
    *SUCCESSOR_53F_COMPATIBILITY,
}

SUCCESSOR_53G_CHANGED_SOURCE = (
    {'backend/config/build_info.py'}
    | SUCCESSOR_53G_COMPATIBILITY
    | ALLOWED_SUCCESSOR_53G
)

ALLOWED_CHANGED_SOURCE = (
    INTENDED_PRODUCTION
    | NEW_SOURCE
    | ALLOWED_HISTORICAL_REGRESSIONS
    | ALLOWED_SUCCESSOR_53B
    | ALLOWED_SUCCESSOR_53C
    | ALLOWED_SUCCESSOR_53D
    | ALLOWED_SUCCESSOR_53E
)

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
AI_NEEDLES = ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai')
WRITE_NEEDLES = ('atomic_write', 'write_text', 'write_bytes')
REPAIR1_TEST_MARKERS = (
    'R1_ONE_VALID_INSUFFICIENT_OK',
    'R1_ONE_MALFORMED_INSUFFICIENT_OK',
    'R1_EMPTY_INSUFFICIENT_OK',
    'R1_FOUR_VALID_UNSUPPORTED_OK',
    'R1_FOUR_MALFORMED_UNSUPPORTED_OK',
    'R1_TWO_MALFORMED_OK',
    'R1_THREE_MALFORMED_OK',
    'CANDLESTICK_PATTERNS_53A2_REPAIR1_CARDINALITY_OK',
)
REQUIRED_TEST_MARKERS = (
    tuple(f'T{i}' for i in range(1, 41))
    + REPAIR1_TEST_MARKERS
    + ('CANDLESTICK_PATTERNS_53A2_PASS',)
)
THRESHOLD_NAMES = (
    'TWEEZER_LEVEL_TOLERANCE_RATIO',
    'STAR_SMALL_BODY_RATIO_MAX',
    'STAR_OUTER_BODY_RATIO_MIN',
    'SOLDIER_BODY_RATIO_MIN',
    'PATTERN_TAG_ORDER',
)
REQUIRED_TAGS = (
    'BULLISH_ENGULFING',
    'BEARISH_ENGULFING',
    'BULLISH_HARAMI',
    'BEARISH_HARAMI',
    'PIERCING_LINE_LIKE',
    'DARK_CLOUD_COVER_LIKE',
    'INSIDE_BAR',
    'OUTSIDE_BAR',
    'TWEEZER_TOP_LIKE',
    'TWEEZER_BOTTOM_LIKE',
    'MORNING_STAR_LIKE',
    'EVENING_STAR_LIKE',
    'THREE_WHITE_SOLDIERS_LIKE',
    'THREE_BLACK_CROWS_LIKE',
)
FORBIDDEN_OUTPUT = (
    'buy',
    'sell',
    'entry',
    'stop',
    'target',
    'recommendation',
    'probability',
    'confidence',
    'trade_signal',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_53A2_CANDLESTICK_PATTERNS_FAIL: {msg}', file=sys.stderr)
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


def _imported_names(src: str) -> set[str]:
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split('.')[0])
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            imported.add(mod.split('.')[0])
            imported.add(mod)
    return imported


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
            f'HEAD must remain canonical 53A2 baseline {CANONICAL_HEAD} '
            f'or committed 53A2 HEAD {COMMITTED_53A2_HEAD}, got {actual_head}'
        )
    if actual_head == CANONICAL_HEAD and actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}'
    if actual_head == COMMITTED_53A2_HEAD and actual_tree != COMMITTED_53A2_TREE:
        return f'committed 53A2 HEAD tree must remain {COMMITTED_53A2_TREE}'
    if actual_head == COMMITTED_53B_HEAD and actual_tree != COMMITTED_53B_TREE:
        return f'committed 53B HEAD tree must remain {COMMITTED_53B_TREE}'
    if actual_head == COMMITTED_53C_HEAD and actual_tree != COMMITTED_53C_TREE:
        return f'committed 53C HEAD tree must remain {COMMITTED_53C_TREE}'
    if actual_head == COMMITTED_53D_HEAD and actual_tree != COMMITTED_53D_TREE:
        return f'committed 53D HEAD tree must remain {COMMITTED_53D_TREE}'
    if actual_head == COMMITTED_53E_HEAD and actual_tree != COMMITTED_53E_TREE:
        return f'committed 53E HEAD tree must remain {COMMITTED_53E_TREE}'
    if actual_head == COMMITTED_53E2_HEAD and actual_tree != COMMITTED_53E2_TREE:
        return f'committed 53E2 HEAD tree must remain {COMMITTED_53E2_TREE}'
    if actual_head == COMMITTED_53F_HEAD and actual_tree != COMMITTED_53F_TREE:
        return f'committed 53F HEAD tree must remain {COMMITTED_53F_TREE}'

    tracked_changed = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'A53A2_CHANGED_FILE_SCOPE '
        f'head={actual_head} '
        f'tracked={sorted(tracked_changed)} '
        f'untracked_relevant={sorted(relevant_untracked)} '
        f'reports_untracked={sorted(reports_untracked)}'
    )

    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'review reports must remain untracked: {sorted(reports_tracked)}'

    staged = _git_paths('diff', '--cached', '--name-only')
    if staged:
        return f'nothing may be staged: {sorted(staged)}'

    data_changes = {
        path for path in (tracked_changed | untracked)
        if path == 'data' or path.startswith('data/')
    }
    if data_changes:
        return f'data/ changes are never allowed: {sorted(data_changes)}'

    protected_hits = tracked_changed & PROTECTED_PRODUCTION
    if protected_hits:
        return f'protected production files changed: {sorted(protected_hits)}'
    for required in PROTECTED_PRODUCTION:
        diff = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', required],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (diff.stdout or '').strip():
            return f'protected file changed: {required}'

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
    elif actual_head == COMMITTED_53F_HEAD:
        if actual_source_scope != SUCCESSOR_53G_CHANGED_SOURCE:
            missing = sorted(SUCCESSOR_53G_CHANGED_SOURCE - actual_source_scope)
            unexpected = sorted(actual_source_scope - SUCCESSOR_53G_CHANGED_SOURCE)
            return f'53G changed source scope mismatch: missing={missing} unexpected={unexpected}'
    else:
        unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
        if unexpected:
            return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    if actual_head == CANONICAL_HEAD:
        if 'backend/config/build_info.py' not in tracked_changed:
            return 'backend/config/build_info.py must change for the 53A2 build bump'
        for required in NEW_SOURCE:
            if required not in relevant_untracked and required not in tracked_changed:
                return f'missing required 53A2 file {required}'
    elif actual_head == COMMITTED_53E_HEAD:
        committed_predecessors = (
            NEW_SOURCE
            | ALLOWED_SUCCESSOR_53B
            | ALLOWED_SUCCESSOR_53C
            | ALLOWED_SUCCESSOR_53D
            | ALLOWED_SUCCESSOR_53E
        )
        if not committed_predecessors <= tracked_now:
            return f'missing committed predecessor files: {sorted(committed_predecessors - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53E2 <= relevant_untracked:
            return f'missing required 53E2 successor files: {sorted(ALLOWED_SUCCESSOR_53E2 - relevant_untracked)}'
        if 'backend/config/build_info.py' not in tracked_changed:
            return 'backend/config/build_info.py must change for the 53E2 successor build bump'
        for path in (
            'backend/analysis/candlestick_patterns.py',
            'backend/analysis/price_action_structure.py',
            'backend/analysis/key_levels_supply_demand.py',
            'backend/analysis/volume_vwap.py',
            'backend/analysis/multi_timeframe.py',
        ):
            if path in tracked_changed:
                return f'predecessor production must remain unchanged for 53E2: {path}'
    elif actual_head == COMMITTED_53E2_HEAD:
        committed_predecessors = (
            NEW_SOURCE
            | ALLOWED_SUCCESSOR_53B
            | ALLOWED_SUCCESSOR_53C
            | ALLOWED_SUCCESSOR_53D
            | ALLOWED_SUCCESSOR_53E
            | ALLOWED_SUCCESSOR_53E2
        )
        if not committed_predecessors <= tracked_now:
            return f'missing committed predecessor files: {sorted(committed_predecessors - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53F <= relevant_untracked:
            return f'missing required 53F successor files: {sorted(ALLOWED_SUCCESSOR_53F - relevant_untracked)}'
        if 'backend/config/build_info.py' not in tracked_changed:
            return 'backend/config/build_info.py must change for the 53F successor build bump'
        for path in (
            'backend/analysis/candlestick_patterns.py',
            'backend/analysis/price_action_structure.py',
            'backend/analysis/key_levels_supply_demand.py',
            'backend/analysis/volume_vwap.py',
            'backend/analysis/multi_timeframe.py',
            'backend/analysis/premarket_structure.py',
        ):
            if path in tracked_changed:
                return f'predecessor production must remain unchanged for 53F: {path}'
    elif actual_head == COMMITTED_53F_HEAD:
        committed_predecessors = (
            NEW_SOURCE
            | ALLOWED_SUCCESSOR_53B
            | ALLOWED_SUCCESSOR_53C
            | ALLOWED_SUCCESSOR_53D
            | ALLOWED_SUCCESSOR_53E
            | ALLOWED_SUCCESSOR_53E2
            | ALLOWED_SUCCESSOR_53F
        )
        if not committed_predecessors <= tracked_now:
            return f'missing committed predecessor files: {sorted(committed_predecessors - tracked_now)}'
        if not ALLOWED_SUCCESSOR_53G <= relevant_untracked:
            return f'missing required 53G successor files: {sorted(ALLOWED_SUCCESSOR_53G - relevant_untracked)}'
        if 'backend/config/build_info.py' not in tracked_changed:
            return 'backend/config/build_info.py must change for the 53G successor build bump'
        for path in (
            'backend/analysis/candlestick_patterns.py',
            'backend/analysis/price_action_structure.py',
            'backend/analysis/key_levels_supply_demand.py',
            'backend/analysis/volume_vwap.py',
            'backend/analysis/multi_timeframe.py',
            'backend/analysis/premarket_structure.py',
            'backend/analysis/historical_setup_evidence.py',
        ):
            if path in tracked_changed:
                return f'predecessor production must remain unchanged for 53G: {path}'
    else:
        for required in NEW_SOURCE:
            if required not in tracked_now:
                return f'missing committed 53A2 file {required}'
        if 'backend/config/build_info.py' not in tracked_changed:
            return 'backend/config/build_info.py must change for the 53B successor build bump'
        if 'backend/analysis/candlestick_patterns.py' in tracked_changed:
            return '53A2 candlestick_patterns.py must remain unchanged for 53B'

    print('A53A2_CHANGED_FILE_SCOPE_OK')
    return None


def _run_script(rel: str, pass_marker: str, fail_label: str) -> str | None:
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / rel)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    out = f'{proc.stdout or ""}{proc.stderr or ""}'
    if proc.stdout:
        print(proc.stdout, end='' if proc.stdout.endswith('\n') else '\n')
    if proc.stderr:
        print(proc.stderr, end='' if proc.stderr.endswith('\n') else '\n', file=sys.stderr)
    if proc.returncode != 0:
        return fail_label
    if pass_marker not in out:
        return f'{fail_label}: missing {pass_marker}'
    return None


def main() -> int:
    before = {str(p): _file_digest(p) for p in WATCHED_PATHS}

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
        ('53A2', 'AstraEdge 53A2'),
        ('53B', 'AstraEdge 53B'),
        ('53C', 'AstraEdge 53C'),
        ('53D', 'AstraEdge 53D'),
        ('53E', 'AstraEdge 53E'),
        ('53E2', 'AstraEdge 53E2'),
        ('53F', 'AstraEdge 53F'),
        ('53G', 'AstraEdge 53G'),
    }:
        return _fail(
            f'build must be exact 53A2 or successor 53B/53C/53D/53E/53E2/53F/53G pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    print('V1_BUILD_IDENTITY_OK')

    anatomy_diff = subprocess.run(
        ['git', 'diff', '--name-only', 'HEAD', '--', 'backend/analysis/candle_anatomy.py'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if (anatomy_diff.stdout or '').strip():
        return _fail('53A candle_anatomy.py must remain unchanged')
    print('V2_53A_MODULE_UNCHANGED_OK')

    module_path = PROJECT_ROOT / 'backend/analysis/candlestick_patterns.py'
    if not module_path.is_file():
        return _fail('missing backend/analysis/candlestick_patterns.py')
    src = module_path.read_text(encoding='utf-8')
    imported = _imported_names(src)
    if 'def analyze_candlestick_patterns(' not in src:
        return _fail('public analyzer analyze_candlestick_patterns is missing')
    if 'from backend.analysis.candle_anatomy import' not in src or 'analyze_candle' not in src:
        return _fail('53A2 must import/reuse analyze_candle')
    if 'def analyze_candle(' in src:
        return _fail('53A2 must not reimplement analyze_candle')
    for name in THRESHOLD_NAMES:
        if name not in src:
            return _fail(f'missing threshold constant {name}')
    for tag in REQUIRED_TAGS:
        if tag not in src:
            return _fail(f'missing pattern tag {tag}')
    for mod in NETWORK_MODULES:
        if mod in imported:
            return _fail(f'analyzer imports network module {mod!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b', src, re.M):
            return _fail(f'analyzer import line mentions {mod!r}')
    for needle in AI_NEEDLES:
        if needle in src:
            return _fail(f'analyzer mentions AI {needle!r}')
    for needle in WRITE_NEEDLES:
        if needle in src:
            return _fail(f'analyzer contains write path {needle!r}')
    if 'open(' in src:
        return _fail('analyzer contains open() path')
    for needle in (
        'market_freshness_guard',
        'opening_session_freshness',
        'alert_freshness_gate',
        'snapshot_freshness_monitor',
        'event_freshness_projection',
        'broker_discovery_foundation',
        'news_pipeline_reliability',
        'live_news_tracker',
    ):
        if needle in src:
            return _fail(f'analyzer depends on {needle}')
    src_lower = src.lower()
    for token in FORBIDDEN_OUTPUT:
        if token in src_lower:
            return _fail(f'analyzer source contains trade-interpretation token {token}')
    print('V3_ANALYZER_CONTRACT_OK')

    for rel in PROTECTED_PRODUCTION:
        diff = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', rel],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (diff.stdout or '').strip():
            return _fail(f'protected file changed vs HEAD: {rel}')
    print('V4_PROTECTED_UNCHANGED_OK')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_candlestick_patterns_53a2.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    out = f'{proc.stdout or ""}{proc.stderr or ""}'
    if proc.stdout:
        print(proc.stdout, end='' if proc.stdout.endswith('\n') else '\n')
    if proc.stderr:
        print(proc.stderr, end='' if proc.stderr.endswith('\n') else '\n', file=sys.stderr)
    if proc.returncode != 0:
        return _fail('focused 53A2 candlestick pattern tests failed')
    missing = [m for m in REQUIRED_TEST_MARKERS if m not in out]
    if missing:
        return _fail(f'missing focused markers: {missing}')
    print('V5_FOCUSED_TESTS_OK')

    a53 = _run_script(
        'scripts/validate_candle_anatomy_53a.py',
        'PHASE_53A_VALIDATION_PASS',
        '53A validator/regression failed',
    )
    if a53:
        return _fail(a53)
    print('V6_53A_REGRESSION_OK')

    d2 = _run_script(
        'scripts/validate_event_age_freshness_52r_d2.py',
        'PHASE_52R_D2_VALIDATION_PASS',
        '52R-D2 validator failed',
    )
    if d2:
        return _fail(d2)
    print('V7_52R_D2_REGRESSION_OK')

    compile_targets = [
        'backend/analysis/__init__.py',
        'backend/analysis/candle_anatomy.py',
        'backend/analysis/candlestick_patterns.py',
        'backend/config/build_info.py',
        'scripts/test_candlestick_patterns_53a2.py',
        'scripts/validate_candlestick_patterns_53a2.py',
        'scripts/test_candle_anatomy_53a.py',
        'scripts/validate_candle_anatomy_53a.py',
    ]
    compiled = subprocess.run(
        [sys.executable, '-m', 'py_compile', *compile_targets],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return _fail(f'V8 py_compile failed: {compiled.stderr or compiled.stdout}')
    print('V8_PY_COMPILE_OK')

    diff_check = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        return _fail(f'V9 git diff --check failed: {diff_check.stdout or diff_check.stderr}')
    print('V9_DIFF_CHECK_OK')

    after = {str(p): _file_digest(p) for p in WATCHED_PATHS}
    if before != after:
        return _fail('validator mutated watched source files')

    staged = subprocess.run(
        ['git', 'diff', '--cached', '--name-only'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if (staged.stdout or '').strip():
        return _fail(f'nothing may be staged: {(staged.stdout or "").strip()}')

    data_proc = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if (data_proc.stdout or '').strip():
        return _fail('repository data/ is not clean after focused validation')

    print('PHASE_53A2_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
