#!/usr/bin/env python3
"""Validator — AstraEdge 52R-B2 automatic governed PRIMARY verification (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_COMMIT = '2aaae59ccf5680b305b2f64be169eb84726de9b2'
CANONICAL_HEAD = 'e6565b0988184ca3473b54a2a19818da9a7b2667'
C1A_HEAD = '21c32dcf5a3a2280ccf90536e2ec238aa54b02e5'
ALLOWED_HEADS = frozenset({BASELINE_COMMIT, CANONICAL_HEAD, C1A_HEAD})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'news' / 'automatic_primary_verification.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py',
    PROJECT_ROOT / 'scripts' / 'test_automatic_primary_verification_52r_b2.py',
    PROJECT_ROOT / 'scripts' / 'validate_automatic_primary_verification_52r_b2.py',
)

REQUIRED_MARKERS = (
    'B2_NSE_CORPORATE_PRIMARY_OK',
    'B2_NSE_XBRL_PRIMARY_OK',
    'B2_DEBT_PATH_FAIL_CLOSED_OK',
    'B2_MEDIA_NEVER_PRIMARY_OK',
    'B2_AUTOVERIFICATION_IDEMPOTENT_OK',
    'B2_BOUNDED_BATCH_OK',
    'B2_FAILURE_CONTAINMENT_OK',
    'B2_ZERO_HTTP_AUTOVERIFICATION_OK',
    'B2_NO_NESTED_DISCOVERY_LOCK_OK',
    'B2_SINGLE_PRODUCTION_OWNER_OK',
    'AUTOMATIC_PRIMARY_VERIFICATION_52R_B2_PASS',
)

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/news/automatic_primary_verification.py',
    'backend/collectors/live_news_tracker.py',
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
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_B2_TESTS = {
    'scripts/test_automatic_primary_verification_52r_b2.py',
    'scripts/validate_automatic_primary_verification_52r_b2.py',
}

ALLOWED_SUCCESSOR_C1A = {
    'backend/news/verified_intelligence_store.py',
    'scripts/test_verified_intelligence_store_52r_c1a.py',
    'scripts/validate_verified_intelligence_store_52r_c1a.py',
}

ALLOWED_SUCCESSOR_C1B = {
    'backend/news/verified_intelligence_classifier.py',
    'backend/collectors/live_news_tracker.py',
    'scripts/test_verified_intelligence_classifier_52r_c1b.py',
    'scripts/validate_verified_intelligence_classifier_52r_c1b.py',
}

ALLOWED_REPORTS = {
    'phase52r_b2_validation.txt',
    'phase52r_b2_diff.txt',
    'phase52r_b2_architecture_audit.txt',
    'phase52r_b2_source_contract_probe.txt',
    'phase52r_b2n_validation.txt',
    'phase52r_b2n_diff.txt',
    'phase52r_b_architecture_audit.txt',
    'phase52r_b1_validation.txt',
    'phase52r_b1_diff.txt',
    'phase52r_c_architecture_audit.txt',
    'phase52r_c1a_validation.txt',
    'phase52r_c1a_diff.txt',
    'phase52r_c1b_integration_audit.txt',
    'phase52r_c1b_validation.txt',
    'phase52r_c1b_diff.txt',
}

FORBIDDEN_PRODUCTION = {
    'backend/news/primary_source_verifier.py',
    'backend/news/broker_discovery_foundation.py',
    'backend/news/rss_discovery_adapter.py',
    'backend/collectors/news_provider_registry.py',
    'backend/collectors/nse_announcements.py',
}

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | ALLOWED_HISTORICAL_REGRESSIONS | ALLOWED_B2_TESTS | ALLOWED_SUCCESSOR_C1A | ALLOWED_SUCCESSOR_C1B

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright',
})

B1_POLICY_TOKENS = (
    'EXCHANGE_PRIMARY_HOSTS',
    'NSE_ARCHIVE_EVENT_PREFIX',
    'BSE_EVENT_PREFIX',
    'GENERIC_EXCHANGE_PATHS',
    'classify_exchange_primary_url',
    '_b1_authoritative_event_path',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_B2_AUTOMATIC_PRIMARY_VERIFICATION_FAIL: {msg}', file=sys.stderr)
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
        return 'unrelated HEAD must never be permitted by the B2 HEAD allowlist'
    if ALLOWED_HEADS != frozenset({BASELINE_COMMIT, CANONICAL_HEAD, C1A_HEAD}):
        return 'B2 HEAD allowlist must remain exactly the original B2 baseline, committed B2 successor, and committed C1A HEAD'
    if len(ALLOWED_HEADS) != 3:
        return 'B2 HEAD allowlist must remain a bounded three-commit set'
    if actual_head not in ALLOWED_HEADS:
        return (
            f'HEAD must be the original B2 implementation baseline {BASELINE_COMMIT}, '
            f'the committed B2 successor {CANONICAL_HEAD}, '
            f'or the committed C1A HEAD {C1A_HEAD}, got {actual_head}'
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
        'B2_CHANGED_FILE_SCOPE '
        f'baseline={BASELINE_COMMIT} '
        f'tracked={sorted(tracked_changed)} '
        f'untracked_relevant={sorted(relevant_untracked)} '
        f'reports_untracked={sorted(reports_untracked)}'
    )

    reports_tracked = ALLOWED_REPORTS & tracked_now
    if reports_tracked:
        return f'review reports must remain untracked: {sorted(reports_tracked)}'

    data_changes = {
        path for path in (tracked_changed | untracked)
        if path == 'data' or path.startswith('data/')
    }
    if data_changes:
        return f'data/ changes are never allowed: {sorted(data_changes)}'

    forbidden_hits = (tracked_changed | relevant_untracked) & FORBIDDEN_PRODUCTION
    if forbidden_hits:
        return f'forbidden production files changed: {sorted(forbidden_hits)}'

    trading_hits = {
        path for path in (tracked_changed | relevant_untracked)
        if path.startswith('backend/trading/') or path.startswith('backend/ai/')
    }
    if trading_hits:
        return f'trading/AI production files changed: {sorted(trading_hits)}'

    unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
    if unexpected:
        return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    for required in (
        'backend/config/build_info.py',
        'backend/news/automatic_primary_verification.py',
        'backend/collectors/live_news_tracker.py',
        'scripts/test_automatic_primary_verification_52r_b2.py',
        'scripts/validate_automatic_primary_verification_52r_b2.py',
    ):
        if required not in actual_source_scope:
            return f'missing required B2 file {required}'

    print('B2_CHANGED_FILE_SCOPE_OK')
    return None


def main() -> int:
    before = {str(p): _file_digest(p) for p in WATCHED_PATHS}

    try:
        scope_error = _validate_changed_file_scope()
    except RuntimeError as exc:
        return _fail(f'Git changed-file scope collection failed: {exc}')
    if scope_error:
        return _fail(scope_error)

    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-C1B'),
    }:
        return _fail(f'build must be exact 52R-B2 pair or successor 52R-C1A/52R-C1B pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')

    b2_path = PROJECT_ROOT / 'backend/news/automatic_primary_verification.py'
    b2_src = b2_path.read_text(encoding='utf-8')
    imported = _imported_names(b2_src)
    for needle in (
        'verify_linked_primary_sighting',
        'find_recent_events',
        'list_event_sightings',
        'EVENT_SCAN_LIMIT',
        'MAX_VERIFICATION_ATTEMPTS',
        'SOURCE_KIND_EXCHANGE',
    ):
        if needle not in b2_src:
            return _fail(f'B2 orchestration missing {needle!r}')
    if 'EVENT_SCAN_LIMIT = 50' not in b2_src or 'MAX_VERIFICATION_ATTEMPTS = 20' not in b2_src:
        return _fail('B2 candidate bounds must remain 50 scan / 20 attempts')
    if '_BatchLock' in b2_src or 'discovery_lock_path' in b2_src:
        return _fail('B2 must not wrap B1 in an outer shared discovery lock')
    for token in B1_POLICY_TOKENS:
        if token in b2_src:
            return _fail(f'B2 must not duplicate B1 policy token {token!r}')
    if '/corporate/' in b2_src or '/xml-data/corpfiling/' in b2_src or '/content/debt/' in b2_src:
        return _fail('B2 must not hard-code exchange document path families')
    for mod in NETWORK_MODULES:
        if mod in imported:
            return _fail(f'B2 orchestration imports network module {mod!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b', b2_src, re.M):
            return _fail(f'B2 import line mentions {mod!r}')
    if 'selenium' in b2_src.casefold() or 'playwright' in b2_src.casefold():
        return _fail('B2 must not add browser automation')
    if '/api/corporate-announcements' in b2_src:
        return _fail('B2 must not add hidden NSE API usage')
    if 'mark_primary_source_verified' in b2_src:
        return _fail('B2 must mutate PRIMARY only through B1 verify_linked_primary_sighting')
    print('B2_ZERO_HTTP_ORCHESTRATION_OK')
    print('B2_NO_DUPLICATE_B1_POLICY_OK')

    verifier = PROJECT_ROOT / 'backend/news/primary_source_verifier.py'
    proc = subprocess.run(
        ['git', 'diff', '--name-only', BASELINE_COMMIT, '--', 'backend/news/primary_source_verifier.py'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if (proc.stdout or '').strip():
        return _fail('B1 production policy file must remain unchanged')
    print('B1_POLICY_UNCHANGED_OK')

    tracker_src = (PROJECT_ROOT / 'backend/collectors/live_news_tracker.py').read_text(encoding='utf-8')
    registry_src = (PROJECT_ROOT / 'backend/collectors/news_provider_registry.py').read_text(encoding='utf-8')
    if 'run_automatic_primary_verification' not in tracker_src:
        return _fail('live_news_tracker must own B2 activation')
    if tracker_src.find('ingest_discovery=True') > tracker_src.find('run_automatic_primary_verification'):
        return _fail('B2 must run after discovery ingest in live_news_tracker')
    if 'run_automatic_primary_verification' in registry_src:
        return _fail('unified refresh must not activate B2')
    if 'verify_linked_primary_sighting' in tracker_src:
        return _fail('live_news_tracker must not call B1 directly')

    owner_hits = []
    verifier_hits = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        rel = _rel(path)
        text = path.read_text(encoding='utf-8')
        if rel != 'backend/news/automatic_primary_verification.py' and 'run_automatic_primary_verification' in text:
            owner_hits.append(rel)
        if rel not in {
            'backend/news/primary_source_verifier.py',
            'backend/news/automatic_primary_verification.py',
        } and ('verify_linked_primary_sighting' in text or 'from backend.news.primary_source_verifier import' in text):
            verifier_hits.append(rel)
    if owner_hits != ['backend/collectors/live_news_tracker.py']:
        return _fail(f'unexpected B2 production owners: {owner_hits}')
    if verifier_hits:
        return _fail(f'unexpected B1 verifier production callers: {verifier_hits}')
    print('B2_SINGLE_PRODUCTION_OWNER_OK')

    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52R-B2 validator must remain strictly read-only')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_automatic_primary_verification_52r_b2.py')],
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
        return _fail('focused 52R-B2 automatic PRIMARY verification test failed')
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

    print('ASTRAEDGE_PHASE_52R_B2_AUTOMATIC_PRIMARY_VERIFICATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
