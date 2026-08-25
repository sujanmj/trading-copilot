#!/usr/bin/env python3
"""Validator — AstraEdge 52R-A2 RSS discovery adapter (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_COMMIT = '78adeaad71fc1a59952185c114fdac05541f5c92'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py',
    PROJECT_ROOT / 'scripts' / 'test_rss_discovery_adapter_52r_a2.py',
    PROJECT_ROOT / 'scripts' / 'validate_rss_discovery_adapter_52r_a2.py',
)

REQUIRED_MARKERS = (
    'RSS_DISCOVERY_BUILD_OK',
    'RSS_DISCOVERY_MAPPING_OK',
    'RSS_DISCOVERY_EXCHANGE_DISCOVERY_ONLY_OK',
    'RSS_DISCOVERY_SOURCE_KIND_BOUNDARY_OK',
    'RSS_DISCOVERY_REQUIRED_FIELDS_FAIL_CLOSED_OK',
    'RSS_DISCOVERY_SIGHTING_IDEMPOTENCE_OK',
    'RSS_DISCOVERY_SOURCE_IDENTITY_TRUTH_OK',
    'RSS_DISCOVERY_MULTI_SOURCE_TRUTH_OK',
    'RSS_DISCOVERY_NO_PRIMARY_PROMOTION_OK',
    'RSS_DISCOVERY_EMPTY_BATCH_NOOP_OK',
    'RSS_DISCOVERY_UNHEALTHY_STORE_IMMUTABLE_OK',
    'RSS_DISCOVERY_BATCH_LOCK_OK',
    'RSS_DISCOVERY_BATCH_LOCK_CROSS_PROCESS_OK',
    'BATCH_LOCK_CRASH_RELEASE_OK',
    'BATCH_LOCK_LIVE_OWNER_NOT_EVICTED_OK',
    'RSS_DISCOVERY_SINGLE_WRITER_ROUTE_OK',
    'RSS_DISCOVERY_NO_NETWORK_AI_TRADING_OK',
    'RSS_DISCOVERY_CONTENT_BOUNDARY_OK',
    'RSS_DISCOVERY_PUBLIC_BOUNDARY_OK',
    'RSS_DISCOVERY_REPO_DATA_SAFE_OK',
    'RSS_DISCOVERY_RAW_EXCEPTION_ESCAPE_COUNT=0',
)

FORBIDDEN_IMPORT_NEEDLES = (
    'requests',
    'httpx',
    'aiohttp',
    'feedparser',
    'BeautifulSoup',
    'selenium',
    'playwright',
    'SmartConnect',
    'smartapi',
    'yfinance',
    'openai',
    'anthropic',
    'google.generativeai',
    'groq',
    'stock_scanner',
    'trade_card_engine',
    'opening_rally_radar',
    'weekly_signal_capture',
    'capture_news_signal',
    'learning_engine',
    'outcome_tracker',
)

INTENDED_PRODUCTION = {
    'backend/news/rss_discovery_adapter.py',
    'backend/collectors/news_provider_registry.py',
    'backend/collectors/live_news_tracker.py',
    'backend/config/build_info.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
    'scripts/test_broker_discovery_foundation_52r_a1.py',
    'scripts/validate_broker_discovery_foundation_52r_a1.py',
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_A2_TESTS = {
    'scripts/test_rss_discovery_adapter_52r_a2.py',
    'scripts/validate_rss_discovery_adapter_52r_a2.py',
}

ALLOWED_SUCCESSOR_B1 = {
    'backend/news/primary_source_verifier.py',
    'scripts/test_primary_source_verifier_52r_b1.py',
    'scripts/validate_primary_source_verifier_52r_b1.py',
}

ALLOWED_SUCCESSOR_B2N = {
    'scripts/test_nse_authoritative_rss_ingest_52r_b2n.py',
    'scripts/validate_nse_authoritative_rss_ingest_52r_b2n.py',
}

ALLOWED_SUCCESSOR_B2 = {
    'backend/news/automatic_primary_verification.py',
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
    'phase52r_a2_architecture_audit.txt',
    'phase52r_a2_validation.txt',
    'phase52r_a2_diff.txt',
}

ALLOWED_SUCCESSOR_D = {
    'backend/news/news_pipeline_reliability.py',
    'backend/collectors/live_news_tracker.py',
    'backend/config/build_info.py',
    'scripts/test_news_pipeline_reliability_52r_d.py',
    'scripts/validate_news_pipeline_reliability_52r_d.py',
}

ALLOWED_SUCCESSOR_D2P = {
    'backend/news/source_time_provenance.py',
    'backend/collectors/news_provider_registry.py',
    'backend/news/rss_discovery_adapter.py',
    'backend/config/build_info.py',
    'scripts/test_source_time_provenance_52r_d2p.py',
    'scripts/validate_source_time_provenance_52r_d2p.py',
}

ALLOWED_SUCCESSOR_D2 = {
    'backend/news/event_freshness_projection.py',
    'backend/config/build_info.py',
    'scripts/test_event_age_freshness_52r_d2.py',
    'scripts/validate_event_age_freshness_52r_d2.py',
}

ALLOWED_CHANGED_SOURCE = (
    INTENDED_PRODUCTION | ALLOWED_HISTORICAL_REGRESSIONS | ALLOWED_A2_TESTS | ALLOWED_SUCCESSOR_B1 | ALLOWED_SUCCESSOR_B2N | ALLOWED_SUCCESSOR_B2 | ALLOWED_SUCCESSOR_C1A | ALLOWED_SUCCESSOR_C1B | ALLOWED_SUCCESSOR_D | ALLOWED_SUCCESSOR_D2P | ALLOWED_SUCCESSOR_D2
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_A2_RSS_DISCOVERY_FAIL: {msg}', file=sys.stderr)
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
        'A2_CHANGED_FILE_SCOPE '
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

    unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
    if unexpected:
        return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    print('RSS_DISCOVERY_CHANGED_FILE_SCOPE_OK')
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

    allowed = {
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-C1B'),
        ('52R-D', 'AstraEdge 52R-D'),
        ('52R-D2P', 'AstraEdge 52R-D2P'),
        ('52R-D2', 'AstraEdge 52R-D2'),
    }
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'build must be exact 52R-A2 / AstraEdge 52R-A2 or successor '
            f'52R-B1 / AstraEdge 52R-B1 or 52R-B2N / AstraEdge 52R-B2N or '
            f'52R-B2 / AstraEdge 52R-B2 or 52R-C1A / AstraEdge 52R-C1A or '
            f'52R-C1B / AstraEdge 52R-C1B or 52R-D / AstraEdge 52R-D, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )

    adapter = PROJECT_ROOT / 'backend/news/rss_discovery_adapter.py'
    if not adapter.is_file():
        return _fail('missing backend/news/rss_discovery_adapter.py')
    src = adapter.read_text(encoding='utf-8')
    for needle in (
        'article_to_sighting_payload',
        'ingest_registry_articles',
        'upsert_sighting',
        'DISCOVERY_ONLY',
        'unsupported_source_kind',
        'lock_contended',
        'store_unhealthy',
        'nse_rss',
        'bse_rss',
        'NEWS_PUBLISHER',
        'EXCHANGE',
    ):
        if needle not in src:
            return _fail(f'adapter missing {needle!r}')
    if 'mark_primary_source_verified' in src:
        return _fail('adapter must not call mark_primary_source_verified')
    if 'import requests' in src or 'from requests' in src:
        return _fail('adapter must not import requests')

    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split('.')[0])
                imported.add(node.module)
    for needle in FORBIDDEN_IMPORT_NEEDLES:
        if needle in imported:
            return _fail(f'adapter imports forbidden module {needle!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(needle)}\b', src, re.M):
            return _fail(f'adapter import line mentions {needle!r}')

    tracker_src = (PROJECT_ROOT / 'backend/collectors/live_news_tracker.py').read_text(encoding='utf-8')
    if 'ingest_discovery=True' not in tracker_src:
        return _fail('live_news_tracker must opt in')
    registry_src = (PROJECT_ROOT / 'backend/collectors/news_provider_registry.py').read_text(encoding='utf-8')
    if 'ingest_discovery: bool = False' not in registry_src:
        return _fail('registry ingest_discovery must default False')

    backend_hits = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        if 'ingest_discovery=True' in text or 'rss_discovery_adapter' in text:
            backend_hits.append(_rel(path))
    allowed_hits = {
        'backend/news/rss_discovery_adapter.py',
        'backend/collectors/news_provider_registry.py',
        'backend/collectors/live_news_tracker.py',
        # B1 reuses the A2 discovery-store lock primitive; it must not ingest.
        'backend/news/primary_source_verifier.py',
    }
    unexpected = [p for p in backend_hits if p not in allowed_hits]
    if unexpected:
        return _fail(f'unexpected production integration files: {unexpected}')
    for extra in (
        'backend/collectors/news_aggregator.py',
        'backend/my_feed/news_refresh.py',
        'backend/telegram/premarket_scheduler.py',
        'backend/collectors/nse_announcements.py',
        'backend/intelligence/stock_catalyst_radar.py',
        'backend/trading/trade_card_engine.py',
    ):
        p = PROJECT_ROOT / extra
        if not p.is_file():
            continue
        text = p.read_text(encoding='utf-8')
        if 'ingest_discovery=True' in text or 'rss_discovery_adapter' in text:
            return _fail(f'{extra} must not integrate A2 discovery')

    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52R-A2 validator must remain strictly read-only')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_rss_discovery_adapter_52r_a2.py')],
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
        return _fail('focused 52R-A2 RSS discovery test failed')
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

    print('ASTRAEDGE_PHASE_52R_A2_RSS_DISCOVERY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
