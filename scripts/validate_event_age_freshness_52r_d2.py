#!/usr/bin/env python3
"""Validator — AstraEdge 52R-D2 read-time event freshness projection (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = '8e526eb374a01d07bc3bab4fb00e620b238793c6'
CANONICAL_TREE = '44d7b3109a64bf7c36e93b863c47a1258a8453a3'
COMMITTED_D2_HEAD = '1e47967bbdf9cd1338d525c008b9ea376943a18a'
COMMITTED_D2_TREE = 'cbf045ab4a99a2537cba9097a6354c0c1256b4d3'
COMMITTED_53A_HEAD = '7596540a797432c24e01dcb79f2bd663c9f837cb'
COMMITTED_53A_TREE = '0e056cec28e7f42322c87a8a8fb563ba2952e8eb'
COMMITTED_53A2_HEAD = '2a2414010aed70e2a34741534d6b66b6300b593c'
COMMITTED_53A2_TREE = 'd5876f3c78e2c7f0d29f2ec20721475ab11b91a5'
COMMITTED_53B_HEAD = '7df88790ad9ada1a81b0f5613caafb05a0c217d5'
COMMITTED_53B_TREE = '91f784a344655723cbc5f322703029f67aa0f544'
ALLOWED_HEADS = frozenset({
    CANONICAL_HEAD,
    COMMITTED_D2_HEAD,
    COMMITTED_53A_HEAD,
    COMMITTED_53A2_HEAD,
    COMMITTED_53B_HEAD,
})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'news' / 'event_freshness_projection.py',
    PROJECT_ROOT / 'scripts' / 'test_event_age_freshness_52r_d2.py',
    PROJECT_ROOT / 'scripts' / 'validate_event_age_freshness_52r_d2.py',
)

PROTECTED_PRODUCTION = {
    'backend/news/broker_discovery_foundation.py',
    'backend/news/source_time_provenance.py',
    'backend/news/verified_intelligence_store.py',
    'backend/news/verified_intelligence_classifier.py',
    'backend/news/primary_source_verifier.py',
    'backend/news/automatic_primary_verification.py',
    'backend/news/news_pipeline_reliability.py',
    'backend/collectors/news_provider_registry.py',
    'backend/news/rss_discovery_adapter.py',
    'backend/collectors/live_news_tracker.py',
    'backend/trading/market_freshness_guard.py',
    'backend/trading/opening_session_freshness.py',
    'backend/orchestration/alert_freshness_gate.py',
    'backend/runtime/snapshot_freshness_monitor.py',
}

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/news/event_freshness_projection.py',
}

NEW_SOURCE = {
    'backend/news/event_freshness_projection.py',
    'scripts/test_event_age_freshness_52r_d2.py',
    'scripts/validate_event_age_freshness_52r_d2.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
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
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_REPORTS = {
    'phase52r_d2_event_age_freshness_audit.txt',
    'phase52r_d2_diff.txt',
    'phase52r_d2_integration_audit.txt',
    'phase52r_d2_validation.txt',
    'phase52r_d2p_diff.txt',
    'phase52r_d2p_integration_audit.txt',
    'phase52r_d2p_validation.txt',
    'phase52r_d2p_prod_repair1.txt',
    'phase53a_review.txt',
    'phase53a_diff.txt',
    'phase53b_review.txt',
    'phase53b_diff.txt',
    'phase53c_review.txt',
    'phase53c_diff.txt',
}

ALLOWED_SUCCESSOR_53A = {
    'backend/analysis/__init__.py',
    'backend/analysis/candle_anatomy.py',
    'backend/config/build_info.py',
    'scripts/test_candle_anatomy_53a.py',
    'scripts/validate_candle_anatomy_53a.py',
}

ALLOWED_SUCCESSOR_53A2 = {
    'backend/analysis/candlestick_patterns.py',
    'backend/config/build_info.py',
    'scripts/test_candlestick_patterns_53a2.py',
    'scripts/validate_candlestick_patterns_53a2.py',
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

ALLOWED_CHANGED_SOURCE = (
    INTENDED_PRODUCTION
    | NEW_SOURCE
    | ALLOWED_HISTORICAL_REGRESSIONS
    | ALLOWED_SUCCESSOR_53A
    | ALLOWED_SUCCESSOR_53A2
    | ALLOWED_SUCCESSOR_53B
    | ALLOWED_SUCCESSOR_53C
)

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
AI_NEEDLES = ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai')
WRITE_NEEDLES = (
    'atomic_write',
    'record_source_time_provenance',
    'upsert_sighting',
    'upsert_event',
    '_atomic_save',
    'write_text',
    'write_bytes',
)
STORE_SCAN_NEEDLES = (
    'list_event_sightings',
    'get_sighting',
    'get_event',
    'load_store',
    'find_events_by_symbol',
)
REQUIRED_TEST_MARKERS = tuple(f'T{i}' for i in range(1, 56)) + ('EVENT_AGE_FRESHNESS_52R_D2_PASS',)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_D2_EVENT_FRESHNESS_FAIL: {msg}', file=sys.stderr)
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
            f'HEAD must remain canonical D2 implementation baseline {CANONICAL_HEAD} '
            f'or committed D2 HEAD {COMMITTED_D2_HEAD} '
            f'or committed successor HEAD, got {actual_head}'
        )
    if actual_head == CANONICAL_HEAD and actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}'
    if actual_head == COMMITTED_D2_HEAD and actual_tree != COMMITTED_D2_TREE:
        return f'committed D2 HEAD tree must remain {COMMITTED_D2_TREE}'
    if actual_head == COMMITTED_53A_HEAD and actual_tree != COMMITTED_53A_TREE:
        return f'committed 53A HEAD tree must remain {COMMITTED_53A_TREE}'
    if actual_head == COMMITTED_53A2_HEAD and actual_tree != COMMITTED_53A2_TREE:
        return f'committed 53A2 HEAD tree must remain {COMMITTED_53A2_TREE}'
    if actual_head == COMMITTED_53B_HEAD and actual_tree != COMMITTED_53B_TREE:
        return f'committed 53B HEAD tree must remain {COMMITTED_53B_TREE}'

    tracked_changed = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'D2_CHANGED_FILE_SCOPE '
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

    unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
    if unexpected:
        return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    if actual_head == CANONICAL_HEAD:
        if 'backend/config/build_info.py' not in tracked_changed:
            return 'backend/config/build_info.py must change for the 52R-D2 build bump'
        for required in NEW_SOURCE:
            if required not in relevant_untracked and required not in tracked_changed:
                return f'missing required D2 file {required}'
    else:
        for required in NEW_SOURCE:
            if required not in tracked_now:
                return f'missing required D2 file {required}'

    print('D2_CHANGED_FILE_SCOPE_OK')
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
        ('52R-D2', 'AstraEdge 52R-D2'),
        ('53A', 'AstraEdge 53A'),
        ('53A2', 'AstraEdge 53A2'),
        ('53B', 'AstraEdge 53B'),
        ('53C', 'AstraEdge 53C'),
    }:
        return _fail(
            f'build must be exact 52R-D2 / AstraEdge 52R-D2 or successor '
            f'53A / AstraEdge 53A, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    print('V1_BUILD_IDENTITY_OK')

    module_path = PROJECT_ROOT / 'backend/news/event_freshness_projection.py'
    if not module_path.is_file():
        return _fail('missing backend/news/event_freshness_projection.py')
    src = module_path.read_text(encoding='utf-8')
    imported = _imported_names(src)
    for mod in NETWORK_MODULES:
        if mod in imported:
            return _fail(f'projector imports network module {mod!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b', src, re.M):
            return _fail(f'projector import line mentions {mod!r}')
    for needle in AI_NEEDLES:
        if needle in src:
            return _fail(f'projector mentions AI {needle!r}')
    for needle in WRITE_NEEDLES:
        if needle in src:
            return _fail(f'projector contains write/store-mutation path {needle!r}')
    if 'open(' in src:
        return _fail('projector contains open() write/read path')
    for needle in (
        'market_freshness_guard',
        'opening_session_freshness',
        'alert_freshness_gate',
        'snapshot_freshness_monitor',
    ):
        if needle in src:
            return _fail(f'projector imports trading freshness {needle}')
    if 'news_pipeline_reliability' in src or 'evaluate_news_pipeline_reliability' in src:
        return _fail('projector couples to D1 freshness')
    if 'source_age_seconds' in src:
        return _fail('generic source_age_seconds contract exists')
    if '_verified_linked_sighting' not in src:
        return _fail('event projector must verify sighting.event_id linkage')
    if 'sighting_event_id != event_id' not in src:
        return _fail('event projector must compare sighting.event_id to event.event_id')
    if 'health if health != HEALTH_OK else HEALTH_MALFORMED' in src:
        return _fail('malformed sighting_id must not synthesize sidecar HEALTH_MALFORMED')
    if 'PUBLISHED_PARSED' not in src or 'UPDATED_PARSED' not in src:
        return _fail('PUBLISHED_PARSED / UPDATED_PARSED distinction missing')
    if 'source_time_value' not in src or 'BINDING_MISMATCH' not in src:
        return _fail('binding comparison missing')
    if 'SOURCE_TIME_AMBIGUOUS' not in src:
        return _fail('historical ambiguity contract missing')
    if 'max(0' in src or 'max(0,' in src:
        return _fail('future timestamps must not be clamped')
    for needle in STORE_SCAN_NEEDLES:
        if needle in src:
            return _fail(f'projector scans A1 store via {needle}')
    print('V2_PROJECTOR_CONTRACT_OK')

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
    print('V3_PROTECTED_UNCHANGED_OK')

    from backend.news.broker_discovery_foundation import SCHEMA_VERSION as A1_SCHEMA
    from backend.news.source_time_provenance import SCHEMA_VERSION as D2P_SCHEMA
    from backend.news.verified_intelligence_classifier import DERIVATION_VERSION
    from backend.news.verified_intelligence_store import INTELLIGENCE_SCHEMA_VERSION
    from backend.news.news_pipeline_reliability import SCHEMA_VERSION as D1_SCHEMA

    if A1_SCHEMA != '52R-A1':
        return _fail(f'A1 schema mutated: {A1_SCHEMA}')
    if D2P_SCHEMA != '52R-D2P':
        return _fail(f'D2P schema mutated: {D2P_SCHEMA}')
    if INTELLIGENCE_SCHEMA_VERSION != '52R-C1A' or DERIVATION_VERSION != '52R-C1B':
        return _fail('C1A/C1B versions changed')
    if D1_SCHEMA != '52R-D1':
        return _fail(f'D1 schema mutated: {D1_SCHEMA}')
    print('V4_SCHEMA_UNCHANGED_OK')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_event_age_freshness_52r_d2.py')],
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
        return _fail('focused 52R-D2 event freshness tests failed')
    missing = [m for m in REQUIRED_TEST_MARKERS if m not in out]
    if missing:
        return _fail(f'missing focused markers: {missing}')
    print('V5_FOCUSED_TESTS_OK')

    compile_targets = [
        'backend/news/event_freshness_projection.py',
        'backend/config/build_info.py',
        'scripts/test_event_age_freshness_52r_d2.py',
        'scripts/validate_event_age_freshness_52r_d2.py',
    ]
    compiled = subprocess.run(
        [sys.executable, '-m', 'py_compile', *compile_targets],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return _fail(f'V6 py_compile failed: {compiled.stderr or compiled.stdout}')
    print('V6_PY_COMPILE_OK')

    diff_check = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        return _fail(f'V7 git diff --check failed: {diff_check.stdout or diff_check.stderr}')
    print('V7_DIFF_CHECK_OK')

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

    print('PHASE_52R_D2_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
