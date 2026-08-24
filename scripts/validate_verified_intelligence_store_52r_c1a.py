#!/usr/bin/env python3
"""Validator — AstraEdge 52R-C1A verified intelligence store foundation (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_IMPL_BASELINE = 'e6565b0988184ca3473b54a2a19818da9a7b2667'
COMMITTED_C1A_HEAD = '21c32dcf5a3a2280ccf90536e2ec238aa54b02e5'
BASELINE_COMMIT = ORIGINAL_IMPL_BASELINE
ALLOWED_HEADS = frozenset({ORIGINAL_IMPL_BASELINE, COMMITTED_C1A_HEAD})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_store.py',
    PROJECT_ROOT / 'scripts' / 'test_verified_intelligence_store_52r_c1a.py',
    PROJECT_ROOT / 'scripts' / 'validate_verified_intelligence_store_52r_c1a.py',
)

REQUIRED_MARKERS = (
    'C1A_BUILD_PAIR_OK',
    'C1A_MISSING_STORE_HEALTH_OK',
    'C1A_VALID_EMPTY_STORE_OK',
    'C1A_BUILD_PAIR_EXACT_OK',
    'C1A_FIRST_PRIMARY_INSERT_OK',
    'C1A_DETERMINISTIC_INTELLIGENCE_ID_OK',
    'C1A_DETERMINISTIC_SOURCE_INPUT_HASH_OK',
    'C1A_DETERMINISTIC_RECORD_FINGERPRINT_OK',
    'C1A_IDEMPOTENT_UPSERT_OK',
    'C1A_DERIVED_AT_PRESERVED_OK',
    'C1A_VERSION_CONFLICT_SOURCE_INPUT_OK',
    'C1A_VERSION_CONFLICT_CLASSIFICATION_OK',
    'C1A_NEW_DERIVATION_VERSION_ROW_OK',
    'C1A_NEW_TAXONOMY_VERSION_ROW_OK',
    'C1A_NON_PRIMARY_REJECTED_OK',
    'C1A_MISSING_PRIMARY_URL_REJECTED_OK',
    'C1A_MALFORMED_EVENT_UUID_REJECTED_OK',
    'C1A_MALFORMED_SOURCE_FINGERPRINT_REJECTED_OK',
    'C1A_UNKNOWN_CLASSIFICATION_REJECTED_OK',
    'C1A_INVALID_PROVENANCE_REJECTED_OK',
    'C1A_FACTS_NONEMPTY_REJECTED_OK',
    'C1A_FACT_PROVENANCE_NONEMPTY_REJECTED_OK',
    'C1A_RAW_MARKUP_FORBIDDEN_OK',
    'C1A_MALFORMED_STORE_IMMUTABLE_OK',
    'C1A_PARTIAL_STORE_IMMUTABLE_OK',
    'C1A_UNREADABLE_STORE_IMMUTABLE_OK',
    'C1A_LOCK_CONTENTION_ZERO_MUTATION_OK',
    'C1A_ATOMIC_SINGLE_WRITE_OK',
    'C1A_NO_REAL_REPO_DATA_ACCESS_OK',
    'C1A_NO_NETWORK_AI_TRADING_IMPORTS_OK',
    'C1A_NO_DISCOVERY_MUTATION_API_OK',
    'C1A_NO_PRODUCTION_CALLER_OK',
    'C1A_DORMANT_PRODUCTION_OK',
    'C1A_QUERY_ORDER_LIMIT_OK',
    'C1A_UTF8_ROUND_TRIP_OK',
    'C1A_FINGERPRINT_CORRUPTION_DETECTED_OK',
    'C1A_RECORD_ID_CORRUPTION_DETECTED_OK',
    'C1A_UPDATED_AT_NOT_IDENTITY_OK',
    'C1A_NO_PUBLISHER_CORROBORATION_IDENTITY_OK',
    'C1A_UPSERT_FORBIDDEN_FIELD_REJECTED_OK',
    'C1A_UPSERT_UNKNOWN_FIELD_REJECTED_OK',
    'C1A_UPSERT_OUTPUT_FIELD_REJECTED_OK',
    'C1A_UPSERT_EXTRA_FIELD_ZERO_MUTATION_OK',
    'VERIFIED_INTELLIGENCE_STORE_52R_C1A_PASS',
)

MUST_REMAIN_UNCHANGED = (
    'backend/news/broker_discovery_foundation.py',
    'backend/news/primary_source_verifier.py',
    'backend/news/automatic_primary_verification.py',
    'backend/news/rss_discovery_adapter.py',
)

MUST_REMAIN_UNCHANGED_EXCEPT_C1B_SUCCESSOR = (
    'backend/collectors/live_news_tracker.py',
)

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/news/verified_intelligence_store.py',
}

ALLOWED_C1A_TESTS = {
    'scripts/test_verified_intelligence_store_52r_c1a.py',
    'scripts/validate_verified_intelligence_store_52r_c1a.py',
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
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_SUCCESSOR_C1B = {
    'backend/news/verified_intelligence_classifier.py',
    'backend/collectors/live_news_tracker.py',
    'scripts/test_verified_intelligence_classifier_52r_c1b.py',
    'scripts/validate_verified_intelligence_classifier_52r_c1b.py',
}

ALLOWED_REPORTS = {
    'phase52r_c_architecture_audit.txt',
    'phase52r_c1a_validation.txt',
    'phase52r_c1a_diff.txt',
    'phase52r_c1b_integration_audit.txt',
    'phase52r_c1b_validation.txt',
    'phase52r_c1b_diff.txt',
}

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | ALLOWED_C1A_TESTS | ALLOWED_HISTORICAL_REGRESSIONS | ALLOWED_SUCCESSOR_C1B

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
DISCOVERY_MUTATION = (
    'upsert_sighting',
    'mark_primary_source_verified',
    'run_automatic_primary_verification',
    'verify_linked_primary_sighting',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_C1A_VERIFIED_INTELLIGENCE_STORE_FAIL: {msg}', file=sys.stderr)
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
    actual_head = (head.stdout or '').strip()
    unrelated_head = '0000000000000000000000000000000000000000'
    if unrelated_head in ALLOWED_HEADS:
        return 'unrelated HEAD must never be permitted by the C1A HEAD allowlist'
    if ALLOWED_HEADS != frozenset({ORIGINAL_IMPL_BASELINE, COMMITTED_C1A_HEAD}):
        return 'C1A HEAD allowlist must remain the original C1A implementation baseline and committed C1A HEAD'
    if actual_head not in ALLOWED_HEADS:
        return (
            f'HEAD must be the original C1A implementation baseline {ORIGINAL_IMPL_BASELINE} '
            f'or the committed C1A HEAD {COMMITTED_C1A_HEAD}, got {actual_head}'
        )

    tracked_changed = _git_paths(
        'diff',
        '--name-only',
        '--diff-filter=ACDMRTUXB',
        BASELINE_COMMIT,
        '--',
    )
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'C1A_CHANGED_FILE_SCOPE '
        f'baseline={BASELINE_COMMIT} '
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

    for required in MUST_REMAIN_UNCHANGED:
        if required in actual_source_scope:
            return f'{required} must remain unchanged from baseline'
    for required in MUST_REMAIN_UNCHANGED_EXCEPT_C1B_SUCCESSOR:
        if required in actual_source_scope and actual_head == ORIGINAL_IMPL_BASELINE:
            return f'{required} must remain unchanged from the C1A implementation baseline'
        if required in actual_source_scope and required not in ALLOWED_SUCCESSOR_C1B:
            return f'{required} is not in the bounded C1B successor allowlist'

    unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
    if unexpected:
        return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    if actual_head == COMMITTED_C1A_HEAD:
        store_vs_c1a = subprocess.run(
            ['git', 'diff', '--name-only', COMMITTED_C1A_HEAD, '--', 'backend/news/verified_intelligence_store.py'],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (store_vs_c1a.stdout or '').strip():
            return 'C1A store source must remain unchanged from the committed C1A HEAD'

    if 'backend/news/verified_intelligence_store.py' not in actual_source_scope:
        return 'missing new production file backend/news/verified_intelligence_store.py'
    if 'backend/config/build_info.py' not in tracked_changed:
        return 'backend/config/build_info.py must change for the 52R-C1A build bump'

    print('C1A_CHANGED_FILE_SCOPE_OK')
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
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-C1B'),
    }:
        return _fail(
            f'build must be exact 52R-C1A / AstraEdge 52R-C1A or successor '
            f'52R-C1B / AstraEdge 52R-C1B, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )

    module_path = PROJECT_ROOT / 'backend/news/verified_intelligence_store.py'
    if not module_path.is_file():
        return _fail('missing backend/news/verified_intelligence_store.py')
    src = module_path.read_text(encoding='utf-8')
    for needle in (
        'INTELLIGENCE_SCHEMA_VERSION',
        'verified_news_intelligence_store.json',
        'verified_news_intelligence_store.lock',
        'get_verified_intelligence_store_health',
        'build_verified_intelligence_record',
        'upsert_verified_intelligence_record',
        'find_verified_intelligence_for_event',
        'find_recent_verified_intelligence',
        'version_conflict',
        'PRIMARY_SOURCE_VERIFIED',
        'BOARD_MEETING_INTIMATION',
        'INVESTOR_PRESENTATION',
        'PRESS_RELEASE',
        'PARSED_CANONICAL_HEADLINE',
        'classification_only',
        'UPSERT_ALLOWED_INPUT_KEYS',
        'upsert payload has unsupported fields',
    ):
        if needle not in src:
            return _fail(f'C1A store missing {needle!r}')
    if '52R-A1' in src and 'INTELLIGENCE_SCHEMA_VERSION = "52R-A1"' in src:
        return _fail('C1A must not reuse discovery schema version 52R-A1')
    imported = _imported_names(src)
    for mod in NETWORK_MODULES:
        if mod in imported:
            return _fail(f'C1A imports network module {mod!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b', src, re.M):
            return _fail(f'C1A import line mentions {mod!r}')
    for api in DISCOVERY_MUTATION:
        if api in src:
            return _fail(f'C1A must not reference discovery mutation API {api}')
    if 'rss_discovery_adapter' in src:
        return _fail('C1A must not import the A2 adapter')
    print('C1A_ZERO_HTTP_STORE_OK')
    print('C1A_NO_DISCOVERY_MUTATION_OK')

    caller_hits = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        rel = _rel(path)
        if rel == 'backend/news/verified_intelligence_store.py':
            continue
        text = path.read_text(encoding='utf-8')
        if 'upsert_verified_intelligence_record' in text or 'verified_intelligence_store' in text:
            caller_hits.append(rel)
    authorized_callers = set()
    if BUILD_STAGE == '52R-C1B':
        authorized_callers = {'backend/news/verified_intelligence_classifier.py'}
    unexpected_callers = [hit for hit in caller_hits if hit not in authorized_callers]
    if unexpected_callers:
        return _fail(f'C1A production callers exist: {unexpected_callers}')
    if BUILD_STAGE == '52R-C1A' and caller_hits:
        return _fail(f'C1A production callers exist: {caller_hits}')
    print('C1A_DORMANT_PRODUCTION_OK')

    b2_validator = (
        PROJECT_ROOT / 'scripts' / 'validate_automatic_primary_verification_52r_b2.py'
    ).read_text(encoding='utf-8')
    original_b2_head = '2aaae59ccf5680b305b2f64be169eb84726de9b2'
    successor_b2_head = 'e6565b0988184ca3473b54a2a19818da9a7b2667'
    if 'ALLOWED_HEADS' not in b2_validator:
        return _fail('B2 validator must keep an explicit ALLOWED_HEADS allowlist')
    if f"BASELINE_COMMIT = '{original_b2_head}'" not in b2_validator:
        return _fail('B2 validator must retain original BASELINE_COMMIT')
    if successor_b2_head not in b2_validator:
        return _fail('B2 validator must accept the committed B2 successor HEAD')
    if COMMITTED_C1A_HEAD not in b2_validator:
        return _fail('B2 validator must accept the committed C1A HEAD')
    if 'unrelated HEAD must never be permitted' not in b2_validator:
        return _fail('B2 validator must reject an unrelated HEAD')
    print('C1A_REPAIR1_HISTORICAL_B2_HEAD_CONTRACT_OK')

    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52R-C1A validator must remain strictly read-only')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_verified_intelligence_store_52r_c1a.py')],
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
        return _fail('focused 52R-C1A verified intelligence store test failed')
    missing = [m for m in REQUIRED_MARKERS if m not in out]
    if missing:
        return _fail(f'missing required markers: {missing}')

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

    print('ASTRAEDGE_PHASE_52R_C1A_VERIFIED_INTELLIGENCE_STORE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
