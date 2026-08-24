#!/usr/bin/env python3
"""Validator — AstraEdge 52R-B1 governed primary source verifier (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_COMMIT = '7005bc11a744eb4cbc1676ad043e9193eed4ab81'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'news' / 'primary_source_verifier.py',
    PROJECT_ROOT / 'scripts' / 'test_primary_source_verifier_52r_b1.py',
    PROJECT_ROOT / 'scripts' / 'validate_primary_source_verifier_52r_b1.py',
)

REQUIRED_MARKERS = (
    'PRIMARY_EXCHANGE_PROMOTION_OK',
    'PRIMARY_PUBLISHER_REJECTED_OK',
    'SECONDARY_MULTI_SOURCE_NOT_PRIMARY_OK',
    'PRIMARY_HOST_POLICY_OK',
    'PRIMARY_GENERIC_FEED_REJECTED_OK',
    'PRIMARY_EVENT_SPECIFIC_PATH_POLICY_OK',
    'PRIMARY_EVENT_PATH_TRAVERSAL_REJECTED_OK',
    'PRIMARY_EVENT_LINKAGE_OK',
    'PRIMARY_HEADLINE_IDENTITY_OK',
    'PRIMARY_DATE_IDENTITY_OK',
    'PRIMARY_REJECTED_TERMINAL_OK',
    'PRIMARY_IDEMPOTENCE_OK',
    'PRIMARY_CANONICAL_URL_IDEMPOTENCE_OK',
    'PRIMARY_CONFLICT_REFUSED_OK',
    'PRIMARY_UNHEALTHY_STORE_IMMUTABLE_OK',
    'PRIMARY_VERIFIER_SHARED_STORE_LOCK_OK',
    'PRIMARY_VERIFIER_RAW_EXCEPTION_ESCAPE_COUNT=0',
    'PRIMARY_VERIFIER_NO_NETWORK_AI_TRADING_OK',
    'PRIMARY_VERIFIER_NO_NSE_WAF_PATH_OK',
    'PRIMARY_VERIFIER_DORMANT_PRODUCTION_OK',
    'PRIMARY_VERIFIER_NO_TRADING_COUPLING_OK',
    'PRIMARY_VERIFIER_REPO_DATA_SAFE_OK',
    'PRIMARY_SOURCE_VERIFIER_52R_B1_PASS',
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
    'stock_catalyst_radar',
    'trade_card_engine',
    'opening_rally_radar',
    'weekly_signal_capture',
    'capture_news_signal',
    'learning_engine',
    'outcome_tracker',
    'nse_announcements',
    'ai_router',
)

INTENDED_PRODUCTION = {
    'backend/news/primary_source_verifier.py',
    'backend/config/build_info.py',
}

ALLOWED_HISTORICAL_REGRESSIONS = {
    'scripts/test_broker_discovery_foundation_52r_a1.py',
    'scripts/validate_broker_discovery_foundation_52r_a1.py',
    'scripts/test_rss_discovery_adapter_52r_a2.py',
    'scripts/validate_rss_discovery_adapter_52r_a2.py',
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_B1_TESTS = {
    'scripts/test_primary_source_verifier_52r_b1.py',
    'scripts/validate_primary_source_verifier_52r_b1.py',
}

ALLOWED_REPORTS = {
    'phase52r_b_architecture_audit.txt',
    'phase52r_b1_validation.txt',
    'phase52r_b1_diff.txt',
    'phase52r_a2_architecture_audit.txt',
    'phase52r_a2_validation.txt',
    'phase52r_a2_diff.txt',
}

FORBIDDEN_PRODUCTION = {
    'backend/collectors/nse_announcements.py',
    'backend/collectors/govt_tracker.py',
    'backend/collectors/news_aggregator.py',
    'backend/collectors/live_news_tracker.py',
    'backend/collectors/news_provider_registry.py',
    'backend/intelligence/stock_catalyst_radar.py',
    'backend/learning_engine.py',
    'backend/outcome_tracker.py',
}

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | ALLOWED_HISTORICAL_REGRESSIONS | ALLOWED_B1_TESTS


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_B1_PRIMARY_VERIFIER_FAIL: {msg}', file=sys.stderr)
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
        'B1_CHANGED_FILE_SCOPE '
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
    for prefix in ('backend/trading/',):
        trading_hits = {
            path for path in (tracked_changed | relevant_untracked)
            if path.startswith(prefix)
        }
        # Historical 52P/52Q scripts may mention trading; production trading/ must not change.
        if trading_hits:
            return f'trading production files changed: {sorted(trading_hits)}'

    unexpected = actual_source_scope - ALLOWED_CHANGED_SOURCE
    if unexpected:
        return f'unexpected changed source/test/validator files: {sorted(unexpected)}'

    if 'backend/news/primary_source_verifier.py' not in actual_source_scope:
        return 'missing new production file backend/news/primary_source_verifier.py'
    if 'backend/config/build_info.py' not in tracked_changed:
        return 'backend/config/build_info.py must change for the 52R-B1 build bump'
    if 'backend/news/broker_discovery_foundation.py' in actual_source_scope:
        return 'broker_discovery_foundation.py must not change in B1'
    if 'backend/news/rss_discovery_adapter.py' in actual_source_scope:
        return 'rss_discovery_adapter.py must not change unless a lock test requires it'

    print('PRIMARY_VERIFIER_CHANGED_FILE_SCOPE_OK')
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

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('52R-B1', 'AstraEdge 52R-B1'):
        return _fail(f'build must be exact 52R-B1 pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')

    verifier = PROJECT_ROOT / 'backend/news/primary_source_verifier.py'
    if not verifier.is_file():
        return _fail('missing backend/news/primary_source_verifier.py')
    src = verifier.read_text(encoding='utf-8')
    for needle in (
        'verify_linked_primary_sighting',
        'mark_primary_source_verified',
        'EXCHANGE_PRIMARY',
        'discovery_lock_path',
        '_BatchLock',
        'nseindia.com',
        'bseindia.com',
        '/rss-feed',
        '/data/xml/notices.xml',
        '/corporate/',
        '/xml-data/corpfiling/',
        'event_path_not_authoritative',
        '_b1_authoritative_event_path',
        'NSE_ARCHIVE_EVENT_PREFIX',
        'BSE_EVENT_PREFIX',
        '_remainder_is_safe_event_resource',
        '%2e',
        '%2f',
        '%5c',
        'normalize_url',
        'lock_contended',
        'primary_conflict',
    ):
        if needle not in src:
            return _fail(f'verifier missing {needle!r}')
    if 'nse_announcements' in src:
        return _fail('verifier must not import or mention nse_announcements')
    if re.search(r"\['verification_status'\]\s*=", src):
        return _fail('verifier must not directly assign verification_status')
    if '_save_store' in src:
        return _fail('verifier must not implement or call _save_store')
    if 'atomic_write_json' in src:
        return _fail('verifier must not write the JSON store directly')
    imported = _imported_names(src)
    if 'normalize_url' not in imported:
        return _fail('verifier must import foundation normalize_url')
    ok_idx = src.find("result['ok'] = True")
    path_idx = src.find('_b1_authoritative_event_path')
    if ok_idx < 0 or path_idx < 0 or path_idx > ok_idx:
        return _fail('PRIMARY eligibility must require positive event-path policy before ok=True')
    if '_remainder_is_safe_event_resource' not in src:
        return _fail('missing explicit structural/traversal rejection policy')
    if "'..'" not in src and '".."' not in src:
        return _fail('traversal policy must reject raw .. segments')
    if '%2e' not in src.casefold() or '%2f' not in src.casefold() or '%5c' not in src.casefold():
        return _fail('traversal policy must reject percent-encoded structural escapes')
    for needle in FORBIDDEN_IMPORT_NEEDLES:
        if needle in imported:
            return _fail(f'verifier imports forbidden module {needle!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(needle)}\b', src, re.M):
            return _fail(f'verifier import line mentions {needle!r}')
    if 'rss_discovery_adapter' not in src or '_BatchLock' not in src:
        return _fail('verifier must reuse the existing A2 discovery store lock')

    backend_hits = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        if path.resolve() == verifier.resolve():
            continue
        text = path.read_text(encoding='utf-8')
        if 'primary_source_verifier' in text or 'verify_linked_primary_sighting' in text:
            backend_hits.append(_rel(path))
    if backend_hits:
        return _fail(f'unexpected production callers: {backend_hits}')
    print('PRODUCTION_CALLERS none')
    print('PRIMARY_VERIFIER_DORMANT_PRODUCTION_OK')

    for extra in (
        'backend/collectors/live_news_tracker.py',
        'backend/collectors/news_provider_registry.py',
        'backend/collectors/nse_announcements.py',
        'backend/intelligence/stock_catalyst_radar.py',
        'backend/trading/trade_card_engine.py',
        'backend/trading/opening_rally_radar.py',
        'backend/trading/weekly_signal_capture.py',
        'backend/learning_engine.py',
        'backend/outcome_tracker.py',
        'backend/ai_router.py',
        'backend/analyzers/stock_scanner.py',
    ):
        p = PROJECT_ROOT / extra
        if not p.is_file():
            continue
        text = p.read_text(encoding='utf-8')
        if 'primary_source_verifier' in text or 'verify_linked_primary_sighting' in text:
            return _fail(f'{extra} must not integrate B1 verifier')
    print('PRIMARY_VERIFIER_NO_TRADING_COUPLING_OK')
    print('PRIMARY_VERIFIER_NO_NSE_WAF_PATH_OK')

    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52R-B1 validator must remain strictly read-only')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_primary_source_verifier_52r_b1.py')],
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
        return _fail('focused 52R-B1 primary verifier test failed')
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
    print('PRIMARY_VERIFIER_REPO_DATA_SAFE_OK')

    print('ASTRAEDGE_PHASE_52R_B1_PRIMARY_VERIFIER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
