#!/usr/bin/env python3
"""AstraEdge 52R-B2 — automatic governed PRIMARY verification (isolated)."""

from __future__ import annotations

import ast
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
PUB = datetime(2099, 7, 31, 10, 15, 0, tzinfo=IST)
PASS_MARKERS: list[str] = []

B2_PATH = PROJECT_ROOT / 'backend' / 'news' / 'automatic_primary_verification.py'
TRACKER_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py'
REGISTRY_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py'
VERIFIER_PATH = PROJECT_ROOT / 'backend' / 'news' / 'primary_source_verifier.py'
ADAPTER_PATH = PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py'
FOUNDATION_PATH = PROJECT_ROOT / 'backend' / 'news' / 'broker_discovery_foundation.py'

CORPORATE_PDF = 'https://nsearchives.nseindia.com/corporate/INFY_ANNOUNCEMENT_1.pdf'
CORPORATE_XBRL = 'https://nsearchives.nseindia.com/corporate/xbrl/INFY_ANNOUNCEMENT_1.xml'
DEBT_PDF = 'https://nsearchives.nseindia.com/content/debt/WDM/DEBT1.pdf'
MEDIA_URL = 'https://economictimes.indiatimes.com/markets/infosys-other-event'


def _fail(msg: str) -> int:
    print(f'AUTOMATIC_PRIMARY_VERIFICATION_52R_B2_FAIL: {msg}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


def _git_data_status() -> str:
    proc = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or '').strip()


def _exchange(**extra):
    row = {
        'source_name': 'NSE Corporate Information',
        'source_kind': 'EXCHANGE',
        'source_url': CORPORATE_PDF,
        'source_headline': 'Infosys Limited — Board Meeting Intimation',
        'source_published_at': PUB,
        'original_publisher': 'NSE',
        'bounded_excerpt': 'Board meeting intimation for Infosys.',
        'symbols': ['INFY'],
        'event_type': 'OTHER',
        'structured_facts': {},
    }
    row.update(extra)
    return row


def _publisher(**extra):
    row = {
        'source_name': 'ET Markets',
        'source_kind': 'NEWS_PUBLISHER',
        'source_url': MEDIA_URL,
        'source_headline': 'Infosys other event publisher copy',
        'source_published_at': PUB,
        'original_publisher': 'ET Markets',
        'bounded_excerpt': 'Publisher copy.',
        'symbols': ['INFY'],
        'event_type': 'OTHER',
        'structured_facts': {},
    }
    row.update(extra)
    return row


@contextmanager
def _isolated_b2():
    from scripts._test_runtime_isolation import isolated_premarket_data_root

    with tempfile.TemporaryDirectory() as td:
        lock_path = Path(td) / 'rss_discovery_ingest.lock'
        with isolated_premarket_data_root() as iso:
            def _temp_data_path(relative: str) -> Path:
                rel = str(relative or '').replace('\\', '/').lstrip('/')
                path = iso['temp_root'] / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                return path

            with patch.dict(os.environ, {'RSS_DISCOVERY_LOCK_PATH': str(lock_path)}, clear=False), patch(
                'backend.news.broker_discovery_foundation.get_data_path',
                side_effect=_temp_data_path,
            ), patch(
                'backend.news.rss_discovery_adapter.get_data_path',
                side_effect=_temp_data_path,
            ):
                yield {
                    'iso': iso,
                    'lock_path': lock_path,
                    'store_path': iso['temp_root'] / 'broker_news_discovery_store.json',
                }


def _reset(ctx: dict) -> None:
    store = ctx['store_path']
    if store.exists():
        store.unlink()
    lock = ctx['lock_path']
    if lock.exists():
        lock.unlink()


