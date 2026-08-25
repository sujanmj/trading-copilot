#!/usr/bin/env python3
"""AstraEdge 52R-D1 — news pipeline reliability focused tests (T1-T78, isolated)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')
PASS_MARKERS: list[str] = []
MARKET_NOW = datetime(2099, 7, 27, 10, 15, 0, tzinfo=IST)  # Tuesday market
WEEKEND_NOW = datetime(2099, 7, 25, 12, 0, 0, tzinfo=IST)  # Saturday
NIGHT_NOW = datetime(2099, 7, 27, 23, 30, 0, tzinfo=IST)
NS_A = int(MARKET_NOW.timestamp() * 1_000_000_000)
NS_B = NS_A + 1_000_000_000
NS_C = NS_A + 2_000_000_000

PROTECTED = (
    PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_store.py',
    PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_classifier.py',
    PROJECT_ROOT / 'backend' / 'news' / 'broker_discovery_foundation.py',
    PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py',
    PROJECT_ROOT / 'backend' / 'news' / 'automatic_primary_verification.py',
    PROJECT_ROOT / 'backend' / 'news' / 'primary_source_verifier.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'market_freshness_guard.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'opening_session_freshness.py',
    PROJECT_ROOT / 'backend' / 'orchestration' / 'alert_freshness_gate.py',
    PROJECT_ROOT / 'backend' / 'runtime' / 'snapshot_freshness_monitor.py',
)
MODULE_PATH = PROJECT_ROOT / 'backend' / 'news' / 'news_pipeline_reliability.py'
TRACKER_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py'
FORBIDDEN_IMPORTS = frozenset({
    'requests', 'httpx', 'aiohttp', 'urllib', 'urllib.request', 'selenium',
    'playwright', 'feedparser', 'openai', 'anthropic', 'groq',
})
DISCOVERY_MUTATION = (
    'upsert_event',
    'upsert_sighting',
    'upsert_verified_intelligence_record',
    'mark_primary_source_verified',
)


def _fail(msg: str) -> int:
    print(f'NEWS_PIPELINE_RELIABILITY_52R_D_FAIL: {msg}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'missing'


def _git_data_status() -> str:
    proc = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or '').strip()


def _snapshot_data() -> dict[str, tuple[int, int]]:
    from scripts._test_runtime_isolation import snapshot_data_tree

    return snapshot_data_tree()


def _status(sid: str, freshness: str) -> dict:
    return {
        'source_id': sid,
        'freshness_status': freshness,
        'items_found': 1 if freshness == 'CURRENT' else 0,
        'error_count': 1 if freshness == 'STALE' else 0,
    }


def _result(
    *,
    n: int,
    items: int,
    errors: list[str] | None = None,
    statuses: list[tuple[str, str]] | None = None,
    ok: bool | None = None,
    partial: bool | None = None,
    discovery: dict | None = None,
    verification: dict | None = None,
    classification: dict | None = None,
) -> dict:
    errors = list(errors or [])
    provider_status = {}
    if statuses is None:
        statuses = [('p{0}'.format(i), 'CURRENT') for i in range(n)]
    for sid, freshness in statuses:
        provider_status[sid] = _status(sid, freshness)
        if freshness == 'CURRENT' and items > 0:
            provider_status[sid]['items_found'] = max(1, items // max(1, n))
        if freshness == 'STALE':
            provider_status[sid]['error_count'] = 1
            provider_status[sid]['items_found'] = 0
    payload = {
        'ok': (ok if ok is not None else items > 0),
        'partial': (partial if partial is not None else (bool(errors) and items > 0)),
        'sources_checked': n,
        'items_found': items,
        'error_count': len(errors),
        'errors': errors,
        'provider_status': provider_status,
        'output': {'last_updated': 'must-not-be-used', 'feeds_ok': 99, 'feeds_failed': 99},
        'discovery': discovery,
        'primary_verification': verification or {'ok': True, 'failed': 0},
        'verified_intelligence': classification or {'ok': True, 'failed': 0, 'store_health': 'OK'},
    }
    return payload


def _all_current(n: int = 2, items: int = 4, errors: list[str] | None = None) -> dict:
    statuses = [(f'p{i}', 'CURRENT') for i in range(n)]
    return _result(n=n, items=items, errors=errors or [], statuses=statuses)


def _zero_missing(n: int = 2) -> dict:
    statuses = [(f'p{i}', 'MISSING') for i in range(n)]
    return _result(n=n, items=0, errors=[], statuses=statuses, ok=False, partial=False)


def _all_stale(n: int = 2, errors: list[str] | None = None) -> dict:
    statuses = [(f'p{i}', 'STALE') for i in range(n)]
    errs = errors if errors is not None else ['feed a', 'feed b']
    return _result(n=n, items=0, errors=errs, statuses=statuses, ok=False)


def _mixed_stale_missing() -> dict:
    return _result(
        n=2,
        items=0,
        errors=['stale feed'],
        statuses=[('a', 'STALE'), ('b', 'MISSING')],
        ok=False,
    )


def _current_stale_articles() -> dict:
    return _result(
        n=2,
        items=3,
        errors=['one failed'],
        statuses=[('a', 'CURRENT'), ('b', 'STALE')],
        partial=True,
    )


def _mixed_current_missing() -> dict:
    return _result(
        n=2,
        items=2,
        errors=[],
        statuses=[('a', 'CURRENT'), ('b', 'MISSING')],
        ok=True,
        partial=False,
    )


def _current_missing_errors() -> dict:
    return _result(
        n=2,
        items=2,
        errors=['subfeed'],
        statuses=[('a', 'CURRENT'), ('b', 'MISSING')],
        partial=True,
    )


@contextmanager
def _isolated():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sidecar = root / 'news_pipeline_reliability.json'
        lock = root / 'news_pipeline_reliability.lock'
        with patch.dict(
            os.environ,
            {
                'NEWS_PIPELINE_RELIABILITY_PATH': str(sidecar),
                'NEWS_PIPELINE_RELIABILITY_LOCK_PATH': str(lock),
                'NEWS_SOURCE_TIME_PROVENANCE_PATH': str(root / 'news_source_time_provenance.json'),
                'NEWS_SOURCE_TIME_PROVENANCE_LOCK_PATH': str(root / 'news_source_time_provenance.lock'),
            },
            clear=False,
        ):
            yield {
                'root': root,
                'sidecar': sidecar,
                'lock': lock,
            }


def _load(ctx: dict) -> dict:
    return json.loads(ctx['sidecar'].read_text(encoding='utf-8'))


def _bytes(ctx: dict) -> bytes:
    return ctx['sidecar'].read_bytes() if ctx['sidecar'].exists() else b''


def test_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('52R-D', 'AstraEdge 52R-D'),
        ('52R-D2P', 'AstraEdge 52R-D2P'),
        ('52R-D2', 'AstraEdge 52R-D2'),
        ('53A', 'AstraEdge 53A'),
        ('53A2', 'AstraEdge 53A2'),
    }:
        return _fail(f'expected 52R-D / AstraEdge 52R-D or successor 52R-D2P / AstraEdge 52R-D2P or 52R-D2 / AstraEdge 52R-D2, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('52R_D_BUILD_PAIR_OK')
    return 0


def test_t20_imports() -> int:
    src = MODULE_PATH.read_text(encoding='utf-8')
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
    for name in FORBIDDEN_IMPORTS:
        if name in imported:
            return _fail(f'reliability module imports {name}')
    if 'market_freshness_guard' in src or 'opening_session_freshness' in src:
        return _fail('reliability module must not import trading freshness guards')
    if 'openai' in src or 'anthropic' in src or 'ai_router' in src:
        return _fail('reliability module must not reference AI')
    for api in DISCOVERY_MUTATION:
        if api in src:
            return _fail(f'reliability module must not call {api}')
    _pass('T20')
    return 0


def test_t17_t22_static() -> int:
    src = MODULE_PATH.read_text(encoding='utf-8')
    for api in DISCOVERY_MUTATION:
        if api in src:
            return _fail(f'record path mentions {api}')
    tracker = TRACKER_PATH.read_text(encoding='utf-8')
    rss = tracker.find('run_unified_news_refresh(send_macro_alerts=False, ingest_discovery=True)')
    b2 = tracker.find('run_automatic_primary_verification')
    c1b = tracker.find('run_verified_intelligence_classification')
    attempt = tracker.find('record_news_pipeline_attempt')
    finalize = tracker.find('finalize_news_pipeline_run')
    if rss < 0 or b2 < rss or c1b < b2:
        return _fail('tracker order is not RSS then B2 then C1B')
    if attempt < 0 or attempt > rss:
        return _fail('attempt must be recorded before STEP 1')
    if 'finally:' not in tracker or finalize < 0:
        return _fail('finalize must run from finally')
    if tracker.count('run_verified_intelligence_classification') != 2:
        return _fail('C1B integration count changed')
    if 'verified_intelligence_store' in tracker:
        return _fail('tracker must not import C1A store')
    _pass('T17')
    _pass('T22')
    return 0


def test_t1_missing(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import evaluate_news_pipeline_reliability

    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['sidecar_health'] != 'MISSING':
        return _fail(f'T1 sidecar_health {ev["sidecar_health"]}')
    if ev['freshness_state'] != 'MISSING' or ev['latest_run_health'] != 'NONE':
        return _fail('T1 must not fabricate CURRENT/SUCCESS')
    if ev['rss_outcome'] is not None or ev['run_state'] is not None:
        return _fail('T1 null run fields')
    if 'COLLECTOR_NEVER_COMPLETED' not in ev['collector_state']:
        return _fail('T1 missing NEVER_COMPLETED')
    if ctx['sidecar'].exists():
        return _fail('T1 evaluate wrote sidecar')
    _pass('T1')
    return 0


def test_t25_t26_t38_first_attempt(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        record_news_pipeline_attempt,
    )

    rec = record_news_pipeline_attempt(NS_A)
    if rec.get('status') != 'WRITTEN':
        return _fail(f'T25 write status {rec}')
    data = _load(ctx)
    if data['run_state'] != 'IN_PROGRESS' or data['rss_outcome'] is not None:
        return _fail('T25 invented an RSS outcome')
    completed_keys = (
        'last_completed_run_started_ns', 'last_success_at', 'last_failure_at',
        'last_error', 'last_run_ok', 'rss_ok', 'rss_outcome',
        'rss_zero_result_ambiguous', 'rss_error_count', 'items_found',
        'sources_checked', 'feeds_ok', 'feeds_failed',
        'provider_current_count', 'provider_stale_count', 'provider_missing_count',
        'a2_isolated_exception', 'b2_isolated_exception', 'c1b_isolated_exception',
    )
    for key in completed_keys:
        if data.get(key) is not None:
            return _fail(f'T25/T38 completed field {key}={data.get(key)!r} must be null')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['freshness_state'] != 'MISSING' or ev['latest_run_health'] != 'NONE':
        return _fail('T26 fabricated CURRENT')
    if 'COLLECTOR_IN_PROGRESS' not in ev['collector_state']:
        return _fail('T26 missing IN_PROGRESS collector flag')
    _pass('T25')
    _pass('T26')
    _pass('T38')
    return 0


def _finalize(ns: int, result, exc=None):
    from backend.news.news_pipeline_reliability import (
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(ns)
    return finalize_news_pipeline_run(ns, result, step1_exception=exc)


def test_clocks_and_zero_result(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    zero = _zero_missing()
    zero['ok'] = False
    finalize_news_pipeline_run(NS_A, zero)
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_ZERO_RESULT' or data['rss_ok'] is not True:
        return _fail(f'T4 outcome {data["rss_outcome"]} rss_ok={data["rss_ok"]}')
    if data['last_success_at'] is None or data['last_failure_at'] is not None:
        return _fail('T4 clocks')
    if data['rss_zero_result_ambiguous'] is not True:
        return _fail('T4 ambiguous flag')
    if data['last_error'] != '':
        return _fail('T4 last_error')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['freshness_state'] != 'CURRENT' or ev['latest_run_health'] != 'SUCCESS':
        return _fail('T4/T42 evaluate')
    _pass('T4')
    _pass('T14')
    _pass('T42')
    _pass('T48')

    prior_success = data['last_success_at']
    record_news_pipeline_attempt(NS_B)
    finalize_news_pipeline_run(NS_B, _all_stale())
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_ALL_FAILED':
        return _fail(f'T3 outcome {data["rss_outcome"]}')
    if data['last_success_at'] != prior_success:
        return _fail('T3 last_success_at advanced')
    if data['last_failure_at'] is None or data['rss_ok'] is not False:
        return _fail('T3 failure clock')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['freshness_state'] != 'CURRENT' or ev['latest_run_health'] != 'FAILED':
        return _fail('T3/T39 freshness/health split')
    if 'COLLECTOR_LAST_FAILED' not in ev['collector_state']:
        return _fail('T39 missing LAST_FAILED')
    _pass('T3')
    _pass('T39')
    _pass('T47')
    return 0


def test_partial_and_mixed(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    success_at = _load(ctx)['last_success_at']
    record_news_pipeline_attempt(NS_B)
    finalize_news_pipeline_run(NS_B, _current_stale_articles())
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_PARTIAL' or data['rss_ok'] is not False:
        return _fail(f'T5 outcome {data["rss_outcome"]}')
    if data['last_success_at'] != success_at:
        return _fail('T5/T54 last_success_at advanced')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['latest_run_health'] != 'PARTIAL' or ev['freshness_state'] != 'CURRENT':
        return _fail('T5/T40 evaluate')
    _pass('T5')
    _pass('T40')
    _pass('T54')

    record_news_pipeline_attempt(NS_C)
    finalize_news_pipeline_run(NS_C, _mixed_stale_missing())
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_PARTIAL':
        return _fail('T49 mixed zero-item must be RSS_PARTIAL')
    if data['rss_outcome'] == 'RSS_ALL_FAILED':
        return _fail('T49 mapped mixed to ALL_FAILED')
    if data['last_success_at'] != success_at or data['last_failure_at'] is None:
        # last_failure_at may remain from T3 in earlier tests if same ctx reused;
        # this function uses a fresh ctx from caller. Failure clock must not newly
        # advance solely from mixed zero-item if it was null.
        pass
    if data['last_success_at'] != success_at:
        return _fail('T49 advanced last_success_at')
    if data['last_failure_at'] is not None:
        return _fail('T49 advanced last_failure_at')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['latest_run_health'] != 'PARTIAL':
        return _fail('T49 health')
    _pass('T49')
    return 0


def test_t50_zero_partition() -> int:
    from backend.news.news_pipeline_reliability import classify_rss_outcome

    z1 = classify_rss_outcome(result=_zero_missing())
    z2 = classify_rss_outcome(result=_all_stale())
    z3 = classify_rss_outcome(result=_mixed_stale_missing())
    z4 = classify_rss_outcome(result=_result(
        n=2, items=0, errors=[], statuses=[('a', 'CURRENT'), ('b', 'MISSING')],
    ))
    if z1['rss_outcome'] != 'RSS_ZERO_RESULT':
        return _fail('T50 Z1')
    if z2['rss_outcome'] != 'RSS_ALL_FAILED':
        return _fail('T50 Z2')
    if z3['rss_outcome'] != 'RSS_PARTIAL':
        return _fail('T50 Z3')
    if z4['rss_outcome'] != 'RSS_PARTIAL':
        return _fail('T50 Z4')
    if z3['rss_outcome'] == 'RSS_ALL_FAILED' or z4['rss_outcome'] == 'RSS_ALL_FAILED':
        return _fail('T50 mixed/inconsistent invented ALL_FAILED')
    _pass('T50')
    return 0


def test_components_and_no_providers(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    b2_fail = {'ok': False, 'error_type': 'RuntimeError', 'failed': 1}
    c1b_fail = {'ok': False, 'error_type': 'RuntimeError', 'failed': 1}
    record_news_pipeline_attempt(NS_A)
    rss = _all_current()
    rss['primary_verification'] = b2_fail
    finalize_news_pipeline_run(NS_A, rss)
    data = _load(ctx)
    if data['rss_ok'] is not True or data['rss_outcome'] != 'RSS_ALL_CURRENT':
        return _fail('T6 rss rewritten')
    if data['last_run_ok'] is not False or data['b2_isolated_exception'] is not True:
        return _fail('T6 last_run_ok')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['latest_run_health'] != 'SUCCESS_WITH_COMPONENT_FAILURE':
        return _fail(f'T6/T46 health {ev["latest_run_health"]}')
    _pass('T6')
    _pass('T46')

    record_news_pipeline_attempt(NS_B)
    rss = _all_current()
    rss['verified_intelligence'] = c1b_fail
    finalize_news_pipeline_run(NS_B, rss)
    data = _load(ctx)
    if data['rss_ok'] is not True or data['c1b_isolated_exception'] is not True:
        return _fail('T7 C1B isolation')
    _pass('T7')

    record_news_pipeline_attempt(NS_C)
    a2 = _all_current()
    a2['discovery'] = {'ok': False, 'error_type': 'OSError', 'lock_contended': False}
    finalize_news_pipeline_run(NS_C, a2)
    data = _load(ctx)
    if data['rss_ok'] is not True or data['last_run_ok'] is not False:
        return _fail('T24 A2 isolation')
    if data['a2_isolated_exception'] is not True:
        return _fail('T24 a2 flag')
    _pass('T24')

    from backend.news.news_pipeline_reliability import classify_rss_outcome

    empty = classify_rss_outcome(result={'sources_checked': 0, 'items_found': 0, 'error_count': 0, 'errors': [], 'provider_status': {}})
    if empty['rss_outcome'] != 'RSS_NO_PROVIDERS' or empty['last_error'] != 'no_enabled_providers':
        return _fail('T23 classify')
    record_news_pipeline_attempt(NS_C + 1)
    prior_success = _load(ctx)['last_success_at']
    finalize_news_pipeline_run(
        NS_C + 1,
        {'sources_checked': 0, 'items_found': 0, 'error_count': 0, 'errors': [], 'provider_status': {}},
    )
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_NO_PROVIDERS':
        return _fail('T23 outcome')
    if data['last_success_at'] != prior_success:
        return _fail('T23 success clock')
    if data['last_error'] != 'no_enabled_providers':
        return _fail('T23 last_error')
    _pass('T23')
    return 0


def test_t8_t9_tracker(ctx: dict) -> int:
    from backend.collectors.live_news_tracker import run_live_news_tracker

    with patch(
        'backend.collectors.live_news_tracker.run_unified_news_refresh',
        side_effect=RuntimeError('step1 boom'),
    ):
        raised = False
        try:
            run_live_news_tracker()
        except RuntimeError as exc:
            raised = str(exc) == 'step1 boom'
        if not raised:
            return _fail('T8 STEP1 exception must propagate')
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_STEP1_EXCEPTION':
        return _fail(f'T8 outcome {data.get("rss_outcome")}')
    if data['last_success_at'] is not None:
        return _fail('T8 advanced success')
    if data['last_failure_at'] is None:
        return _fail('T8 missing failure clock')
    _pass('T8')

    ctx['sidecar'].unlink(missing_ok=True)
    good = _all_current()
    with patch(
        'backend.collectors.live_news_tracker.run_unified_news_refresh',
        return_value=good,
    ), patch(
        'backend.news.automatic_primary_verification.run_automatic_primary_verification',
        return_value={'ok': True, 'failed': 0, 'attempted': 0, 'verified': 0},
    ), patch(
        'backend.news.verified_intelligence_classifier.run_verified_intelligence_classification',
        return_value={'ok': True, 'failed': 0, 'attempted': 0},
    ), patch(
        'backend.news.news_pipeline_reliability.record_news_pipeline_attempt',
        side_effect=RuntimeError('attempt failed'),
    ), patch(
        'backend.news.news_pipeline_reliability.finalize_news_pipeline_run',
        side_effect=RuntimeError('finalize failed'),
    ):
        out = run_live_news_tracker()
    if out.get('items_found') != good['items_found']:
        return _fail('T9 STEP1 result altered')
    _pass('T9')
    return 0


def test_corrupt_lock_ordering(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        _ReliabilityLock,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
        reliability_lock_path,
    )

    ctx['sidecar'].write_text('{', encoding='utf-8')
    before = _bytes(ctx)
    rec = record_news_pipeline_attempt(NS_A)
    fin = finalize_news_pipeline_run(NS_A, _all_current())
    if rec.get('status') != 'MALFORMED' or fin.get('status') != 'MALFORMED':
        return _fail('T10/T34 must skip MALFORMED')
    if _bytes(ctx) != before:
        return _fail('T10/T34 overwrote malformed bytes')
    _pass('T10')
    _pass('T34')

    ctx['sidecar'].unlink()
    ctx['sidecar'].write_bytes(b'\xff\xfe')
    before = _bytes(ctx)
    rec = record_news_pipeline_attempt(NS_A)
    if rec.get('status') != 'UNREADABLE':
        return _fail(f'T10 unread {rec}')
    if _bytes(ctx) != before:
        return _fail('T10 overwrote unreadable bytes')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    before = _bytes(ctx)
    lock = _ReliabilityLock(reliability_lock_path())
    if not lock.try_acquire():
        return _fail('T11 could not acquire test lock')
    try:
        rec = record_news_pipeline_attempt(NS_B)
        fin = finalize_news_pipeline_run(NS_B, _all_current())
    finally:
        lock.release()
    if rec.get('status') != 'LOCK_CONTENDED' or fin.get('status') != 'LOCK_CONTENDED':
        return _fail(f'T11 status rec={rec} fin={fin}')
    if _bytes(ctx) != before:
        return _fail('T11 mutated under contention')
    _pass('T11')

    finalize_news_pipeline_run(NS_A, _all_current())
    newer = _load(ctx)
    before = _bytes(ctx)
    skipped = finalize_news_pipeline_run(NS_A - 1, _all_stale())
    if skipped.get('status') != 'SKIPPED':
        return _fail('T12/T31 older finalize')
    if _bytes(ctx) != before or _load(ctx)['run_started_ns'] != newer['run_started_ns']:
        return _fail('T12 older overwrite')
    _pass('T12')
    _pass('T31')
    return 0


def test_attempt_finalize_machine(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    fin = finalize_news_pipeline_run(NS_A, _all_current())
    if fin.get('status') != 'WRITTEN':
        return _fail('T32 finalize IN_PROGRESS')
    if _load(ctx)['run_state'] != 'FINALIZED':
        return _fail('T32 not finalized')
    _pass('T32')
    _pass('T41')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['freshness_state'] != 'CURRENT' or ev['latest_run_health'] != 'SUCCESS':
        return _fail('T41 evaluate')

    prior = _load(ctx)
    record_news_pipeline_attempt(NS_B)
    data = _load(ctx)
    if data['run_state'] != 'IN_PROGRESS' or data['run_started_ns'] != NS_B:
        return _fail('T27 attempt identity')
    if data['last_completed_run_started_ns'] != NS_A or data['last_success_at'] != prior['last_success_at']:
        return _fail('T27 lost completed identity')
    if data['rss_outcome'] != 'RSS_ALL_CURRENT':
        return _fail('T27 completed outcome rewritten')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['latest_attempt']['in_progress'] is not True:
        return _fail('T28 latest_attempt')
    if ev['last_completed']['run_started_ns'] != NS_A:
        return _fail('T28 last_completed identity')
    if ev['freshness_state'] != 'CURRENT' or ev['latest_run_health'] != 'SUCCESS':
        return _fail('T28/T44 split')
    if 'COLLECTOR_IN_PROGRESS' not in ev['collector_state']:
        return _fail('T44 collector')
    _pass('T27')
    _pass('T28')
    _pass('T44')

    before = _bytes(ctx)
    failure_before = data['last_failure_at']
    ev = evaluate_news_pipeline_reliability(
        now=MARKET_NOW + timedelta(hours=6),
        orchestrator_state={'last_scheduler_tick_unix': (MARKET_NOW + timedelta(hours=6)).timestamp()},
    )
    if 'IN_PROGRESS_STALE' not in ev['collector_state']:
        return _fail('T29/T30 IN_PROGRESS_STALE')
    if 'COLLECTOR_FAILED' in ev['collector_state'] and ev['rss_outcome'] == 'RSS_ALL_CURRENT':
        return _fail('T30 abandoned IN_PROGRESS became COLLECTOR_FAILED')
    if _bytes(ctx) != before or _load(ctx)['last_failure_at'] != failure_before:
        return _fail('T29/T30 mutated sidecar or synthesized last_failure_at')
    _pass('T29')
    _pass('T30')

    # newer finalize without matching attempt (lost attempt write)
    prior_success = _load(ctx)['last_success_at']
    fin = finalize_news_pipeline_run(NS_C, _all_stale())
    if fin.get('status') != 'WRITTEN':
        return _fail(f'T33 status {fin}')
    data = _load(ctx)
    if data['run_started_ns'] != NS_C or data['rss_outcome'] != 'RSS_ALL_FAILED':
        return _fail('T33 did not accept newer finalize')
    if data['last_success_at'] != prior_success:
        return _fail('T33 cleared historical success')
    _pass('T33')

    before = _bytes(ctx)
    dup = finalize_news_pipeline_run(NS_C, _all_stale())
    if dup.get('status') != 'IDEMPOTENT':
        return _fail(f'T35 {dup}')
    if _bytes(ctx) != before:
        return _fail('T35 wrote on duplicate')
    _pass('T35')
    return 0


def test_overlap(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        _ReliabilityLock,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
        reliability_lock_path,
    )

    record_news_pipeline_attempt(NS_A)
    record_news_pipeline_attempt(NS_B)
    skipped = finalize_news_pipeline_run(NS_A, _all_current())
    if skipped.get('status') != 'SKIPPED':
        return _fail('T36 A finalize should skip')
    finalize_news_pipeline_run(NS_B, _all_stale())
    if _load(ctx)['run_started_ns'] != NS_B or _load(ctx)['rss_outcome'] != 'RSS_ALL_FAILED':
        return _fail('T36 remaining truth is not B')
    _pass('T36')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    lock = _ReliabilityLock(reliability_lock_path())
    lock.try_acquire()
    try:
        contended = record_news_pipeline_attempt(NS_B)
    finally:
        lock.release()
    if contended.get('status') != 'LOCK_CONTENDED':
        return _fail('T37 B attempt should contend')
    finalize_news_pipeline_run(NS_A, _all_current())
    finalize_news_pipeline_run(NS_B, _mixed_current_missing())
    data = _load(ctx)
    if data['run_started_ns'] != NS_B or data['rss_outcome'] != 'RSS_MIXED_CURRENT_MISSING':
        return _fail(f'T37 remaining truth {data.get("rss_outcome")}')
    _pass('T37')
    return 0


def test_p1_and_refuse(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        SCHEMA_KEYS,
        _classify_payload,
        _persist,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    result = _all_current(n=3, items=5)
    result['output']['last_updated'] = '2099-01-01T00:00:00+05:30'
    finalize_news_pipeline_run(NS_A, result)
    data = _load(ctx)
    if data['provider_current_count'] != 3 or data['sources_checked'] != 3:
        return _fail('T13 counts not from provider_status')
    if data['last_success_at'] == result['output']['last_updated']:
        return _fail('T13 used last_updated')
    if not ctx['sidecar'].is_file():
        return _fail('T13 sidecar missing')
    # news_feed.json must not be required
    if (ctx['root'] / 'news_feed.json').exists():
        return _fail('T13 wrote news_feed')
    _pass('T13')

    bad = {key: None for key in SCHEMA_KEYS}
    bad['schema_version'] = '52R-D1'
    refused = _persist(bad)
    if refused.get('status') != 'REFUSED':
        return _fail(f'T21 persist {refused}')
    if _classify_payload({'nope': 1}) != 'MALFORMED':
        return _fail('T21 classify extra keys')
    _pass('T21')
    return 0


def test_scheduler_and_idle(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    stale_tick = MARKET_NOW.timestamp() - 200
    ev = evaluate_news_pipeline_reliability(
        now=MARKET_NOW,
        orchestrator_state={'last_scheduler_tick_unix': stale_tick},
    )
    if ev['scheduler_state'] != 'SCHEDULER_STALE':
        return _fail(f'T18 scheduler {ev["scheduler_state"]}')
    if ev['freshness_state'] != 'CURRENT':
        return _fail('T45 scheduler must not hide CURRENT freshness')
    if ev['latest_run_health'] != 'SUCCESS':
        return _fail('T18 health')
    _pass('T18')
    _pass('T45')

    ctx['sidecar'].unlink()
    old_ns = int((WEEKEND_NOW - timedelta(hours=10)).timestamp() * 1_000_000_000)
    record_news_pipeline_attempt(old_ns)
    finalize_news_pipeline_run(old_ns, _all_current())
    ev = evaluate_news_pipeline_reliability(now=WEEKEND_NOW, orchestrator_state={})
    if ev['freshness_state'] != 'IDLE':
        return _fail(f'T19 expected IDLE got {ev["freshness_state"]}')
    _pass('T19')
    return 0


def test_t2_recent_market(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['freshness_state'] != 'CURRENT':
        return _fail('T2 freshness')
    if 'IN_PROGRESS_STALE' in ev['collector_state']:
        return _fail('T2 collector stale')
    _pass('T2')
    return 0


def test_t43_no_history_failed(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_stale())
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['freshness_state'] != 'MISSING' or ev['latest_run_health'] != 'FAILED':
        return _fail(f'T43 {ev["freshness_state"]} {ev["latest_run_health"]}')
    _pass('T43')
    return 0


def test_repair5_positive(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        classify_rss_outcome,
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    payload = _all_current(errors=['subfeed'])
    payload['partial'] = True
    finalize_news_pipeline_run(NS_A, payload)
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_PARTIAL_ERRORS':
        return _fail(f'T51/T55 outcome {data["rss_outcome"]}')
    if data['rss_ok'] is not False:
        return _fail('T51 rss_ok')
    if data['last_success_at'] is None:
        return _fail('T51 success clock')
    if not str(data['last_error']).startswith('rss_partial_errors:'):
        return _fail(f'T51/T58 last_error {data["last_error"]}')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['latest_run_health'] != 'PARTIAL':
        return _fail('T51 health')
    _pass('T51')
    _pass('T55')

    record_news_pipeline_attempt(NS_B)
    mixed = _mixed_current_missing()
    mixed['partial'] = False
    failure_before = _load(ctx)['last_failure_at']
    finalize_news_pipeline_run(NS_B, mixed)
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_MIXED_CURRENT_MISSING':
        return _fail(f'T52 outcome {data["rss_outcome"]}')
    if data['rss_ok'] is not True or data['last_error'] != '':
        return _fail('T52/T58 mixed last_error')
    if data['last_failure_at'] != failure_before:
        return _fail('T52 failure clock')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['latest_run_health'] != 'SUCCESS':
        return _fail('T52 health')
    _pass('T52')
    _pass('T58')

    classified = classify_rss_outcome(result=_current_missing_errors())
    if classified['rss_outcome'] != 'RSS_PARTIAL_ERRORS':
        return _fail('T53 partial flag overrode branch')
    _pass('T53')

    mixed_b2 = _mixed_current_missing()
    mixed_b2['primary_verification'] = {'ok': False, 'error_type': 'RuntimeError', 'failed': 1}
    record_news_pipeline_attempt(NS_C)
    finalize_news_pipeline_run(NS_C, mixed_b2)
    data = _load(ctx)
    if data['rss_outcome'] != 'RSS_MIXED_CURRENT_MISSING' or data['rss_ok'] is not True:
        return _fail('T57 rss rewritten')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['latest_run_health'] != 'SUCCESS_WITH_COMPONENT_FAILURE':
        return _fail(f'T57 health {ev["latest_run_health"]}')
    _pass('T57')

    inconsistent = classify_rss_outcome(result=_result(
        n=2, items=1, errors=[], statuses=[('a', 'CURRENT'), ('b', 'CURRENT')],
    ))
    # current_count==2==N, missing 0, stale 0, error 0, items>0 -> ALL_CURRENT
    # force inconsistent counts: N=2 but one unknown freshness
    bad = _all_current()
    bad['provider_status']['p0']['freshness_status'] = 'WEIRD'
    classified = classify_rss_outcome(result=bad)
    if classified['rss_outcome'] != 'RSS_PARTIAL':
        return _fail('T58 inconsistent')
    if classified['last_error'] != 'rss_partial:inconsistent_or_partial_provider_state':
        return _fail(f'T58 diagnostic {classified["last_error"]}')
    _pass('T58')
    return 0


def test_t56_total_function() -> int:
    from backend.news.news_pipeline_reliability import RSS_OUTCOMES, classify_rss_outcome

    fixtures = [
        _all_current(),
        _zero_missing(),
        _all_stale(),
        _mixed_stale_missing(),
        _current_stale_articles(),
        _mixed_current_missing(),
        _current_missing_errors(),
        _all_current(errors=['x']),
        {'sources_checked': 0, 'items_found': 0, 'error_count': 0, 'errors': [], 'provider_status': {}},
        _result(n=2, items=0, errors=['e'], statuses=[('a', 'MISSING'), ('b', 'MISSING')]),
        _result(n=3, items=4, errors=[], statuses=[('a', 'CURRENT'), ('b', 'CURRENT'), ('c', 'MISSING')]),
        _result(n=2, items=2, errors=[], statuses=[('a', 'CURRENT'), ('b', 'STALE')]),
        _result(n=1, items=0, errors=['e'], statuses=[('a', 'STALE')]),
        _result(n=1, items=1, errors=[], statuses=[('a', 'CURRENT')]),
        _result(n=2, items=1, errors=['e'], statuses=[('a', 'CURRENT'), ('b', 'CURRENT')]),
    ]
    seen = []
    for fixture in fixtures:
        classified = classify_rss_outcome(result=fixture)
        outcome = classified['rss_outcome']
        if outcome is None or outcome not in RSS_OUTCOMES:
            return _fail(f'T56 null/invalid {outcome} for {fixture.get("sources_checked")}')
        seen.append(outcome)
    step1 = classify_rss_outcome(result=None, step1_exception=RuntimeError('x'))
    if step1['rss_outcome'] != 'RSS_STEP1_EXCEPTION':
        return _fail('T56 exception')
    if len(seen) != len(fixtures):
        return _fail('T56 missing classification')
    _pass('T56')
    return 0


def _running_sched(now: datetime) -> dict:
    return {'last_scheduler_tick_unix': now.timestamp()}


def _dump(ctx: dict, data: dict) -> None:
    ctx['sidecar'].write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def test_t59_t73_repair1(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        _atomic_save,
        _classify_payload,
        _evaluate_missed_expected_run,
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    old_market = MARKET_NOW - timedelta(hours=2)
    old_ns = int(old_market.timestamp() * 1_000_000_000)
    record_news_pipeline_attempt(old_ns)
    finalize_news_pipeline_run(old_ns, _all_current())
    ev = evaluate_news_pipeline_reliability(
        now=MARKET_NOW,
        orchestrator_state=_running_sched(MARKET_NOW),
    )
    if ev['freshness_state'] != 'STALE':
        return _fail(f'T59 freshness {ev["freshness_state"]}')
    if ev['missed_expected_run'] is not True:
        return _fail('T59 missed_expected_run')
    if ev['scheduler_state'] != 'SCHEDULER_RUNNING':
        return _fail('T59 scheduler')
    _pass('T59')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    ev = evaluate_news_pipeline_reliability(
        now=MARKET_NOW,
        orchestrator_state=_running_sched(MARKET_NOW),
    )
    if ev['freshness_state'] != 'CURRENT' or ev['missed_expected_run'] is not False:
        return _fail(f'T60 {ev["freshness_state"]} missed={ev["missed_expected_run"]}')
    _pass('T60')

    ctx['sidecar'].unlink()
    night_old = NIGHT_NOW - timedelta(hours=10)
    night_ns = int(night_old.timestamp() * 1_000_000_000)
    record_news_pipeline_attempt(night_ns)
    finalize_news_pipeline_run(night_ns, _all_current())
    ev = evaluate_news_pipeline_reliability(
        now=NIGHT_NOW,
        orchestrator_state=_running_sched(NIGHT_NOW),
    )
    if ev['freshness_state'] not in ('IDLE', 'STALE', 'MISSING'):
        return _fail(f'T61 freshness {ev["freshness_state"]}')
    if ev['missed_expected_run'] is not False:
        return _fail('T61 night interval must not false-positive missed_expected_run')
    _pass('T61')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(old_ns)
    ev = evaluate_news_pipeline_reliability(
        now=MARKET_NOW,
        orchestrator_state=_running_sched(MARKET_NOW),
    )
    if 'IN_PROGRESS_STALE' not in ev['collector_state']:
        return _fail(f'T62 collector {ev["collector_state"]}')
    shared = _evaluate_missed_expected_run(
        _load(ctx), MARKET_NOW, 'SCHEDULER_RUNNING'
    )
    if shared is not True or ev['missed_expected_run'] is not True:
        return _fail('T62 shared missed-run classifier')
    if ev['missed_expected_run'] != shared:
        return _fail('T62 evaluator diverged from shared helper')
    _pass('T62')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_stale())
    data = _load(ctx)
    data['rss_ok'] = True
    _dump(ctx, data)
    before = _bytes(ctx)
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state=_running_sched(MARKET_NOW))
    if ev['sidecar_health'] != 'MALFORMED':
        return _fail(f'T63 health {ev["sidecar_health"]}')
    rec = record_news_pipeline_attempt(NS_B)
    fin = finalize_news_pipeline_run(NS_B, _all_current())
    if rec.get('status') != 'MALFORMED' or fin.get('status') != 'MALFORMED':
        return _fail(f'T63 status rec={rec} fin={fin}')
    if _bytes(ctx) != before:
        return _fail('T63 overwrote corrupt bytes')
    _pass('T63')

    data = json.loads(before.decode('utf-8'))
    data['rss_ok'] = False
    data['last_run_ok'] = True
    _dump(ctx, data)
    if _classify_payload(json.loads(ctx['sidecar'].read_text(encoding='utf-8'))) != 'MALFORMED':
        return _fail('T64 expected MALFORMED')
    ev = evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    if ev['sidecar_health'] != 'MALFORMED':
        return _fail('T64 evaluate trusted payload')
    _pass('T64')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_B)
    data = _load(ctx)
    data['last_completed_run_started_ns'] = NS_C
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T65 expected MALFORMED')
    _pass('T65')

    data['last_completed_run_started_ns'] = NS_B
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T66 expected MALFORMED')
    _pass('T66')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    data = _load(ctx)
    data['updated_at'] = '2099-07-27T10:15:00'
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T67 naive updated_at')
    data = _load(ctx)
    data['updated_at'] = '2099-07-27T10:15:00+05:30'
    data['last_attempt_at'] = '2099-07-27T10:15:00'
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T67 naive last_attempt_at')
    data = _load(ctx)
    data['last_attempt_at'] = '2099-07-27T10:15:00+05:30'
    data['last_success_at'] = '2099-07-27T10:15:00'
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T67 naive history timestamp')
    utc_data = _load(ctx)
    utc_data['last_success_at'] = '2099-07-27T04:45:00+00:00'
    _dump(ctx, utc_data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T67 UTC offset must not canonicalize')
    _pass('T67')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    data = _load(ctx)
    data['provider_stale_count'] = 1
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T68 stale_count')
    data['provider_stale_count'] = 0
    data['provider_current_count'] = 1
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T68 current_count != sources_checked')
    _pass('T68')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _zero_missing())
    data = _load(ctx)
    data['items_found'] = 1
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T69 items_found')
    data['items_found'] = 0
    data['provider_missing_count'] = 1
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T69 missing_count != sources_checked')
    _pass('T69')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _mixed_current_missing())
    data = _load(ctx)
    data['provider_stale_count'] = 1
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T70 stale in mixed')
    data['provider_stale_count'] = 0
    data['provider_current_count'] = 2
    data['provider_missing_count'] = 1
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T70 partition overflow')
    _pass('T70')

    ctx['sidecar'].unlink()
    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, None, step1_exception=RuntimeError('step1'))
    data = _load(ctx)
    data['sources_checked'] = 2
    data['items_found'] = 1
    data['provider_current_count'] = 2
    data['provider_stale_count'] = 0
    data['provider_missing_count'] = 0
    data['rss_error_count'] = 0
    data['feeds_ok'] = 2
    data['feeds_failed'] = 0
    _dump(ctx, data)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T71 fabricated STEP1 counts')
    _pass('T71')

    ctx['sidecar'].unlink()
    from backend.news.news_pipeline_reliability import classify_rss_outcome

    bad = _all_current()
    bad['provider_status']['p0']['freshness_status'] = 'WEIRD'
    classified = classify_rss_outcome(result=bad)
    if classified['rss_outcome'] != 'RSS_PARTIAL':
        return _fail('T72 classifier')
    record_news_pipeline_attempt(NS_A)
    fin = finalize_news_pipeline_run(NS_A, bad)
    if fin.get('status') != 'WRITTEN':
        return _fail(f'T72 persist {fin}')
    persisted = _load(ctx)
    if persisted['rss_outcome'] != 'RSS_PARTIAL' or persisted['rss_ok'] is not False:
        return _fail('T72 rss fields')
    if _classify_payload(persisted) != 'OK':
        return _fail('T72 fail-closed PARTIAL rejected by validation')
    _pass('T72')

    expected = (json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    real_write = os.write

    def _short_write(fd: int, data: object) -> int:
        chunk = data[:5] if hasattr(data, '__getitem__') and len(data) > 5 else data
        return real_write(fd, chunk)

    with patch('backend.news.news_pipeline_reliability.os.write', _short_write):
        _atomic_save(ctx['sidecar'], persisted)
    if ctx['sidecar'].read_bytes() != expected:
        return _fail('T73 short-write path lost bytes')
    _pass('T73')
    return 0


def test_t74_t78_canonical_form(ctx: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        _classify_payload,
        _iso_from_ns,
        _is_canonical_ist_timestamp,
        _now_iso,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    valid = _load(ctx)

    padded_leading = dict(valid)
    padded_leading['updated_at'] = ' 2099-07-27T10:15:00+05:30'
    _dump(ctx, padded_leading)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T74 leading whitespace')
    padded_trailing = dict(valid)
    padded_trailing['updated_at'] = '2099-07-27T10:15:00+05:30 '
    _dump(ctx, padded_trailing)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T74 trailing whitespace')
    if _is_canonical_ist_timestamp(' 2099-07-27T10:15:00+05:30 '):
        return _fail('T74 padded both sides accepted')
    _pass('T74')

    spaced = dict(valid)
    spaced['updated_at'] = '2099-07-27 10:15:00+05:30'
    _dump(ctx, spaced)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T75 space separator')
    if _is_canonical_ist_timestamp('2099-07-27 10:15:00+05:30'):
        return _fail('T75 helper accepted space separator')
    _pass('T75')

    for raw in (
        '2099-07-27T10:15:00+05:30:00',
        '2099-07-27T10:15:00,123+05:30',
        '2099-07-27T10:15:00.000000+05:30',
    ):
        mutated = dict(valid)
        mutated['updated_at'] = raw
        _dump(ctx, mutated)
        if _classify_payload(_load(ctx)) != 'MALFORMED':
            return _fail(f'T76 accepted {raw!r}')
        if _is_canonical_ist_timestamp(raw):
            return _fail(f'T76 helper accepted {raw!r}')
    _pass('T76')

    writer_ns = _iso_from_ns(NS_A)
    writer_now = _now_iso(MARKET_NOW)
    if not _is_canonical_ist_timestamp(writer_ns):
        return _fail(f'T77 _iso_from_ns rejected {writer_ns!r}')
    if not _is_canonical_ist_timestamp(writer_now):
        return _fail(f'T77 _now_iso rejected {writer_now!r}')
    restored = dict(valid)
    restored['updated_at'] = writer_now
    restored['last_attempt_at'] = writer_ns
    restored['last_success_at'] = writer_ns
    _dump(ctx, restored)
    if _classify_payload(_load(ctx)) != 'OK':
        return _fail('T77 writer timestamps rejected by payload validator')
    _pass('T77')

    fractional_dt = datetime(2099, 7, 27, 10, 15, 0, 123456, tzinfo=IST)
    fractional = _now_iso(fractional_dt)
    if fractional != '2099-07-27T10:15:00.123456+05:30':
        return _fail(f'T78 unexpected writer form {fractional!r}')
    if not _is_canonical_ist_timestamp(fractional):
        return _fail('T78 fractional writer output rejected')
    frac_doc = dict(valid)
    frac_doc['updated_at'] = fractional
    _dump(ctx, frac_doc)
    if _classify_payload(_load(ctx)) != 'OK':
        return _fail('T78 fractional payload rejected')
    mutated_frac = fractional.replace('T', ' ')
    if _is_canonical_ist_timestamp(mutated_frac):
        return _fail('T78 lexical mutation accepted')
    frac_doc['updated_at'] = mutated_frac
    _dump(ctx, frac_doc)
    if _classify_payload(_load(ctx)) != 'MALFORMED':
        return _fail('T78 mutated fractional payload not MALFORMED')
    _pass('T78')
    return 0


def test_t15_t16_protected(ctx: dict, before_digests: dict[str, str], before_data: dict) -> int:
    from backend.news.news_pipeline_reliability import (
        evaluate_news_pipeline_reliability,
        finalize_news_pipeline_run,
        record_news_pipeline_attempt,
    )

    record_news_pipeline_attempt(NS_A)
    finalize_news_pipeline_run(NS_A, _all_current())
    evaluate_news_pipeline_reliability(now=MARKET_NOW, orchestrator_state={})
    for path in PROTECTED:
        if _digest(path) != before_digests[str(path)]:
            return _fail(f'T15 mutated {path}')
    after = _snapshot_data()
    if after != before_data:
        return _fail('T16 repository data/ mutated')
    if _git_data_status():
        return _fail('T16 git data/ dirty')
    _pass('T15')
    _pass('T16')
    return 0


def main() -> int:
    before_data = _snapshot_data()
    before_digests = {str(path): _digest(path) for path in PROTECTED}
    rc = test_build_identity()
    if rc:
        return rc
    rc = test_t20_imports()
    if rc:
        return rc
    rc = test_t17_t22_static()
    if rc:
        return rc
    rc = test_t50_zero_partition()
    if rc:
        return rc
    rc = test_t56_total_function()
    if rc:
        return rc
    with _isolated() as ctx:
        for fn in (
            test_t1_missing,
            test_t25_t26_t38_first_attempt,
        ):
            rc = fn(ctx)
            if rc:
                return rc
    with _isolated() as ctx:
        rc = test_clocks_and_zero_result(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_partial_and_mixed(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_components_and_no_providers(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_t8_t9_tracker(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_corrupt_lock_ordering(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_attempt_finalize_machine(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_overlap(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_p1_and_refuse(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_t2_recent_market(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_scheduler_and_idle(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_t43_no_history_failed(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_repair5_positive(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_t15_t16_protected(ctx, before_digests, before_data)
        if rc:
            return rc

    with _isolated() as ctx:
        rc = test_t59_t73_repair1(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_t74_t78_canonical_form(ctx)
        if rc:
            return rc

    required = [f'T{i}' for i in range(1, 79)]
    missing = [name for name in required if name not in PASS_MARKERS]
    if missing:
        return _fail(f'missing T markers: {missing}')
    print('NEWS_PIPELINE_RELIABILITY_52R_D_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
