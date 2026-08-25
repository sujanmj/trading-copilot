#!/usr/bin/env python3
"""Validator — AstraEdge 52R-B2N NSE authoritative RSS ingest (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_COMMIT = '1e2be1b41f8b5e8d7c66c38548c227b7457aeb52'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py',
    PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py',
    PROJECT_ROOT / 'scripts' / 'test_nse_authoritative_rss_ingest_52r_b2n.py',
    PROJECT_ROOT / 'scripts' / 'validate_nse_authoritative_rss_ingest_52r_b2n.py',
)

REQUIRED_MARKERS = (
    'NSE_AUTHORITATIVE_RSS_CONFIG_OK',
    'BSE_PRIMARY_BOUNDARY_UNCHANGED_OK',
    'NSE_ANNOUNCEMENT_SUBJECT_IDENTITY_OK',
    'NSE_SAME_DAY_DISTINCT_FILINGS_OK',
    'NSE_EXACT_DUPLICATE_IDEMPOTENT_OK',
    'NSE_MISSING_SUBJECT_DISCOVERY_SKIPPED_OK',
    'NSE_B1_ELIGIBLE_URL_PRESERVED_OK',
    'NSE_DEBT_PATH_STILL_INELIGIBLE_OK',
    'NSE_RSS_NO_ITEM_FOLLOW_HTTP_OK',
    'NSE_FULL_SUMMARY_FAIL_CLOSED_TERMINAL_OK',
    'NSE_RSS_TO_A2_IDENTITY_CONTRACT_OK',
    'B2N_PRIMARY_PROMOTION_DORMANT_OK',
    'NSE_AUTHORITATIVE_RSS_INGEST_52R_B2N_PASS',
)

NSE_ANNOUNCEMENTS_XML = 'https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml'
NSE_DIRECTORY_HTML = 'https://www.nseindia.com/rss-feed'
BSE_NOTICES_XML = 'https://www.bseindia.com/data/xml/notices.xml'

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/collectors/news_provider_registry.py',
    'backend/news/rss_discovery_adapter.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
    'scripts/test_broker_discovery_foundation_52r_a1.py',
    'scripts/validate_broker_discovery_foundation_52r_a1.py',
    'scripts/test_rss_discovery_adapter_52r_a2.py',
    'scripts/validate_rss_discovery_adapter_52r_a2.py',
    'scripts/test_primary_source_verifier_52r_b1.py',
    'scripts/validate_primary_source_verifier_52r_b1.py',
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_B2N_TESTS = {
    'scripts/test_nse_authoritative_rss_ingest_52r_b2n.py',
    'scripts/validate_nse_authoritative_rss_ingest_52r_b2n.py',
}

ALLOWED_SUCCESSOR_B2 = {
    'backend/news/automatic_primary_verification.py',
    'backend/collectors/live_news_tracker.py',
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
    'phase52r_b2_architecture_audit.txt',
    'phase52r_b2_source_contract_probe.txt',
    'phase52r_b2n_validation.txt',
    'phase52r_b2n_diff.txt',
    'phase52r_b2_validation.txt',
    'phase52r_b2_diff.txt',
    'phase52r_b_architecture_audit.txt',
    'phase52r_b1_validation.txt',
    'phase52r_b1_diff.txt',
    'phase52r_a2_architecture_audit.txt',
    'phase52r_a2_validation.txt',
    'phase52r_a2_diff.txt',
}

FORBIDDEN_PRODUCTION = {
    'backend/news/primary_source_verifier.py',
    'backend/news/broker_discovery_foundation.py',
    'backend/collectors/nse_announcements.py',
    'backend/collectors/live_news_tracker.py',
}

ALLOWED_SUCCESSOR_D = {
    'backend/news/news_pipeline_reliability.py',
    'backend/collectors/live_news_tracker.py',
    'backend/config/build_info.py',
    'scripts/test_news_pipeline_reliability_52r_d.py',
    'scripts/validate_news_pipeline_reliability_52r_d.py',
}

ALLOWED_CHANGED_SOURCE = (
    INTENDED_PRODUCTION | ALLOWED_HISTORICAL_REGRESSIONS | ALLOWED_B2N_TESTS | ALLOWED_SUCCESSOR_B2 | ALLOWED_SUCCESSOR_C1A | ALLOWED_SUCCESSOR_C1B | ALLOWED_SUCCESSOR_D
)

FORBIDDEN_IMPORT_NEEDLES = (
    'selenium',
    'playwright',
    'SmartConnect',
    'nse_announcements',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_B2N_NSE_RSS_INGEST_FAIL: {msg}', file=sys.stderr)
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


def _validate_changed_file_scope() -> str | None:
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
        'B2N_CHANGED_FILE_SCOPE '
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

    forbidden_hits = ((tracked_changed | relevant_untracked) & FORBIDDEN_PRODUCTION) - ALLOWED_SUCCESSOR_B2 - ALLOWED_SUCCESSOR_C1B - ALLOWED_SUCCESSOR_D
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
        'backend/collectors/news_provider_registry.py',
        'backend/news/rss_discovery_adapter.py',
        'scripts/test_nse_authoritative_rss_ingest_52r_b2n.py',
        'scripts/validate_nse_authoritative_rss_ingest_52r_b2n.py',
    ):
        if required not in actual_source_scope:
            return f'missing required B2N file {required}'

    print('NSE_AUTHORITATIVE_RSS_CHANGED_FILE_SCOPE_OK')
    return None


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
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-C1B'),
        ('52R-D', 'AstraEdge 52R-D'),
    }:
        return _fail(f'build must be exact 52R-B2N pair or successor 52R-B2/52R-C1A/52R-C1B/52R-D pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')

    from backend.collectors.news_provider_registry import PROVIDER_DEFS

    nse = next((p for p in PROVIDER_DEFS if p.get('source_id') == 'nse_rss'), None)
    bse = next((p for p in PROVIDER_DEFS if p.get('source_id') == 'bse_rss'), None)
    nse_feeds = [str(url) for url, _cat in ((nse or {}).get('feeds') or [])]
    bse_feeds = [str(url) for url, _cat in ((bse or {}).get('feeds') or [])]
    if nse_feeds != [NSE_ANNOUNCEMENTS_XML]:
        return _fail(f'nse_rss must use announcements XML, got {nse_feeds}')
    if NSE_DIRECTORY_HTML in nse_feeds:
        return _fail('nse_rss still points at the HTML RSS directory')
    if bse_feeds != [BSE_NOTICES_XML]:
        return _fail(f'bse_rss must remain unchanged, got {bse_feeds}')

    adapter_src = (PROJECT_ROOT / 'backend/news/rss_discovery_adapter.py').read_text(encoding='utf-8')
    for needle in (
        'extract_nse_filing_subject',
        'build_nse_discovery_headline',
        'validate_nse_discovery_headline',
        'resolve_nse_discovery_headline',
        'discovery_headline',
        'skip_missing_discovery_headline',
        'SUBJECT',
    ):
        if needle not in adapter_src:
            return _fail(f'adapter missing filing-identity primitive {needle!r}')
    if 'verify_linked_primary_sighting' in adapter_src or 'mark_primary_source_verified' in adapter_src:
        return _fail('adapter must not call B1 mutation APIs')
    if 'PRIMARY_SOURCE_VERIFIED' in adapter_src:
        return _fail('adapter must not write PRIMARY_SOURCE_VERIFIED')

    from backend.news.rss_discovery_adapter import resolve_nse_discovery_headline
    import inspect

    resolve_src = inspect.getsource(resolve_nse_discovery_headline)
    resolve_tree = ast.parse(resolve_src)
    fallback_keys = []
    helper_calls = []
    for node in ast.walk(resolve_tree):
        if isinstance(node, ast.Constant) and node.value in ('description', 'summary'):
            fallback_keys.append(node.value)
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, 'id', None) or getattr(func, 'attr', None)
            if name == 'build_nse_discovery_headline':
                helper_calls.append(name)
    if fallback_keys:
        return _fail(
            f'resolve_nse_discovery_headline must not read truncated {fallback_keys}'
        )
    if helper_calls:
        return _fail(
            'resolve_nse_discovery_headline must not rebuild identity from summary text'
        )
    if 'validate_nse_discovery_headline' not in resolve_src:
        return _fail('resolve_nse_discovery_headline must validate the explicit registry field')

    parseable = 'Corporate announcement |SUBJECT: Press Release'
    company = 'Example Industries Limited'
    if resolve_nse_discovery_headline({
        'title': company,
        'discovery_headline': None,
        'description': parseable,
        'summary': parseable,
    }) is not None:
        return _fail('explicit None discovery_headline must not fall back to truncated description')
    if resolve_nse_discovery_headline({
        'title': company,
        'description': parseable,
        'summary': parseable,
    }) is not None:
        return _fail('missing discovery_headline must not fall back to truncated description')
    print('NSE_EXPLICIT_DISCOVERY_HEADLINE_TERMINAL_OK')

    registry_src = (PROJECT_ROOT / 'backend/collectors/news_provider_registry.py').read_text(encoding='utf-8')
    if NSE_ANNOUNCEMENTS_XML not in registry_src:
        return _fail('registry source missing official announcements XML URL')
    if 'verify_linked_primary_sighting' in registry_src or 'mark_primary_source_verified' in registry_src:
        return _fail('registry must not call B1 mutation APIs')
    if '/api/corporate-announcements' in registry_src:
        return _fail('registry must not add hidden NSE API usage')
    if 'selenium' in registry_src.casefold() or 'playwright' in registry_src.casefold():
        return _fail('registry must not add browser automation')
    imported = _imported_names(registry_src)
    if 'nse_announcements' in imported:
        return _fail('registry must not import nse_announcements')

    verifier = PROJECT_ROOT / 'backend/news/primary_source_verifier.py'
    foundation = PROJECT_ROOT / 'backend/news/broker_discovery_foundation.py'
    waf = PROJECT_ROOT / 'backend/collectors/nse_announcements.py'
    if not verifier.is_file() or not foundation.is_file() or not waf.is_file():
        return _fail('B1 verifier, foundation, or legacy NSE collector missing')

    backend_hits = []
    allowed_callers = {'backend/news/automatic_primary_verification.py'}
    b2_module = PROJECT_ROOT / 'backend/news/automatic_primary_verification.py'
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        if path.resolve() == verifier.resolve():
            continue
        text = path.read_text(encoding='utf-8')
        if 'verify_linked_primary_sighting' in text:
            backend_hits.append(_rel(path))
    unexpected_hits = [h for h in backend_hits if h not in allowed_callers]
    if unexpected_hits:
        return _fail(f'unexpected production callers of B1 verifier: {unexpected_hits}')

    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52R-B2N validator must remain strictly read-only')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_nse_authoritative_rss_ingest_52r_b2n.py')],
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
        return _fail('focused 52R-B2N NSE RSS ingest test failed')
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

    print('ASTRAEDGE_PHASE_52R_B2N_NSE_RSS_INGEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