def test_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    allowed = {('52R-B2', 'AstraEdge 52R-B2'), ('52R-C1A', 'AstraEdge 52R-C1A'), ('52R-C1B', 'AstraEdge 52R-C1B'), ('52R-D', 'AstraEdge 52R-D'), ('52R-D2P', 'AstraEdge 52R-D2P'), ('52R-D2', 'AstraEdge 52R-D2'), ('53A', 'AstraEdge 53A'), ('53A2', 'AstraEdge 53A2')}
    mismatches = (
        ('52R-B2', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-B2'),
        ('52R-B2', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-B2'),
        ('52R-B2', 'AstraEdge 52R-C1A'),
        ('52R-C1A', 'AstraEdge 52R-C1B'),
        ('52R-C1B', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-D'),
        ('52R-D', 'AstraEdge 52R-C1B'),
        ('52R-D2P', 'AstraEdge 52R-D'),
        ('52R-D', 'AstraEdge 52R-D2P'),
        ('52R-D2', 'AstraEdge 52R-D2P'),
        ('52R-D2P', 'AstraEdge 52R-D2'),
        ('53A', 'AstraEdge 52R-D2'),
        ('52R-D2', 'AstraEdge 53A'),
        ('53A2', 'AstraEdge 53A'),
        ('53A', 'AstraEdge 53A2'),
    )
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'expected exact pair 52R-B2 / AstraEdge 52R-B2 or successor '
            f'52R-C1A / AstraEdge 52R-C1A or 52R-C1B / AstraEdge 52R-C1B or '
            f'52R-D / AstraEdge 52R-D, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    print(f'BUILD_PAIR {BUILD_STAGE} / {TELEGRAM_BUILD}')
    return 0


def test_nse_corporate_primary(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import run_automatic_primary_verification
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_DISCOVERY_ONLY,
        VERIFICATION_PRIMARY,
        get_event,
        normalize_url,
        upsert_sighting,
    )

    seeded = upsert_sighting(_exchange())
    event = get_event(seeded['event_id'])
    if not event or event.get('verification_status') != VERIFICATION_DISCOVERY_ONLY:
        return _fail(f'precondition DISCOVERY_ONLY failed: {event}')
    stats = run_automatic_primary_verification()
    after = get_event(seeded['event_id'])
    canonical = normalize_url(CORPORATE_PDF)
    print(
        'NSE_CORPORATE_EVIDENCE '
        f'stats={stats} status={after.get("verification_status") if after else None} '
        f'url={after.get("primary_source_url") if after else None}'
    )
    if stats.get('verified') != 1:
        return _fail(f'expected one verified corporate PDF, got {stats}')
    if not after or after.get('verification_status') != VERIFICATION_PRIMARY:
        return _fail(f'expected PRIMARY_SOURCE_VERIFIED, got {after}')
    if after.get('primary_source_url') != canonical:
        return _fail(f'primary_source_url mismatch {after.get("primary_source_url")!r}')
    _pass('B2_NSE_CORPORATE_PRIMARY_OK')
    return 0


def test_nse_xbrl_primary(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import run_automatic_primary_verification
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        normalize_url,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import classify_exchange_primary_url

    info = classify_exchange_primary_url(CORPORATE_XBRL)
    if info.get('ok') is not True:
        return _fail(f'B1 classifier must accept XBRL path, got {info}')
    seeded = upsert_sighting(_exchange(
        source_url=CORPORATE_XBRL,
        source_headline='Infosys Limited — XBRL Filing',
    ))
    stats = run_automatic_primary_verification()
    after = get_event(seeded['event_id'])
    canonical = normalize_url(CORPORATE_XBRL)
    print(f'NSE_XBRL_EVIDENCE stats={stats} status={after.get("verification_status") if after else None}')
    if stats.get('verified') != 1:
        return _fail(f'expected XBRL promotion, got {stats}')
    if not after or after.get('verification_status') != VERIFICATION_PRIMARY:
        return _fail(f'XBRL event not PRIMARY: {after}')
    if after.get('primary_source_url') != canonical:
        return _fail(f'XBRL primary URL mismatch {after.get("primary_source_url")!r}')
    _pass('B2_NSE_XBRL_PRIMARY_OK')
    return 0


def test_debt_path_fail_closed(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import run_automatic_primary_verification
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import classify_exchange_primary_url

    info = classify_exchange_primary_url(DEBT_PDF)
    seeded = upsert_sighting(_exchange(
        source_url=DEBT_PDF,
        source_headline='Infosys Limited — Debt Filing',
    ))
    stats = run_automatic_primary_verification()
    after = get_event(seeded['event_id'])
    print(
        f'DEBT_EVIDENCE classifier={info} stats={stats} '
        f'status={after.get("verification_status") if after else None} '
        f'url={after.get("primary_source_url") if after else None}'
    )
    if info.get('ok') or info.get('reason') != 'event_path_not_authoritative':
        return _fail(f'B1 reason must remain event_path_not_authoritative, got {info}')
    if after and after.get('verification_status') == VERIFICATION_PRIMARY:
        return _fail('debt path must not become PRIMARY')
    if after and after.get('primary_source_url'):
        return _fail(f'debt path wrote primary_source_url {after.get("primary_source_url")!r}')
    if stats.get('verified'):
        return _fail(f'debt path must not verify, got {stats}')
    _pass('B2_DEBT_PATH_FAIL_CLOSED_OK')
    return 0


def test_media_never_primary(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import run_automatic_primary_verification
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )

    seeded = upsert_sighting(_publisher())
    stats = run_automatic_primary_verification()
    after = get_event(seeded['event_id'])
    print(f'MEDIA_EVIDENCE stats={stats} status={after.get("verification_status") if after else None}')
    if stats.get('verified'):
        return _fail(f'media must never verify, got {stats}')
    if stats.get('attempted'):
        return _fail(f'media must not be passed to B1, got {stats}')
    if after and after.get('verification_status') == VERIFICATION_PRIMARY:
        return _fail('media event became PRIMARY')
    _pass('B2_MEDIA_NEVER_PRIMARY_OK')
    return 0


def test_autoverification_idempotent(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import run_automatic_primary_verification
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        normalize_url,
        upsert_sighting,
    )

    seeded = upsert_sighting(_exchange())
    first = run_automatic_primary_verification()
    store_after_first = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    second = run_automatic_primary_verification()
    store_after_second = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    event = get_event(seeded['event_id'])
    canonical = normalize_url(CORPORATE_PDF)
    print(
        'IDEMPOTENCE_EVIDENCE '
        f'first={first} second={second} '
        f'events={len(store_after_second.get("events") or {})} '
        f'sightings={len(store_after_second.get("sightings") or {})}'
    )
    if first.get('verified') != 1:
        return _fail(f'first pass should verify once, got {first}')
    if second.get('verified'):
        return _fail(f'second pass must not re-promote, got {second}')
    if second.get('already_primary', 0) < 1:
        return _fail(f'second pass should count already_primary, got {second}')
    if len(store_after_first.get('events') or {}) != 1 or len(store_after_second.get('events') or {}) != 1:
        return _fail('second pass created extra events')
    if len(store_after_first.get('sightings') or {}) != 1 or len(store_after_second.get('sightings') or {}) != 1:
        return _fail('second pass created extra sightings')
    if not event or event.get('verification_status') != VERIFICATION_PRIMARY:
        return _fail(f'status not stable PRIMARY: {event}')
    if event.get('primary_source_url') != canonical:
        return _fail(f'primary URL changed {event.get("primary_source_url")!r}')
    _pass('B2_AUTOVERIFICATION_IDEMPOTENT_OK')
    return 0


def test_bounded_batch(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import (
        MAX_VERIFICATION_ATTEMPTS,
        run_automatic_primary_verification,
    )
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY, get_event, upsert_sighting

    created = []
    for idx in range(MAX_VERIFICATION_ATTEMPTS + 5):
        seeded = upsert_sighting(_exchange(
            source_url=f'https://nsearchives.nseindia.com/corporate/BATCH{idx:02d}.pdf',
            source_headline=f'Infosys Limited — Batch Filing {idx:02d}',
            source_published_at=PUB + timedelta(seconds=idx),
        ))
        created.append(seeded)
    stats = run_automatic_primary_verification()
    primary_count = 0
    for row in created:
        event = get_event(row['event_id'])
        if event and event.get('verification_status') == VERIFICATION_PRIMARY:
            primary_count += 1
    print(
        'BOUNDED_EVIDENCE '
        f'created={len(created)} attempted={stats.get("attempted")} '
        f'verified={stats.get("verified")} bounded={stats.get("bounded")} '
        f'primary_count={primary_count} cap={MAX_VERIFICATION_ATTEMPTS}'
    )
    if stats.get('attempted') != MAX_VERIFICATION_ATTEMPTS:
        return _fail(f'attempted must equal cap {MAX_VERIFICATION_ATTEMPTS}, got {stats}')
    if stats.get('bounded') is not True:
        return _fail(f'bounded flag must be true, got {stats}')
    if stats.get('verified') != MAX_VERIFICATION_ATTEMPTS:
        return _fail(f'verified must equal cap, got {stats}')
    if primary_count != MAX_VERIFICATION_ATTEMPTS:
        return _fail(f'PRIMARY count {primary_count} exceeds or misses cap')
    _pass('B2_BOUNDED_BATCH_OK')
    return 0


def test_failure_containment(ctx: dict) -> int:
    from backend.news import automatic_primary_verification as b2
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )

    bad = upsert_sighting(_exchange(
        source_url='https://nsearchives.nseindia.com/corporate/BAD1.pdf',
        source_headline='Infosys Limited — Bad Candidate',
        source_published_at=PUB + timedelta(seconds=2),
    ))
    good = upsert_sighting(_exchange(
        source_url='https://nsearchives.nseindia.com/corporate/GOOD1.pdf',
        source_headline='Infosys Limited — Good Candidate',
        source_published_at=PUB + timedelta(seconds=1),
    ))
    real = b2.verify_linked_primary_sighting

    def _wrapped(event_id, sighting_id, *args, **kwargs):
        if str(event_id) == str(bad['event_id']):
            raise RuntimeError('synthetic candidate failure')
        return real(event_id, sighting_id, *args, **kwargs)

    with patch.object(b2, 'verify_linked_primary_sighting', side_effect=_wrapped):
        stats = b2.run_automatic_primary_verification()
    good_event = get_event(good['event_id'])
    bad_event = get_event(bad['event_id'])
    print(
        'CONTAINMENT_EVIDENCE '
        f'stats={stats} good={good_event.get("verification_status") if good_event else None} '
        f'bad={bad_event.get("verification_status") if bad_event else None}'
    )
    if stats.get('failed', 0) < 1:
        return _fail(f'expected a contained failure, got {stats}')
    if not good_event or good_event.get('verification_status') != VERIFICATION_PRIMARY:
        return _fail('valid candidate must still promote after a sibling failure')
    if bad_event and bad_event.get('verification_status') == VERIFICATION_PRIMARY:
        return _fail('failing candidate must not become PRIMARY')
    _pass('B2_FAILURE_CONTAINMENT_OK')
    return 0


def test_zero_http(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import run_automatic_primary_verification
    from backend.news.broker_discovery_foundation import upsert_sighting

    upsert_sighting(_exchange())
    calls: list[str] = []

    def _boom(*_args, **_kwargs):
        calls.append('network')
        raise AssertionError('network call during B2')

    network_patches = [
        patch('urllib.request.urlopen', _boom),
        patch('http.client.HTTPConnection', _boom),
        patch('http.client.HTTPSConnection', _boom),
    ]
    try:
        import requests  # noqa: F401
        network_patches.append(patch('requests.request', _boom))
        network_patches.append(patch('requests.get', _boom))
        network_patches.append(patch('requests.Session.get', _boom))
    except Exception:
        pass
    try:
        import httpx  # noqa: F401
        network_patches.append(patch('httpx.request', _boom))
        network_patches.append(patch('httpx.get', _boom))
    except Exception:
        pass

    with contextlib_nested(network_patches):
        stats = run_automatic_primary_verification()
    print(f'ZERO_HTTP_EVIDENCE calls={calls} verified={stats.get("verified")}')
    if calls:
        return _fail(f'B2 performed network calls: {calls}')
    if stats.get('verified') != 1:
        return _fail(f'HTTP guard should not block verification, got {stats}')
    src = B2_PATH.read_text(encoding='utf-8')
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or '').split('.')[0])
    forbidden = {'requests', 'httpx', 'aiohttp', 'selenium', 'playwright'}
    hits = sorted(imported & forbidden)
    if hits:
        return _fail(f'B2 orchestration imports network stack {hits}')
    _pass('B2_ZERO_HTTP_AUTOVERIFICATION_OK')
    return 0


def contextlib_nested(patches):
    from contextlib import ExitStack

    stack = ExitStack()
    for item in patches:
        stack.enter_context(item)
    return stack


def test_no_nested_lock(ctx: dict) -> int:
    from backend.news.automatic_primary_verification import run_automatic_primary_verification
    from backend.news.broker_discovery_foundation import upsert_sighting
    from backend.news.rss_discovery_adapter import _BatchLock

    upsert_sighting(_exchange())
    state = {'depth': 0, 'nested': False, 'entry_depths': []}
    orig_acquire = _BatchLock.try_acquire
    orig_release = _BatchLock.release

    def _acquire(self):
        if state['depth'] > 0:
            state['nested'] = True
        ok = orig_acquire(self)
        if ok:
            state['depth'] += 1
        return ok

    def _release(self):
        try:
            return orig_release(self)
        finally:
            if state['depth'] > 0:
                state['depth'] -= 1

    from backend.news import automatic_primary_verification as b2

    real_verify = b2.verify_linked_primary_sighting

    def _verify(*args, **kwargs):
        state['entry_depths'].append(state['depth'])
        return real_verify(*args, **kwargs)

    src = B2_PATH.read_text(encoding='utf-8')
    if '_BatchLock' in src or 'discovery_lock_path' in src:
        return _fail('B2 must not take the shared discovery lock')

    with patch.object(_BatchLock, 'try_acquire', _acquire), patch.object(_BatchLock, 'release', _release), patch.object(
        b2, 'verify_linked_primary_sighting', side_effect=_verify
    ):
        stats = run_automatic_primary_verification()
    print(
        'NESTED_LOCK_EVIDENCE '
        f'nested={state["nested"]} entry_depths={state["entry_depths"]} stats={stats}'
    )
    if state['nested']:
        return _fail('B2 held an outer discovery lock while calling B1')
    if not state['entry_depths'] or any(depth != 0 for depth in state['entry_depths']):
        return _fail(f'B1 must be entered with zero outer lock depth, got {state["entry_depths"]}')
    if stats.get('verified') != 1:
        return _fail(f'lock instrumentation must not prevent promotion, got {stats}')
    _pass('B2_NO_NESTED_DISCOVERY_LOCK_OK')
    return 0


def test_single_production_owner() -> int:
    from backend.collectors.live_news_tracker import run_live_news_tracker

    tracker_src = TRACKER_PATH.read_text(encoding='utf-8')
    registry_src = REGISTRY_PATH.read_text(encoding='utf-8')
    if 'run_automatic_primary_verification' not in tracker_src:
        return _fail('live_news_tracker must invoke B2 after discovery ingest')
    ingest_idx = tracker_src.find('ingest_discovery=True')
    b2_idx = tracker_src.find('run_automatic_primary_verification')
    if ingest_idx < 0 or b2_idx < ingest_idx:
        return _fail('B2 must run after ingest_discovery=True in live_news_tracker')
    if 'run_automatic_primary_verification' in registry_src:
        return _fail('unified refresh must not activate B2')
    if 'verify_linked_primary_sighting' in tracker_src:
        return _fail('live_news_tracker must not call B1 directly')

    hits: list[str] = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        rel = str(path.relative_to(PROJECT_ROOT)).replace('\\', '/')
        if rel == 'backend/news/automatic_primary_verification.py':
            continue
        text = path.read_text(encoding='utf-8')
        if 'run_automatic_primary_verification' in text:
            hits.append(rel)
    if hits != ['backend/collectors/live_news_tracker.py']:
        return _fail(f'unexpected B2 production owners: {hits}')

    b2_calls: list[str] = []

    def _refresh(**_kwargs):
        return {
            'ok': True,
            'sources_checked': 0,
            'items_found': 0,
            'new_items': 0,
            'error_count': 0,
            'errors': [],
            'discovery': {'inserted': 0},
        }

    def _b2():
        b2_calls.append('b2')
        return {'scanned': 0, 'attempted': 0, 'verified': 0, 'skipped': 0, 'failed': 0}

    with tempfile.TemporaryDirectory() as td:
        sidecar = Path(td) / 'news_pipeline_reliability.json'
        lock = Path(td) / 'news_pipeline_reliability.lock'
        with patch('backend.collectors.live_news_tracker.run_unified_news_refresh', side_effect=_refresh), patch(
            'backend.news.automatic_primary_verification.run_automatic_primary_verification',
            side_effect=_b2,
        ), patch(
            'backend.news.verified_intelligence_classifier.run_verified_intelligence_classification',
            return_value={'ok': True, 'attempted': 0, 'inserted': 0, 'failed': 0},
        ), patch.dict(
            os.environ,
            {
                'NEWS_PIPELINE_RELIABILITY_PATH': str(sidecar),
                'NEWS_PIPELINE_RELIABILITY_LOCK_PATH': str(lock),
            },
            clear=False,
        ):
            result = run_live_news_tracker()
    if b2_calls != ['b2']:
        return _fail(f'live owner did not invoke B2 exactly once, got {b2_calls}')
    if 'primary_verification' not in result:
        return _fail('live owner must attach primary_verification stats')
    print('SINGLE_OWNER_EVIDENCE caller=backend/collectors/live_news_tracker.py')
    _pass('B2_SINGLE_PRODUCTION_OWNER_OK')
    return 0


def test_repo_data_safe() -> int:
    status = _git_data_status()
    if status:
        return _fail(f'repository data/ is dirty: {status}')
    _pass('B2_REPO_DATA_SAFE_OK')
    return 0


def main() -> int:
    no_ctx = (
        test_build_identity,
        test_single_production_owner,
        test_repo_data_safe,
    )
    for fn in no_ctx:
        rc = fn()
        if rc:
            return rc

    ctx_tests = (
        test_nse_corporate_primary,
        test_nse_xbrl_primary,
        test_debt_path_fail_closed,
        test_media_never_primary,
        test_autoverification_idempotent,
        test_bounded_batch,
        test_failure_containment,
        test_zero_http,
        test_no_nested_lock,
    )
    with _isolated_b2() as ctx:
        for fn in ctx_tests:
            _reset(ctx)
            rc = fn(ctx)
            if rc:
                return rc

    required = (
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
    )
    missing = [m for m in required if m not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('AUTOMATIC_PRIMARY_VERIFICATION_52R_B2_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
