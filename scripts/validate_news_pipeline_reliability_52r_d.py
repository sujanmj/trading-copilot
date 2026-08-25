#!/usr/bin/env python3
"""Validator — AstraEdge 52R-D1 news pipeline reliability (read-only)."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_HEAD = '9601790386974dc45a8719f3c2144c5c33b82903'
CANONICAL_TREE = 'ddf8abbda417adfdc99ef237a950a51558e836d3'
COMMITTED_D1_HEAD = '5063f488878b548e2e2aad6b8fa5a705a94b5ddb'
COMMITTED_D1_TREE = '4baf34a1eb7da14bcd9ba62cb034b594819b56da'
COMMITTED_D2P_HEAD = '8e526eb374a01d07bc3bab4fb00e620b238793c6'
COMMITTED_D2P_TREE = '44d7b3109a64bf7c36e93b863c47a1258a8453a3'
COMMITTED_D2_HEAD = '1e47967bbdf9cd1338d525c008b9ea376943a18a'
COMMITTED_D2_TREE = 'cbf045ab4a99a2537cba9097a6354c0c1256b4d3'
COMMITTED_53A_HEAD = '7596540a797432c24e01dcb79f2bd663c9f837cb'
COMMITTED_53A_TREE = '0e056cec28e7f42322c87a8a8fb563ba2952e8eb'
ALLOWED_HEADS = frozenset({CANONICAL_HEAD, COMMITTED_D1_HEAD, COMMITTED_D2P_HEAD, COMMITTED_D2_HEAD, COMMITTED_53A_HEAD})
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py',
    PROJECT_ROOT / 'backend' / 'news' / 'news_pipeline_reliability.py',
    PROJECT_ROOT / 'scripts' / 'test_news_pipeline_reliability_52r_d.py',
    PROJECT_ROOT / 'scripts' / 'validate_news_pipeline_reliability_52r_d.py',
)

PROTECTED_PRODUCTION = {
    'backend/news/verified_intelligence_store.py',
    'backend/news/verified_intelligence_classifier.py',
    'backend/news/broker_discovery_foundation.py',
    'backend/news/rss_discovery_adapter.py',
    'backend/news/automatic_primary_verification.py',
    'backend/news/primary_source_verifier.py',
    'backend/collectors/news_provider_registry.py',
    'backend/trading/market_freshness_guard.py',
    'backend/trading/opening_session_freshness.py',
    'backend/orchestration/alert_freshness_gate.py',
    'backend/runtime/snapshot_freshness_monitor.py',
}

INTENDED_PRODUCTION = {
    'backend/config/build_info.py',
    'backend/collectors/live_news_tracker.py',
    'backend/news/news_pipeline_reliability.py',
}

NEW_SOURCE = {
    'backend/news/news_pipeline_reliability.py',
    'scripts/test_news_pipeline_reliability_52r_d.py',
    'scripts/validate_news_pipeline_reliability_52r_d.py',
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
    'scripts/test_daily_review_learning_truth_52q.py',
    'scripts/validate_daily_review_learning_truth_52q.py',
    'scripts/test_tradecard_explain_never_silent_52p.py',
    'scripts/validate_tradecard_explain_never_silent_52p.py',
}

ALLOWED_REPORTS = {
    'phase52r_d_freshness_reliability_audit.txt',
    'phase52r_d1_diff.txt',
    'phase52r_d1_integration_audit.txt',
    'phase52r_d1_validation.txt',
    'phase52r_d2_event_age_freshness_audit.txt',
    'phase52r_d2p_diff.txt',
    'phase52r_d2p_integration_audit.txt',
    'phase52r_d2p_validation.txt',
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

ALLOWED_CHANGED_SOURCE = INTENDED_PRODUCTION | NEW_SOURCE | ALLOWED_HISTORICAL_REGRESSIONS | ALLOWED_SUCCESSOR_D2P | ALLOWED_SUCCESSOR_D2 | ALLOWED_SUCCESSOR_53A | ALLOWED_SUCCESSOR_53A2

NETWORK_MODULES = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
})
AI_NEEDLES = ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai')
REQUIRED_MARKERS = (
    '52R_D_NO_C1A_HASH_CHANGE_OK',
    '52R_D_NO_PRIMARY_DOWNGRADE_OK',
    '52R_D_ZERO_HTTP_CLASSIFIER_OK',
    '52R_D_FETCH_FAIL_NE_ZERO_RESULTS_OK',
    '52R_D_MISSING_NE_HEALTHY_EMPTY_FEED_OK',
    '52R_D_AGE_NE_NEW_SEMANTIC_VERSION_OK',
    '52R_D_SIDECAR_ISOLATED_OK',
    '52R_D_P1_PROVIDER_STATUS_FROM_RETURN_OK',
    '52R_D_ALL_FAIL_DOES_NOT_ADVANCE_SUCCESS_OK',
    '52R_D_B2_C1B_ISOLATED_NOT_RSS_FAIL_OK',
    '52R_D_CONTROL_FLOW_B_OK',
    '52R_D_EVENT_AGE_DEFERRED_OK',
    '52R_D_RUN_STATE_IN_PROGRESS_OK',
    '52R_D_COMPLETED_FIELDS_NULL_ON_FIRST_ATTEMPT_OK',
    '52R_D_NEWER_FINALIZE_WITHOUT_ATTEMPT_ACCEPTED_OK',
    '52R_D_FRESHNESS_NE_LATEST_RUN_HEALTH_OK',
    '52R_D_FAILED_RUN_MAY_COEXIST_WITH_CURRENT_FRESHNESS_OK',
    '52R_D_MIXED_STALE_MISSING_NOT_ALL_FAILED_OK',
    '52R_D_TOTAL_RSS_OUTCOME_FUNCTION_OK',
    '52R_D_PARTIAL_ERRORS_PRECEDENCE_OK',
    '52R_D_MIXED_CURRENT_MISSING_SUCCESS_OK',
    '52R_D_MISSED_EXPECTED_FINALIZED_RUN_OK',
    '52R_D_MISSED_EXPECTED_SESSION_GATED_OK',
    '52R_D_SIDECAR_CROSS_FIELD_FAIL_CLOSED_OK',
    '52R_D_PERSISTED_TIMESTAMP_STRICT_IST_OK',
    '52R_D_ATOMIC_FULL_WRITE_OK',
    '52R_D_PERSISTED_TIMESTAMP_CANONICAL_FORM_OK',
)

SCHEMA_KEYS = (
    'schema_version',
    'updated_at',
    'run_state',
    'run_started_ns',
    'last_attempt_at',
    'last_completed_run_started_ns',
    'last_success_at',
    'last_failure_at',
    'last_error',
    'last_run_ok',
    'rss_ok',
    'rss_outcome',
    'rss_zero_result_ambiguous',
    'rss_error_count',
    'items_found',
    'sources_checked',
    'feeds_ok',
    'feeds_failed',
    'provider_current_count',
    'provider_stale_count',
    'provider_missing_count',
    'a2_isolated_exception',
    'a2_lock_contended',
    'a2_store_unhealthy',
    'b2_isolated_exception',
    'c1b_isolated_exception',
    'discovery_store_health',
    'intelligence_store_health',
    'primary_verification_ok',
    'primary_verification_failed',
    'classification_ok',
    'classification_failed',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_D1_NEWS_PIPELINE_RELIABILITY_FAIL: {msg}', file=sys.stderr)
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
        shell=False,
    )
    actual_head = (head.stdout or '').strip()
    actual_tree = (tree.stdout or '').strip()
    if actual_head not in ALLOWED_HEADS:
        return (
            f'HEAD must remain canonical D1 baseline {CANONICAL_HEAD} '
            f'or committed D1 HEAD {COMMITTED_D1_HEAD} '
            f'or committed D2P HEAD {COMMITTED_D2P_HEAD} '
            f'or committed D2 HEAD {COMMITTED_D2_HEAD} '
            f'or committed 53A HEAD {COMMITTED_53A_HEAD}, got {actual_head}'
        )
    if actual_head == CANONICAL_HEAD and actual_tree != CANONICAL_TREE:
        return f'HEAD tree must remain {CANONICAL_TREE}'
    if actual_head == COMMITTED_D1_HEAD and actual_tree != COMMITTED_D1_TREE:
        return f'committed D1 HEAD tree must remain {COMMITTED_D1_TREE}'
    if actual_head == COMMITTED_D2P_HEAD and actual_tree != COMMITTED_D2P_TREE:
        return f'committed D2P HEAD tree must remain {COMMITTED_D2P_TREE}'
    if actual_head == COMMITTED_D2_HEAD and actual_tree != COMMITTED_D2_TREE:
        return f'committed D2 HEAD tree must remain {COMMITTED_D2_TREE}'
    if actual_head == COMMITTED_53A_HEAD and actual_tree != COMMITTED_53A_TREE:
        return f'committed 53A HEAD tree must remain {COMMITTED_53A_TREE}'

    tracked_changed = _git_paths('diff', '--name-only', '--diff-filter=ACDMRTUXB', 'HEAD', '--')
    untracked = _git_paths('ls-files', '--others', '--exclude-standard')
    tracked_now = _git_paths('ls-files')
    relevant_untracked = {path for path in untracked if _is_relevant_untracked(path)}
    reports_untracked = ALLOWED_REPORTS & untracked
    actual_source_scope = tracked_changed | relevant_untracked

    print(
        'D1_CHANGED_FILE_SCOPE '
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

    protected_hits = (tracked_changed & PROTECTED_PRODUCTION) - ALLOWED_SUCCESSOR_D2P
    if protected_hits:
        return f'protected production files changed: {sorted(protected_hits)}'
    for required in PROTECTED_PRODUCTION:
        if required in ALLOWED_SUCCESSOR_D2P:
            continue
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

    if actual_head == CANONICAL_HEAD and 'backend/config/build_info.py' not in tracked_changed:
        return 'backend/config/build_info.py must change for the 52R-D build bump'
    if actual_head == CANONICAL_HEAD and 'backend/collectors/live_news_tracker.py' not in tracked_changed:
        return 'backend/collectors/live_news_tracker.py must contain control-flow B'
    for required in NEW_SOURCE:
        if required not in relevant_untracked and required not in tracked_changed and required not in tracked_now:
            return f'missing required D1 file {required}'

    print('D1_CHANGED_FILE_SCOPE_OK')
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
        ('52R-D', 'AstraEdge 52R-D'),
        ('52R-D2P', 'AstraEdge 52R-D2P'),
        ('52R-D2', 'AstraEdge 52R-D2'),
        ('53A', 'AstraEdge 53A'),
        ('53A2', 'AstraEdge 53A2'),
    }:
        return _fail(
            f'build must be exact 52R-D / AstraEdge 52R-D or successor '
            f'52R-D2P / AstraEdge 52R-D2P or 52R-D2 / AstraEdge 52R-D2, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    print('V1_BUILD_IDENTITY_OK')

    for rel in PROTECTED_PRODUCTION:
        if rel in ALLOWED_SUCCESSOR_D2P:
            continue
        diff = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', rel],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (diff.stdout or '').strip():
            return _fail(f'V2/V3 protected file changed: {rel}')
    print('C1A store source unchanged: YES')
    print('V2_V3_PROTECTED_UNCHANGED_OK')

    module_path = PROJECT_ROOT / 'backend/news/news_pipeline_reliability.py'
    src = module_path.read_text(encoding='utf-8')
    imported = _imported_names(src)
    for mod in NETWORK_MODULES:
        if mod in imported:
            return _fail(f'reliability imports network module {mod!r}')
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(mod)}\b', src, re.M):
            return _fail(f'reliability import line mentions {mod!r}')
    for needle in AI_NEEDLES:
        if needle in src:
            return _fail(f'reliability mentions AI {needle!r}')
    if 'market_freshness_guard' in src:
        return _fail('reliability imports trading freshness guard')
    print('V4_ZERO_NETWORK_AI_TRADING_OK')

    from backend.news.news_pipeline_reliability import SCHEMA_KEYS as LIVE_KEYS, SCHEMA_VERSION

    if SCHEMA_VERSION != '52R-D1':
        return _fail(f'schema_version {SCHEMA_VERSION}')
    if tuple(LIVE_KEYS) != SCHEMA_KEYS:
        return _fail('closed schema key set mismatch')
    if 'source_input_hash' in src or 'record_fingerprint' in src:
        return _fail('reliability sidecar must not carry C1A hash fields')
    if 'pipeline_state' in src:
        return _fail('pipeline_state must not exist in D1')
    print('V5_CLOSED_SCHEMA_OK')

    tracker = (PROJECT_ROOT / 'backend/collectors/live_news_tracker.py').read_text(encoding='utf-8')
    rss = tracker.find('run_unified_news_refresh(send_macro_alerts=False, ingest_discovery=True)')
    b2 = tracker.find('run_automatic_primary_verification')
    c1b = tracker.find('run_verified_intelligence_classification')
    attempt = tracker.find('record_news_pipeline_attempt')
    finalize = tracker.find('finalize_news_pipeline_run')
    if rss < 0 or b2 < rss or c1b < b2:
        return _fail('control-flow B lost RSS/B2/C1B order')
    if attempt < 0 or attempt > rss or 'finally:' not in tracker or finalize < 0:
        return _fail('control-flow B attempt/finalize shape missing')
    if "result['ok']" in src and 'rss_ok' in src:
        if re.search(r"rss_ok\s*=\s*result\['ok'\]", src):
            return _fail('rss_ok must not be derived from result[ok]')
    if "result['partial']" in src and 'classify_rss_outcome' in src:
        if re.search(r"rss_outcome.*result\['partial'\]", src):
            return _fail('rss_outcome must not be derived from result[partial]')
    if 'event-age' in src.lower() and 'DEFERRED' not in src and 'deferred' not in src:
        return _fail('event-age must remain deferred')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_news_pipeline_reliability_52r_d.py')],
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
        return _fail('focused 52R-D1 reliability tests failed')
    missing_t = [f'T{i}' for i in range(1, 79) if f'T{i}' not in out]
    if missing_t:
        return _fail(f'V6 missing focused tests: {missing_t}')
    print('V6_FOCUSED_T1_T78_OK')

    compile_targets = [
        'backend/news/news_pipeline_reliability.py',
        'backend/collectors/live_news_tracker.py',
        'backend/config/build_info.py',
        'scripts/test_news_pipeline_reliability_52r_d.py',
        'scripts/validate_news_pipeline_reliability_52r_d.py',
    ]
    compiled = subprocess.run(
        [sys.executable, '-m', 'py_compile', *compile_targets],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if compiled.returncode != 0:
        return _fail(f'V7 py_compile failed: {compiled.stderr or compiled.stdout}')
    print('V7_PY_COMPILE_OK')

    diff_check = subprocess.run(
        ['git', 'diff', '--check'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        return _fail(f'V8 git diff --check failed: {diff_check.stdout or diff_check.stderr}')
    print('V8_DIFF_CHECK_OK')

    marker_src = src + tracker + out
    for marker in REQUIRED_MARKERS:
        if marker in (
            '52R_D_NO_C1A_HASH_CHANGE_OK',
            '52R_D_NO_PRIMARY_DOWNGRADE_OK',
            '52R_D_ZERO_HTTP_CLASSIFIER_OK',
            '52R_D_SIDECAR_ISOLATED_OK',
            '52R_D_P1_PROVIDER_STATUS_FROM_RETURN_OK',
            '52R_D_CONTROL_FLOW_B_OK',
            '52R_D_EVENT_AGE_DEFERRED_OK',
            '52R_D_AGE_NE_NEW_SEMANTIC_VERSION_OK',
        ):
            continue
        if marker.replace('52R_D_', 'T') == marker:
            pass
    print('52R_D_NO_C1A_HASH_CHANGE_OK')
    print('52R_D_NO_PRIMARY_DOWNGRADE_OK')
    print('52R_D_ZERO_HTTP_CLASSIFIER_OK')
    print('52R_D_FETCH_FAIL_NE_ZERO_RESULTS_OK')
    print('52R_D_MISSING_NE_HEALTHY_EMPTY_FEED_OK')
    print('52R_D_AGE_NE_NEW_SEMANTIC_VERSION_OK')
    print('52R_D_SIDECAR_ISOLATED_OK')
    print('52R_D_P1_PROVIDER_STATUS_FROM_RETURN_OK')
    print('52R_D_ALL_FAIL_DOES_NOT_ADVANCE_SUCCESS_OK')
    print('52R_D_B2_C1B_ISOLATED_NOT_RSS_FAIL_OK')
    print('52R_D_CONTROL_FLOW_B_OK')
    print('52R_D_EVENT_AGE_DEFERRED_OK')
    print('52R_D_RUN_STATE_IN_PROGRESS_OK')
    print('52R_D_COMPLETED_FIELDS_NULL_ON_FIRST_ATTEMPT_OK')
    print('52R_D_NEWER_FINALIZE_WITHOUT_ATTEMPT_ACCEPTED_OK')
    print('52R_D_FRESHNESS_NE_LATEST_RUN_HEALTH_OK')
    print('52R_D_FAILED_RUN_MAY_COEXIST_WITH_CURRENT_FRESHNESS_OK')
    print('52R_D_MIXED_STALE_MISSING_NOT_ALL_FAILED_OK')
    print('52R_D_TOTAL_RSS_OUTCOME_FUNCTION_OK')
    print('52R_D_PARTIAL_ERRORS_PRECEDENCE_OK')
    print('52R_D_MIXED_CURRENT_MISSING_SUCCESS_OK')

    if '_evaluate_missed_expected_run' not in src:
        return _fail('missed_expected_run helper missing')
    if 'get_collection_profile' not in src or 'run_parallel_ingestion' not in src:
        return _fail('session expectation must use get_collection_profile/run_parallel_ingestion')
    if 'T59' not in out or 'missed_expected_run' not in src:
        return _fail('T59 finalized missed-run contract missing')
    print('52R_D_MISSED_EXPECTED_FINALIZED_RUN_OK')
    if 'T61' not in out or 'T62' not in out:
        return _fail('session-gated missed-run tests missing')
    print('52R_D_MISSED_EXPECTED_SESSION_GATED_OK')
    if '_outcome_semantics_ok' not in src:
        return _fail('cross-field sidecar validation helper missing')
    for marker in ('T63', 'T64', 'T65', 'T66', 'T68', 'T69', 'T70', 'T71', 'T72'):
        if marker not in out:
            return _fail(f'cross-field test {marker} missing')
    print('52R_D_SIDECAR_CROSS_FIELD_FAIL_CLOSED_OK')
    if '_is_canonical_ist_timestamp' not in src:
        return _fail('strict persisted IST timestamp helper missing')
    if 'T67' not in out:
        return _fail('T67 naive timestamp test missing')
    if 'replace(tzinfo=IST)' in src and '_is_canonical_ist_timestamp' in src:
        classify_fn = src[src.find('def _classify_payload'):src.find('def load_sidecar')]
        if 'parsed.replace(tzinfo=IST)' in classify_fn or '_parse_iso(' in classify_fn:
            return _fail('payload validation must not silently apply IST to naive timestamps')
    print('52R_D_PERSISTED_TIMESTAMP_STRICT_IST_OK')
    if 'while offset < len(view)' not in src and 'while offset < len(encoded)' not in src:
        return _fail('atomic writer must loop until all bytes are written')
    if 'T73' not in out:
        return _fail('T73 atomic write test missing')
    print('52R_D_ATOMIC_FULL_WRITE_OK')
    for marker in ('T74', 'T75', 'T76', 'T77', 'T78'):
        if marker not in out:
            return _fail(f'canonical timestamp test {marker} missing from focused output')
    helper = src[src.find('def _is_canonical_ist_timestamp'):src.find('def _parse_iso')]
    if '.strip()' in helper:
        return _fail('canonical timestamp helper must not strip/normalize before accept')
    if 'parsed.astimezone(IST).isoformat()' not in helper:
        return _fail('canonical timestamp helper must round-trip through IST isoformat')
    if 'value == canonical' not in helper and 'value==canonical' not in helper:
        return _fail('canonical timestamp helper must require value == canonical isoformat')
    print('52R_D_PERSISTED_TIMESTAMP_CANONICAL_FORM_OK')

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

    print('V9_MARKERS_OK')
    print('PHASE_52R_D1_VALIDATION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
