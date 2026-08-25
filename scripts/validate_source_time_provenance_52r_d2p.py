#!/usr/bin/env python3
"""Validator — AstraEdge 52R-D2P source timestamp provenance (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = '5063f488878b548e2e2aad6b8fa5a705a94b5ddb'
CANONICAL_TREE = '4baf34a1eb7da14bcd9ba62cb034b594819b56da'
COMMITTED_D2P_HEAD = '8e526eb374a01d07bc3bab4fb00e620b238793c6'
COMMITTED_D2P_TREE = '44d7b3109a64bf7c36e93b863c47a1258a8453a3'
ALLOWED_HEADS = frozenset({CANONICAL_HEAD, COMMITTED_D2P_HEAD})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'news' / 'source_time_provenance.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py',
    PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py',
    PROJECT_ROOT / 'scripts' / 'test_source_time_provenance_52r_d2p.py',
    PROJECT_ROOT / 'scripts' / 'validate_source_time_provenance_52r_d2p.py',
)

PROTECTED_PRODUCTION = {
    'backend/news/broker_discovery_foundation.py',
    'backend/news/verified_intelligence_store.py',
    'backend/news/verified_intelligence_classifier.py',
    'backend/news/primary_source_verifier.py',
    'backend/news/automatic_primary_verification.py',
    'backend/news/news_pipeline_reliability.py',
    'backend/trading/market_freshness_guard.py',
    'backend/trading/opening_session_freshness.py',
    'backend/orchestration/alert_freshness_gate.py',
    'backend/runtime/snapshot_freshness_monitor.py',
    'backend/collectors/live_news_tracker.py',
}

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/collectors/news_provider_registry.py',
    'backend/news/rss_discovery_adapter.py',
    'backend/news/source_time_provenance.py',
}

NEW_SOURCE = {
    'backend/news/source_time_provenance.py',
    'scripts/test_source_time_provenance_52r_d2p.py',
    'scripts/validate_source_time_provenance_52r_d2p.py',
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
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_REPORTS = {
    'phase52r_d2_event_age_freshness_audit.txt',
    'phase52r_d2p_diff.txt',
    'phase52r_d2p_integration_audit.txt',
    'phase52r_d2p_validation.txt',
    'phase52r_d2_diff.txt',
    'phase52r_d2_integration_audit.txt',
    'phase52r_d2_validation.txt',
}

ALLOWED_SUCCESSOR_D2 = {
    'backend/news/event_freshness_projection.py',
    'backend/config/build_info.py',
    'scripts/test_event_age_freshness_52r_d2.py',
    'scripts/validate_event_age_freshness_52r_d2.py',
}

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | NEW_SOURCE | ALLOWED_HISTORICAL_REGRESSIONS | ALLOWED_SUCCESSOR_D2

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
AI_NEEDLES = ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai')

REQUIRED_TEST_MARKERS = (
    'T0_BUILD_PAIR_OK',
    'T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11', 'T12', 'T13',
    'T14', 'T15', 'T16', 'T17', 'T18', 'T19', 'T20', 'T21', 'T22',
    'T23', 'T24', 'T25', 'T26', 'T27',
    'T28', 'T29', 'T30', 'T31', 'T32', 'T33', 'T34', 'T35', 'T36', 'T37', 'T38',
    'T39', 'T40', 'T41', 'T42', 'T43', 'T44', 'T45',
    'SOURCE_TIME_PROVENANCE_52R_D2P_PASS',
)

ENTRY_KEYS = (
    'sighting_id',
    'source_time_provenance',
    'source_time_basis',
    'source_time_value',
    'timezone_assumption',
    'recorded_at',
    'schema_version',
)
TOP_KEYS = ('schema_version', 'updated_at', 'entries')


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_D2P_SOURCE_TIME_PROVENANCE_FAIL: {msg}', file=sys.stderr)
    return 1


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return 'missing'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace('\\', '/')


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
        or name in {'railway.json', 'railway.toml', 'procfile'}
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
            for alias in node.names:
                imported.add(alias.name)
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
            f'HEAD must remain canonical D2P baseline {CANONICAL_HEAD} '
            f'or committed D2P HEAD {COMMITTED_D2P_HEAD}, got {actual_head}'
        )
    if actual_head == CANONICAL_HEAD and actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}'
    if actual_head == COMMITTED_D2P_HEAD and actual_tree != COMMITTED_D2P_TREE:
        return f'committed D2P HEAD tree must remain {COMMITTED_D2P_TREE}'

    tracked_changed = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'D2P_CHANGED_FILE_SCOPE '
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
            return 'backend/config/build_info.py must change for the 52R-D2P build bump'
        if 'backend/collectors/news_provider_registry.py' not in tracked_changed:
            return 'backend/collectors/news_provider_registry.py must retain timestamp basis'
        if 'backend/news/rss_discovery_adapter.py' not in tracked_changed:
            return 'backend/news/rss_discovery_adapter.py must bind provenance before A1'
        for required in NEW_SOURCE:
            if required not in relevant_untracked and required not in tracked_changed:
                return f'missing required D2P file {required}'
    else:
        for required in NEW_SOURCE:
            if required not in tracked_now:
                return f'missing required D2P file {required}'

    print('D2P_CHANGED_FILE_SCOPE_OK')
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
        ('52R-D2P', 'AstraEdge 52R-D2P'),
        ('52R-D2', 'AstraEdge 52R-D2'),
    }:
        return _fail(
            f'build must be exact 52R-D2P / AstraEdge 52R-D2P or successor '
            f'52R-D2 / AstraEdge 52R-D2, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    print('V1_BUILD_IDENTITY_OK')

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
    print('V2_PROTECTED_UNCHANGED_OK')

    from backend.news.broker_discovery_foundation import SCHEMA_VERSION as A1_SCHEMA

    if A1_SCHEMA != '52R-A1':
        return _fail(f'A1 schema mutated: {A1_SCHEMA}')
    foundation = (PROJECT_ROOT / 'backend/news/broker_discovery_foundation.py').read_text(encoding='utf-8')
    if 'def compute_event_fingerprint' not in foundation or 'def compute_sighting_fingerprint' not in foundation:
        return _fail('A1 fingerprint helpers missing')
    print('V3_A1_IDENTITY_UNCHANGED_OK')

    module_path = PROJECT_ROOT / 'backend/news/source_time_provenance.py'
    src = module_path.read_text(encoding='utf-8')
    imported = _imported_names(src)
    for mod in NETWORK_MODULES:
        if mod in imported:
            return _fail(f'provenance imports network module {mod!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b', src, re.M):
            return _fail(f'provenance import line mentions {mod!r}')
    for needle in AI_NEEDLES:
        if needle in src:
            return _fail(f'provenance mentions AI {needle!r}')
    if 'rss_discovery_adapter' in src:
        return _fail('provenance sidecar must not import or name the A2 adapter')
    if 'age_seconds' in src or 'freshness_state' in src or 'event_age' in src:
        return _fail('D2P must not calculate age or freshness')
    print('V4_ZERO_NETWORK_AI_AGE_OK')

    from backend.news.source_time_provenance import (
        ALLOWED_BASIS,
        BASIS_PUBLISHED_PARSED,
        BASIS_UPDATED_PARSED,
        ENTRY_KEYS as LIVE_ENTRY_KEYS,
        SCHEMA_VERSION,
        SOURCE_TIME_PRESENT,
        TOP_KEYS as LIVE_TOP_KEYS,
    )

    if SCHEMA_VERSION != '52R-D2P':
        return _fail(f'schema_version {SCHEMA_VERSION}')
    if tuple(LIVE_TOP_KEYS) != TOP_KEYS:
        return _fail('closed top-level schema mismatch')
    if tuple(LIVE_ENTRY_KEYS) != ENTRY_KEYS:
        return _fail('closed entry schema mismatch')
    if SOURCE_TIME_PRESENT != 'SOURCE_TIME_PRESENT':
        return _fail('SOURCE_TIME_PRESENT token drifted')
    if ALLOWED_BASIS != frozenset({BASIS_PUBLISHED_PARSED, BASIS_UPDATED_PARSED}):
        return _fail('basis split drifted')
    if BASIS_PUBLISHED_PARSED != 'PUBLISHED_PARSED' or BASIS_UPDATED_PARSED != 'UPDATED_PARSED':
        return _fail('basis tokens drifted')
    if 'datetime.now' in src and 'source_time_value' in src:
        # recorded_at/updated_at may use now; source_time_value must not.
        write_fn = src[src.find('def record_source_time_provenance'):]
        incoming_fn = src[src.find('def _incoming_entry'):src.find('def _identity_tuple')]
        if 'datetime.now' in incoming_fn:
            return _fail('source_time_value must not be synthesized from now')
        if 'source_time_value=datetime' in write_fn:
            return _fail('writer must not synthesize source_time_value')
    print('V5_CLOSED_SCHEMA_OK')

    registry = (PROJECT_ROOT / 'backend/collectors/news_provider_registry.py').read_text(encoding='utf-8')
    if "return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc), 'PUBLISHED_PARSED'" not in registry:
        return _fail('registry must preserve PUBLISHED_PARSED basis')
    if "return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc), 'UPDATED_PARSED'" not in registry:
        return _fail('registry must preserve UPDATED_PARSED basis distinctly')
    if '(pub or datetime.now(timezone.utc)).isoformat()' in registry:
        return _fail('registry still uses now-fallback as published source time')
    if "article_row['published_at'] = datetime.now" in registry:
        return _fail('registry still writes now into published_at')
    print('V6_NO_NOW_FALLBACK_OK')

    adapter = (PROJECT_ROOT / 'backend/news/rss_discovery_adapter.py').read_text(encoding='utf-8')
    if 'build_source_sighting' not in adapter or 'record_source_time_provenance' not in adapter:
        return _fail('adapter must prebuild and bind provenance')
    if 'ingested_at' in adapter and "payload['source_published_at'] = article.get('ingested_at')" in adapter:
        return _fail('adapter must never map ingested_at to source_published_at')
    ingest_fn = adapter[adapter.find('def _ingest_eligible_article'):adapter.find('def ingest_registry_articles')]
    rec_pos = ingest_fn.find('record_source_time_provenance')
    upsert_pos = ingest_fn.find('upsert_sighting')
    if rec_pos < 0 or upsert_pos < 0 or rec_pos > upsert_pos:
        return _fail('adapter must bind sidecar before A1 upsert')
    if 'Never create a sidecar row' not in adapter and 'never create a sidecar' not in adapter.lower():
        if 'Historical: A1 exists, sidecar missing' not in adapter:
            return _fail('adapter must preserve historical no-backfill contract')
    print('V7_ADAPTER_ORDER_AND_NO_BACKFILL_OK')

    c1a = (PROJECT_ROOT / 'backend/news/verified_intelligence_store.py').read_text(encoding='utf-8')
    if 'INTELLIGENCE_SCHEMA_VERSION' not in c1a:
        return _fail('C1A schema marker missing')
    c1b = (PROJECT_ROOT / 'backend/news/verified_intelligence_classifier.py').read_text(encoding='utf-8')
    if "DERIVATION_VERSION = '52R-C1B'" not in c1b:
        return _fail('C1B derivation version changed')
    d1 = (PROJECT_ROOT / 'backend/news/news_pipeline_reliability.py').read_text(encoding='utf-8')
    if "SCHEMA_VERSION = '52R-D1'" not in d1:
        return _fail('D1 schema changed')
    print('V8_C1A_C1B_D1_UNCHANGED_OK')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_source_time_provenance_52r_d2p.py')],
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
        return _fail('focused 52R-D2P provenance tests failed')
    missing = [m for m in REQUIRED_TEST_MARKERS if m not in out]
    if missing:
        return _fail(f'missing focused markers: {missing}')
    print('V9_FOCUSED_TESTS_OK')

    compile_targets = [
        'backend/news/source_time_provenance.py',
        'backend/collectors/news_provider_registry.py',
        'backend/news/rss_discovery_adapter.py',
        'backend/config/build_info.py',
        'scripts/test_source_time_provenance_52r_d2p.py',
        'scripts/validate_source_time_provenance_52r_d2p.py',
    ]
    compiled = subprocess.run(
        [sys.executable, '-m', 'py_compile', *compile_targets],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return _fail(f'V10 py_compile failed: {compiled.stderr or compiled.stdout}')
    print('V10_PY_COMPILE_OK')

    diff_check = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        return _fail(f'V11 git diff --check failed: {diff_check.stdout or diff_check.stderr}')
    print('V11_DIFF_CHECK_OK')

    after = {str(p): _file_digest(p) for p in WATCHED_PATHS}
    if before != after:
        return _fail('validator mutated watched source files')

    data_proc = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if (data_proc.stdout or '').strip():
        return _fail('repository data/ is not clean after focused validation')

    print('PHASE_52R_D2P_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
