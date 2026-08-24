#!/usr/bin/env python3
"""Validator — AstraEdge 52R-C1B verified intelligence classifier (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_COMMIT = '21c32dcf5a3a2280ccf90536e2ec238aa54b02e5'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py',
    PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_classifier.py',
    PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_store.py',
    PROJECT_ROOT / 'scripts' / 'test_verified_intelligence_classifier_52r_c1b.py',
    PROJECT_ROOT / 'scripts' / 'validate_verified_intelligence_classifier_52r_c1b.py',
)

REQUIRED_MARKERS = (
    'C1B_BUILD_PAIR_OK',
    'C1B_UNICODE_SEPARATOR_CONTRACT_OK',
    'C1B_PRIMARY_ONLY_OK',
    'C1B_BOARD_MEETING_CLASSIFICATION_OK',
    'C1B_INVESTOR_PRESENTATION_CLASSIFICATION_OK',
    'C1B_PRESS_RELEASE_CLASSIFICATION_OK',
    'C1B_OTHER_FALLBACK_OK',
    'C1B_NO_FUZZY_MATCHING_OK',
    'C1B_VERSION_CONTRACT_OK',
    'C1B_PRECHECK_IDEMPOTENT_SKIP_OK',
    'C1B_PRECHECK_VERSION_CONFLICT_NOT_HIDDEN_OK',
    'C1B_BOUNDED_SCAN_OK',
    'C1B_BOUNDED_ATTEMPTS_OK',
    'C1B_RECENT_BACKFILL_OK',
    'C1B_MALFORMED_STORE_IMMUTABLE_OK',
    'C1B_ZERO_HTTP_CLASSIFIER',
    'C1B_ZERO_AI_CANONICAL_CLASSIFICATION',
    'C1B_NO_TRADING_BEHAVIOR_CHANGE',
    'C1B_AFTER_B2_CALLER_OK',
    'C1B_NO_NESTED_LOCKS_OK',
    'VERIFIED_INTELLIGENCE_CLASSIFIER_52R_C1B_PASS',
)

PROTECTED_PRODUCTION = {
    'backend/news/verified_intelligence_store.py',
    'backend/news/broker_discovery_foundation.py',
    'backend/news/rss_discovery_adapter.py',
    'backend/news/primary_source_verifier.py',
    'backend/news/automatic_primary_verification.py',
    'backend/collectors/news_provider_registry.py',
}

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/collectors/live_news_tracker.py',
}

NEW_UNTRACKED_SOURCE = {
    'backend/news/verified_intelligence_classifier.py',
    'scripts/test_verified_intelligence_classifier_52r_c1b.py',
    'scripts/validate_verified_intelligence_classifier_52r_c1b.py',
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
    'scripts/test_verified_intelligence_store_52r_c1a.py',
    'scripts/validate_verified_intelligence_store_52r_c1a.py',
}

ALLOWED_REPORTS = {
    'phase52r_c1b_integration_audit.txt',
    'phase52r_c1b_validation.txt',
    'phase52r_c1b_diff.txt',
}

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | ALLOWED_HISTORICAL_REGRESSIONS | NEW_UNTRACKED_SOURCE

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
DISCOVERY_MUTATION = (
    'upsert_sighting',
    'mark_primary_source_verified',
    'run_automatic_primary_verification',
    'verify_linked_primary_sighting',
    'attach_sighting_to_event',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_C1B_VERIFIED_INTELLIGENCE_CLASSIFIER_FAIL: {msg}', file=sys.stderr)
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
    if (head.stdout or '').strip() != BASELINE_COMMIT:
        return f'HEAD must remain canonical baseline {BASELINE_COMMIT}'

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
        'C1B_CHANGED_FILE_SCOPE '
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

    protected_hits = tracked_changed & PROTECTED_PRODUCTION
    if protected_hits:
        return f'protected production files changed: {sorted(protected_hits)}'
    for required in PROTECTED_PRODUCTION:
        diff = subprocess.run(
            ['git', 'diff', '--name-only', BASELINE_COMMIT, '--', required],
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

    if 'backend/config/build_info.py' not in tracked_changed:
        return 'backend/config/build_info.py must change for the 52R-C1B build bump'
    if 'backend/collectors/live_news_tracker.py' not in tracked_changed:
        return 'backend/collectors/live_news_tracker.py must contain the authorized C1B caller'
    for required in NEW_UNTRACKED_SOURCE:
        if required not in relevant_untracked:
            return f'missing required untracked C1B file {required}'

    print('C1B_CHANGED_FILE_SCOPE_OK')
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

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('52R-C1B', 'AstraEdge 52R-C1B'):
        return _fail(
            f'build must be exact 52R-C1B / AstraEdge 52R-C1B, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )

    module_path = PROJECT_ROOT / 'backend/news/verified_intelligence_classifier.py'
    if not module_path.is_file():
        return _fail('missing backend/news/verified_intelligence_classifier.py')
    src = module_path.read_text(encoding='utf-8')
    for needle in (
        'EVENT_SCAN_LIMIT = 50',
        'MAX_CLASSIFICATION_ATTEMPTS = 20',
        "DERIVATION_VERSION = '52R-C1B'",
        "TAXONOMY_VERSION = '52R-C1A'",
        "FACT_PARSER_VERSION = 'classification_only'",
        'classify_verified_intelligence_headline',
        'run_verified_intelligence_classification',
        'BOARD_MEETING_INTIMATION',
        'INVESTOR_PRESENTATION',
        'PRESS_RELEASE',
        'PARSED_CANONICAL_HEADLINE',
        'find_recent_events',
        'build_verified_intelligence_record',
        'upsert_verified_intelligence_record',
        'find_verified_intelligence_for_event',
        'source_input_hash',
        'record_fingerprint',
        'version_conflict',
    ):
        if needle not in src:
            return _fail(f'C1B classifier missing {needle!r}')

    from backend.news.verified_intelligence_classifier import HEADLINE_SEPARATOR

    if HEADLINE_SEPARATOR != ' \u2014 ':
        return _fail(f'HEADLINE_SEPARATOR must be space-emdash-space, got {HEADLINE_SEPARATOR!r}')
    if ord(HEADLINE_SEPARATOR.strip()) != 0x2014:
        return _fail(
            f'HEADLINE_SEPARATOR strip codepoint must be U+2014, got {ord(HEADLINE_SEPARATOR.strip()):#x}'
        )
    expected_assign = "HEADLINE_SEPARATOR = ' \u2014 '"
    if expected_assign not in src:
        return _fail('classifier source missing exact U+2014 HEADLINE_SEPARATOR assignment')
    mojibake = '\u00e2\u20ac\u201d'
    for rel in (
        'backend/news/verified_intelligence_classifier.py',
        'scripts/test_verified_intelligence_classifier_52r_c1b.py',
        'scripts/validate_verified_intelligence_classifier_52r_c1b.py',
    ):
        text = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        if mojibake in text:
            return _fail(f'{rel} contains U+00E2 U+20AC U+201D mojibake')
    print('C1B_UNICODE_SEPARATOR_VALIDATOR_OK')
    imported = _imported_names(src)
    for mod in NETWORK_MODULES:
        if mod in imported:
            return _fail(f'C1B imports network module {mod!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b', src, re.M):
            return _fail(f'C1B import line mentions {mod!r}')
    for api in DISCOVERY_MUTATION:
        if api in src:
            return _fail(f'C1B must not reference discovery mutation API {api}')
    if 'rss_discovery_adapter' in src:
        return _fail('C1B must not import the A2 adapter')
    if 'primary_source_verifier' in src:
        return _fail('C1B must not import B1')
    if 'discovery_lock_path' in src or '_BatchLock' in src:
        return _fail('C1B must not take the discovery write lock')
    print('C1B_ZERO_HTTP_VALIDATOR_OK')
    print('C1B_NO_DISCOVERY_MUTATION_VALIDATOR_OK')

    tracker_src = (PROJECT_ROOT / 'backend/collectors/live_news_tracker.py').read_text(encoding='utf-8')
    ingest_idx = tracker_src.find('ingest_discovery=True')
    b2_idx = tracker_src.find('run_automatic_primary_verification')
    c1b_idx = tracker_src.find('run_verified_intelligence_classification')
    if ingest_idx < 0 or b2_idx < ingest_idx or c1b_idx < 0 or c1b_idx < b2_idx:
        return _fail('C1B caller must run after B2 in live_news_tracker')
    if tracker_src.count('run_verified_intelligence_classification') != 2:
        return _fail('live_news_tracker must contain exactly one authorized C1B integration')
    if 'verified_intelligence_store' in tracker_src:
        return _fail('live_news_tracker must not import the C1A store directly')

    caller_hits = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        rel = _rel(path)
        if rel == 'backend/news/verified_intelligence_classifier.py':
            continue
        text = path.read_text(encoding='utf-8')
        if 'run_verified_intelligence_classification' in text:
            caller_hits.append(rel)
    if caller_hits != ['backend/collectors/live_news_tracker.py']:
        return _fail(f'unexpected C1B production callers: {caller_hits}')
    print('C1B_SINGLE_PRODUCTION_OWNER_OK')

    store_diff = subprocess.run(
        ['git', 'diff', '--name-only', BASELINE_COMMIT, '--', 'backend/news/verified_intelligence_store.py'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if (store_diff.stdout or '').strip():
        return _fail('C1A store source must remain unchanged')
    print('C1B_C1A_STORE_UNCHANGED_OK')
    print('C1B_C1A_STORE_GIT_UNCHANGED_OK')

    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52R-C1B validator must remain strictly read-only')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_verified_intelligence_classifier_52r_c1b.py')],
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
        return _fail('focused 52R-C1B verified intelligence classifier test failed')
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

    print('ASTRAEDGE_PHASE_52R_C1B_VERIFIED_INTELLIGENCE_CLASSIFIER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
