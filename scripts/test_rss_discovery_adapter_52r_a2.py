#!/usr/bin/env python3
"""AstraEdge 52R-A2 — RSS discovery adapter (isolated)."""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
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
RAW_EXCEPTION_ESCAPES = 0

ADAPTER_PATH = PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py'
REGISTRY_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py'
TRACKER_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py'

LOCK_SUBPROCESS_SCRIPT = r'''
import json
import os
import sys

from backend.news.rss_discovery_adapter import (
    _BatchLock,
    discovery_lock_path,
    ingest_registry_articles,
)

mode = sys.argv[1]
result = {'pid': os.getpid(), 'mode': mode}
if mode == 'ingest':
    result['stats'] = ingest_registry_articles([json.loads(sys.argv[2])])
elif mode in ('acquire', 'crash'):
    lock = _BatchLock(discovery_lock_path())
    result['acquired'] = lock.try_acquire()
    print('LOCK_CHILD_RESULT ' + json.dumps(result, sort_keys=True), flush=True)
    if mode == 'crash':
        os._exit(0 if result['acquired'] else 4)
    if result['acquired']:
        lock.release()
    raise SystemExit(0)
else:
    raise SystemExit(5)
print('LOCK_CHILD_RESULT ' + json.dumps(result, sort_keys=True), flush=True)
'''

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
    'scanner',
    'trade_card_engine',
    'opening_rally_radar',
    'weekly_signal_capture',
    'capture_news_signal',
    'learning_engine',
    'outcome_tracker',
)

NON_WRITER_PATHS = (
    PROJECT_ROOT / 'backend' / 'my_feed' / 'news_refresh.py',
    PROJECT_ROOT / 'backend' / 'telegram' / 'premarket_scheduler.py',
    PROJECT_ROOT / 'backend' / 'telegram' / 'lazy_command_runner.py',
    PROJECT_ROOT / 'backend' / 'orchestration' / 'telegram_listener.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'news_aggregator.py',
)


def _fail(msg: str) -> int:
    print(f'RSS_DISCOVERY_ADAPTER_52R_A2_FAIL: {msg}', file=sys.stderr)
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


def _article(**extra):
    row = {
        'provider_id': 'et_markets',
        'source_id': 'et_markets',
        'source_name': 'ET Markets',
        'url': 'https://economictimes.example.com/infosys-other-event',
        'title': 'Infosys reports other event',
        'published_at': PUB.isoformat(),
        'description': 'Bounded excerpt for Infosys.',
        'symbols': ['INFY'],
    }
    row.update(extra)
    return row


def _run_lock_subprocess(mode: str, article: dict | None = None) -> tuple[subprocess.CompletedProcess, dict]:
    args = [sys.executable, '-u', '-c', LOCK_SUBPROCESS_SCRIPT, mode]
    if article is not None:
        args.append(json.dumps(article, separators=(',', ':')))
    proc = subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        env=os.environ.copy(),
    )
    payload: dict = {}
    for line in (proc.stdout or '').splitlines():
        if line.startswith('LOCK_CHILD_RESULT '):
            payload = json.loads(line.removeprefix('LOCK_CHILD_RESULT '))
    return proc, payload


@contextmanager
def _isolated_discovery():
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


def test_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    allowed = {
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-C1B'),
        ('52R-D', 'AstraEdge 52R-D'),
    }
    mismatches = (
        ('52R-A2', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52R-A2'),
        ('52Q', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52Q'),
        ('52R-B1', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-B2'),
        ('52R-B2', 'AstraEdge 52R-C1A'),
        ('52R-C1A', 'AstraEdge 52R-C1B'),
        ('52R-C1B', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-D'),
        ('52R-D', 'AstraEdge 52R-C1B'),
    )
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'expected exact pair 52R-A2 / AstraEdge 52R-A2 or successor '
            f'52R-B1 / AstraEdge 52R-B1 or 52R-B2N / AstraEdge 52R-B2N or '
            f'52R-B2 / AstraEdge 52R-B2 or 52R-C1A / AstraEdge 52R-C1A or '
            f'52R-C1B / AstraEdge 52R-C1B or 52R-D / AstraEdge 52R-D, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    _pass('RSS_DISCOVERY_BUILD_OK')
    return 0


def test_no_network_ai_trading_imports() -> int:
    src = ADAPTER_PATH.read_text(encoding='utf-8')
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
    hits = [n for n in FORBIDDEN_IMPORT_NEEDLES if n in imported or n in src]
    # Allow the word only when it is a negative/documentation token in tests, not adapter.
    # Adapter source must not contain the forbidden module names as imports or calls.
    text_hits = []
    for needle in FORBIDDEN_IMPORT_NEEDLES:
        if needle in ('scanner',):
            # reject import-like forms only
            if re_search_import(src, needle):
                text_hits.append(needle)
            continue
        if re_search_import(src, needle) or f'import {needle}' in src or f'from {needle}' in src:
            text_hits.append(needle)
        elif needle in src and needle not in ('scanner',):
            # bare identifier still forbidden in adapter
            if needle in src:
                text_hits.append(needle)
    if text_hits:
        return _fail(f'adapter contains forbidden import/call tokens: {text_hits}')
    print('FORBIDDEN_IMPORT_EVIDENCE adapter_clean=True')
    _pass('RSS_DISCOVERY_NO_NETWORK_AI_TRADING_OK')
    return 0


def re_search_import(src: str, name: str) -> bool:
    import re
    return bool(re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(name)}\b', src, re.M))


def test_no_primary_promotion() -> int:
    src = ADAPTER_PATH.read_text(encoding='utf-8')
    if 'mark_primary_source_verified' in src:
        return _fail('adapter must not call or mention mark_primary_source_verified')
    if 'PRIMARY_SOURCE_VERIFIED' in src or 'VERIFICATION_PRIMARY' in src:
        return _fail('adapter must not inject PRIMARY_SOURCE_VERIFIED')
    if 'REJECTED' in src and 'VERIFICATION_REJECTED' in src:
        return _fail('adapter must not inject REJECTED')
    print('PRIMARY_PROMOTION_EVIDENCE adapter_calls=none')
    print('DISCOVERY_ONLY != verified catalyst')
    print('DISCOVERY_ONLY != trade confirmation')
    print('DISCOVERY_ONLY != learning winner')
    _pass('RSS_DISCOVERY_NO_PRIMARY_PROMOTION_OK')
    return 0


def test_single_writer_route() -> int:
    import backend.collectors.news_provider_registry as registry

    sig = inspect.signature(registry.run_unified_news_refresh)
    default = sig.parameters['ingest_discovery'].default
    if default is not False:
        return _fail(f'ingest_discovery default must be False, got {default!r}')

    tracker_src = TRACKER_PATH.read_text(encoding='utf-8')
    if 'ingest_discovery=True' not in tracker_src:
        return _fail('live_news_tracker must opt in with ingest_discovery=True')
    if tracker_src.count('ingest_discovery=True') != 1:
        return _fail('live_news_tracker must contain exactly one ingest_discovery=True')

    backend_hits: list[str] = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        if path.resolve() == ADAPTER_PATH.resolve():
            continue
        text = path.read_text(encoding='utf-8')
        if 'ingest_discovery=True' in text:
            backend_hits.append(str(path.relative_to(PROJECT_ROOT)).replace('\\', '/'))
    if backend_hits != ['backend/collectors/live_news_tracker.py']:
        return _fail(f'unexpected ingest_discovery=True production callers: {backend_hits}')

    for path in NON_WRITER_PATHS:
        text = path.read_text(encoding='utf-8')
        if 'ingest_discovery=True' in text:
            return _fail(f'{path.name} must not enable discovery ingest')
        if 'rss_discovery_adapter' in text:
            return _fail(f'{path.name} must not import rss_discovery_adapter')

    print('SINGLE_WRITER_EVIDENCE caller=backend/collectors/live_news_tracker.py default=False')
    _pass('RSS_DISCOVERY_SINGLE_WRITER_ROUTE_OK')
    return 0


def test_mapping(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        SOURCE_KIND_NEWS_PUBLISHER,
        VERIFICATION_DISCOVERY_ONLY,
        get_event,
        get_sighting,
        normalize_url,
    )
    from backend.news.rss_discovery_adapter import article_to_sighting_payload, ingest_registry_articles

    article = _article()
    payload = article_to_sighting_payload(article)
    if not payload:
        return _fail('trusted media article must map')
    print('SOURCE_KIND_MAPPING et_markets -> NEWS_PUBLISHER')
    if payload['source_kind'] != SOURCE_KIND_NEWS_PUBLISHER:
        return _fail(f'source_kind {payload["source_kind"]!r}')
    if payload['source_name'] != 'ET Markets':
        return _fail('source_name mapping failed')
    if payload['source_url'] != normalize_url(article['url']):
        return _fail('canonical URL mapping failed')
    if payload['source_headline'] != article['title']:
        return _fail('headline mapping failed')
    if payload['source_published_at'] != article['published_at']:
        return _fail('published timestamp mapping failed')
    if payload['bounded_excerpt'] != article['description']:
        return _fail('bounded excerpt mapping failed')
    if payload['symbols'] != ['INFY']:
        return _fail('symbols mapping failed')
    if payload['event_type'] != 'OTHER':
        return _fail('event_type must be OTHER')
    if payload['structured_facts'] != {}:
        return _fail('structured_facts must be {}')
    if payload['original_publisher'] != 'ET Markets':
        return _fail('original_publisher must copy source_name')

    stats = ingest_registry_articles([article])
    if stats.get('inserted') != 1:
        return _fail(f'expected one insert, got {stats}')
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    sighting = next(iter(store['sightings'].values()))
    event = next(iter(store['events'].values()))
    row = get_sighting(sighting['sighting_id'])
    ev = get_event(event['event_id'])
    if not row or not ev:
        return _fail('persisted mapping rows missing')
    if ev.get('verification_status') != VERIFICATION_DISCOVERY_ONLY:
        return _fail(f'mapped event status {ev.get("verification_status")!r}')
    _pass('RSS_DISCOVERY_MAPPING_OK')
    return 0


def test_exchange_discovery_only(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        SOURCE_KIND_EXCHANGE,
        VERIFICATION_DISCOVERY_ONLY,
        VERIFICATION_PRIMARY,
        get_event,
        get_sighting,
    )
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    nse = _article(
        provider_id='nse_rss',
        source_id='nse_rss',
        source_name='NSE Corporate Information',
        url='https://nsearchives.nseindia.com/corporate/INFY1.xml',
        title='NSE exchange announcement INFY',
        description='NSE exchange announcement INFY |SUBJECT: Exchange Filing',
        discovery_headline='NSE exchange announcement INFY — Exchange Filing',
        symbols=['INFY'],
    )
    bse = _article(
        provider_id='bse_rss',
        source_id='bse_rss',
        source_name='BSE Corporate Announcements',
        url='https://www.bseindia.com/xml-data/corpfiling/TCS1.xml',
        title='BSE exchange announcement TCS',
        symbols=['TCS'],
    )
    stats = ingest_registry_articles([nse, bse])
    print(f'SOURCE_KIND_MAPPING nse_rss -> EXCHANGE inserted={stats.get("inserted")}')
    print('SOURCE_KIND_MAPPING bse_rss -> EXCHANGE')
    if stats.get('inserted') != 2:
        return _fail(f'expected two exchange inserts, got {stats}')
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    kinds = {row['source_kind'] for row in store['sightings'].values()}
    statuses = {row['verification_status'] for row in store['events'].values()}
    primaries = {row.get('primary_source_url') for row in store['events'].values()}
    if kinds != {SOURCE_KIND_EXCHANGE}:
        return _fail(f'exchange kinds {kinds}')
    if statuses != {VERIFICATION_DISCOVERY_ONLY}:
        return _fail(f'exchange statuses {statuses}')
    if primaries != {'', None} and primaries - {'', None}:
        if any(p for p in primaries):
            return _fail(f'exchange primary_source_url {primaries}')
    for row in store['events'].values():
        if row.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail('exchange sighting became PRIMARY')
        ev = get_event(row['event_id'])
        if ev and ev.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail('exchange event became PRIMARY')
    for sid in store['sightings']:
        if not get_sighting(sid):
            return _fail('missing exchange sighting')
    _pass('RSS_DISCOVERY_EXCHANGE_DISCOVERY_ONLY_OK')
    return 0


def test_source_kind_boundary(ctx: dict) -> int:
    from backend.news.rss_discovery_adapter import article_to_sighting_payload, ingest_registry_articles

    skipped = []
    rows = []
    for pid, name in (
        ('rbi', 'RBI Press Releases'),
        ('sebi', 'SEBI Press Releases'),
        ('pib', 'PIB Government Releases'),
        ('mcx', 'MCX Press Releases'),
        ('unknown_xyz', 'Unknown Wire'),
    ):
        art = _article(provider_id=pid, source_id=pid, source_name=name, url=f'https://example.com/{pid}')
        payload = article_to_sighting_payload(art)
        if payload is not None:
            return _fail(f'{pid} must not coerce into a sighting')
        rows.append(art)
        skipped.append(pid)
        print(f'SKIPPED_PROVIDER {pid} reason=unsupported_source_kind')
    stats = ingest_registry_articles(rows)
    if stats.get('inserted') != 0:
        return _fail('unsupported providers must not insert')
    if stats.get('skipped_unsupported_source_kind') != 5:
        return _fail(f'unsupported skip count {stats}')
    _pass('RSS_DISCOVERY_SOURCE_KIND_BOUNDARY_OK')
    return 0


def test_required_fields_fail_closed(ctx: dict) -> int:
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    cases = [
        ('missing_url', _article(url='', link=''), 'skipped_missing_url'),
        ('missing_headline', _article(title='', headline=''), 'skipped_missing_headline'),
        ('missing_source_name', _article(source_name='', source=''), 'skipped_missing_source_name'),
        ('missing_timestamp', _article(published_at=None, published=None), 'skipped_missing_timestamp'),
        ('missing_symbols', _article(symbols=None, tickers=None), 'skipped_missing_symbols'),
        ('empty_symbols', _article(symbols=[], tickers=[]), 'skipped_missing_symbols'),
        ('malformed_container', ['not', 'a', 'dict'], 'skipped_malformed'),
    ]
    print('MISSING_FIELD_TABLE')
    for label, payload, stat_key in cases:
        if label == 'malformed_container':
            stats = ingest_registry_articles(payload)  # type: ignore[arg-type]
            ok = stats.get('skipped_malformed', 0) >= 1 and stats.get('inserted', 0) == 0
        else:
            stats = ingest_registry_articles([payload])
            ok = stats.get(stat_key, 0) >= 1 and stats.get('inserted', 0) == 0
        print(f'  {label} -> {stat_key} ok={ok} stats={ {k: stats.get(k) for k in (stat_key, "inserted", "errors")} }')
        if not ok:
            return _fail(f'{label} did not fail closed: {stats}')
    if ctx['store_path'].exists():
        return _fail('fail-closed rows must not create a discovery store')
    _pass('RSS_DISCOVERY_REQUIRED_FIELDS_FAIL_CLOSED_OK')
    return 0


def test_sighting_idempotence(ctx: dict) -> int:
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    art = _article(url='https://economictimes.example.com/idempotent-1')
    first = ingest_registry_articles([art])
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    sid = next(iter(store['sightings']))
    second = ingest_registry_articles([art])
    store2 = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    print(
        'SIGHTING_IDENTITY_EVIDENCE '
        f'same_source+url+headline+date+publisher sighting_id={sid} '
        f'inserted={first.get("inserted")} deduplicated={second.get("deduplicated")} '
        f'rows={len(store2["sightings"])}'
    )
    if first.get('inserted') != 1:
        return _fail(f'first ingest should insert, got {first}')
    if second.get('deduplicated') != 1 or second.get('inserted') != 0:
        return _fail(f'second ingest should dedupe, got {second}')
    if len(store2['sightings']) != 1:
        return _fail('duplicate sighting row created')
    if next(iter(store2['sightings'])) != sid:
        return _fail('sighting_id changed on repeat ingest')
    _pass('RSS_DISCOVERY_SIGHTING_IDEMPOTENCE_OK')
    return 0


def test_source_identity_truth(ctx: dict) -> int:
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    shared_url = 'https://wire.example.com/same-url-story'
    a = _article(
        provider_id='et_markets',
        source_name='ET Markets',
        url=shared_url,
        title='Shared URL headline identity',
    )
    b = _article(
        provider_id='ndtv_profit',
        source_name='NDTV Profit',
        url=shared_url,
        title='Shared URL headline identity',
    )
    stats = ingest_registry_articles([a, b])
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    names = sorted(row['source_name'] for row in store['sightings'].values())
    print(
        'SIGHTING_IDENTITY_EVIDENCE different_source/publisher '
        f'count={len(store["sightings"])} names={names} inserted={stats.get("inserted")}'
    )
    if stats.get('inserted') != 2:
        return _fail(f'different canonical sources may create distinct sightings, got {stats}')
    if len(store['sightings']) != 2:
        return _fail('URL-only collapse is not the 52R-A1 contract')
    _pass('RSS_DISCOVERY_SOURCE_IDENTITY_TRUTH_OK')
    return 0


def test_multi_source_truth(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_MULTI_SOURCE,
        get_event,
    )
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    headline = 'Canonical identical headline for conservative grouping'
    a = _article(
        provider_id='et_markets',
        source_name='ET Markets',
        url='https://economictimes.example.com/ms-a',
        title=headline,
        symbols=['INFY'],
    )
    b = _article(
        provider_id='ndtv_profit',
        source_name='NDTV Profit',
        url='https://ndtv.example.com/ms-b',
        title=headline,
        symbols=['INFY'],
    )
    stats = ingest_registry_articles([a, b])
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    events = store['events']
    sightings = store['sightings']
    if len(events) != 1:
        return _fail(f'expected one canonical event, got {len(events)}')
    if len(sightings) != 2:
        return _fail(f'expected two sightings, got {len(sightings)}')
    event = next(iter(events.values()))
    ev = get_event(event['event_id'])
    print(
        'MULTI_SOURCE_EVIDENCE '
        f'events=1 sightings=2 source_count={ev.get("source_count")} '
        f'status={ev.get("verification_status")} primary={ev.get("primary_source_url")!r} '
        f'inserted={stats.get("inserted")}'
    )
    if ev.get('source_count') != 2:
        return _fail(f'source_count {ev.get("source_count")}')
    if ev.get('verification_status') != VERIFICATION_MULTI_SOURCE:
        return _fail(f'status {ev.get("verification_status")!r}')
    if ev.get('primary_source_url') not in ('', None):
        return _fail(f'primary_source_url must be empty, got {ev.get("primary_source_url")!r}')
    _pass('RSS_DISCOVERY_MULTI_SOURCE_TRUTH_OK')
    return 0


def test_empty_batch_noop(ctx: dict) -> int:
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    path = ctx['store_path']
    if path.exists():
        path.unlink()
    none_stats = ingest_registry_articles(None)
    empty_stats = ingest_registry_articles([])
    invalid_stats = ingest_registry_articles([
        _article(provider_id='rbi', source_id='rbi', source_name='RBI'),
        'bad',
        _article(symbols=[]),
    ])
    print(
        'EMPTY_BATCH_BYTE_IDENTITY absent_store '
        f'exists={path.exists()} none_inserted={none_stats.get("inserted")} '
        f'empty_inserted={empty_stats.get("inserted")} invalid_inserted={invalid_stats.get("inserted")}'
    )
    if path.exists():
        return _fail('empty/outage batches must not create the discovery store')
    if any(s.get('inserted') for s in (none_stats, empty_stats, invalid_stats)):
        return _fail('empty/outage batches must insert zero')

    seed = ingest_registry_articles([_article(url='https://economictimes.example.com/seed-empty')])
    if seed.get('inserted') != 1:
        return _fail('seed insert failed for empty-batch identity')
    before = path.read_bytes()
    ingest_registry_articles(None)
    ingest_registry_articles([])
    ingest_registry_articles([_article(symbols=[]), {'provider_id': 'sebi'}])
    after = path.read_bytes()
    print(f'EMPTY_BATCH_BYTE_IDENTITY existing_store unchanged={before == after} bytes={len(before)}')
    if before != after:
        return _fail('empty/outage ingest mutated existing store')
    _pass('RSS_DISCOVERY_EMPTY_BATCH_NOOP_OK')
    return 0


def test_unhealthy_store_immutable(ctx: dict) -> int:
    from backend.news import broker_discovery_foundation as bdf
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    path = ctx['store_path']
    path.parent.mkdir(parents=True, exist_ok=True)
    eligible = [_article(url='https://economictimes.example.com/unhealthy')]

    unread = b'\xff\xfe UNREADABLE'
    path.write_bytes(unread)
    before = path.read_bytes()
    stats_u = ingest_registry_articles(eligible)
    after = path.read_bytes()
    print(
        f'UNHEALTHY_STORE_BYTE_IDENTITY UNREADABLE unchanged={before == after} '
        f'health={stats_u.get("store_health")} unhealthy={stats_u.get("store_unhealthy")} '
        f'inserted={stats_u.get("inserted")}'
    )
    if before != after or stats_u.get('inserted') != 0 or not stats_u.get('store_unhealthy'):
        return _fail(f'UNREADABLE store was mutated or ingested: {stats_u}')

    path.write_text('{not-json', encoding='utf-8')
    before = path.read_bytes()
    stats_m = ingest_registry_articles(eligible)
    after = path.read_bytes()
    print(
        f'UNHEALTHY_STORE_BYTE_IDENTITY MALFORMED unchanged={before == after} '
        f'health={stats_m.get("store_health")} unhealthy={stats_m.get("store_unhealthy")}'
    )
    if before != after or stats_m.get('inserted') != 0 or not stats_m.get('store_unhealthy'):
        return _fail(f'MALFORMED store was mutated or ingested: {stats_m}')

    good = bdf.build_canonical_event(
        event_type='OTHER',
        symbols=['IMP'],
        canonical_headline='immutable partial',
        published_at=PUB,
        structured_facts={},
    )
    good['source_count'] = 0
    bad_row = dict(good)
    bad_row['symbols'] = [{}]
    payload = {
        'schema_version': '52R-A1',
        'events': {good['event_id']: bad_row},
        'sightings': {},
        'updated_at': good['updated_at'],
    }
    path.write_text(json.dumps(payload), encoding='utf-8')
    before = path.read_bytes()
    stats_p = ingest_registry_articles(eligible)
    after = path.read_bytes()
    print(
        f'UNHEALTHY_STORE_BYTE_IDENTITY PARTIAL unchanged={before == after} '
        f'health={stats_p.get("store_health")} unhealthy={stats_p.get("store_unhealthy")}'
    )
    if before != after or stats_p.get('inserted') != 0 or not stats_p.get('store_unhealthy'):
        return _fail(f'PARTIAL store was mutated or ingested: {stats_p}')
    _pass('RSS_DISCOVERY_UNHEALTHY_STORE_IMMUTABLE_OK')
    return 0


def test_batch_lock(ctx: dict) -> int:
    from backend.collectors.news_provider_registry import run_unified_news_refresh
    from backend.news.rss_discovery_adapter import (
        _BatchLock,
        discovery_lock_path,
        ingest_registry_articles,
    )

    path = ctx['store_path']
    if path.exists():
        path.unlink()
    art = _article(url='https://economictimes.example.com/lock-1')
    lock = _BatchLock(discovery_lock_path())
    if not lock.try_acquire():
        return _fail('first owner must acquire the batch lock')
    try:
        contended = ingest_registry_articles([art])
        print(
            f'BATCH_LOCK_CONTENTION first_owner=True second_lock_contended={contended.get("lock_contended")} '
            f'second_inserted={contended.get("inserted")} store_exists={path.exists()}'
        )
        if contended.get('lock_contended') is not True:
            return _fail('second ingest must report lock_contended=True')
        if contended.get('inserted') != 0:
            return _fail('contended ingest must perform zero writes')
        if path.exists():
            return _fail('contended ingest must not create/write the store')

        contender_proc, contender = _run_lock_subprocess('ingest', art)
        child_stats = contender.get('stats') or {}
        if contender_proc.returncode != 0 or not contender:
            return _fail(
                'cross-process contender failed unexpectedly: '
                f'rc={contender_proc.returncode} stdout={contender_proc.stdout!r} stderr={contender_proc.stderr!r}'
            )
        print(
            f'BATCH_LOCK_CROSS_PROCESS_CONTENTION owner_pid={os.getpid()} '
            f'contender_pid={contender.get("pid")} lock_contended={child_stats.get("lock_contended")}'
        )
        if child_stats.get('lock_contended') is not True:
            return _fail(f'cross-process contender acquired live owner lock: {child_stats}')
        if child_stats.get('inserted') != 0 or child_stats.get('deduplicated') != 0:
            return _fail(f'cross-process contender performed discovery writes: {child_stats}')
        if path.exists():
            return _fail('cross-process contender created or corrupted the discovery store')
        if lock._fd is None:
            return _fail('cross-process contention displaced the live holder')

        lock._write_metadata(started_at=time.time() - 10_000)
        old_proc, old_contender = _run_lock_subprocess('acquire')
        if old_proc.returncode != 0 or not old_contender:
            return _fail(
                'old-metadata contender failed unexpectedly: '
                f'rc={old_proc.returncode} stdout={old_proc.stdout!r} stderr={old_proc.stderr!r}'
            )
        if old_contender.get('acquired') is not False or lock._fd is None:
            return _fail(f'old metadata evicted a live OS-lock owner: {old_contender}')
        _pass('BATCH_LOCK_LIVE_OWNER_NOT_EVICTED_OK')
    finally:
        lock.release()

    after_release = ingest_registry_articles([art])
    if after_release.get('inserted') != 1:
        return _fail(f'ingest after release must proceed, got {after_release}')

    crash_proc, crashed = _run_lock_subprocess('crash')
    if crash_proc.returncode != 0 or crashed.get('acquired') is not True:
        return _fail(
            'crash holder did not acquire before exit: '
            f'rc={crash_proc.returncode} stdout={crash_proc.stdout!r} stderr={crash_proc.stderr!r}'
        )
    after_crash = _BatchLock(discovery_lock_path())
    if not after_crash.try_acquire():
        return _fail('OS lock was not released automatically when holder process exited')
    after_crash.release()
    _pass('BATCH_LOCK_CRASH_RELEASE_OK')

    stale_file = discovery_lock_path()
    stale_file.write_text(
        json.dumps({'pid': 999999999, 'started_at': time.time() - 10_000}),
        encoding='utf-8',
    )
    stale_stats = ingest_registry_articles([_article(url='https://economictimes.example.com/lock-stale')])
    print(
        f'BATCH_LOCK_STALE_FILE_IGNORED cleared={stale_stats.get("lock_stale_cleared")} '
        f'inserted={stale_stats.get("inserted")} contended={stale_stats.get("lock_contended")} '
        f'lock_file_remains={stale_file.is_file()}'
    )
    if stale_stats.get('lock_contended'):
        return _fail('unlocked stale diagnostic file must not contend')
    if stale_stats.get('inserted') != 1:
        return _fail('unlocked stale diagnostic file blocked ingestion')
    if stale_stats.get('lock_stale_cleared') or not stale_file.is_file():
        return _fail('advisory lock correctness must not delete the stable lock file')

    _pass('RSS_DISCOVERY_BATCH_LOCK_CROSS_PROCESS_OK')

    with patch(
        'backend.collectors.news_provider_registry.get_enabled_providers',
        return_value=[],
    ), patch(
        'backend.news.rss_discovery_adapter.ingest_registry_articles',
        side_effect=RuntimeError('adapter boom'),
    ):
        result = run_unified_news_refresh(ingest_discovery=True)
    if result.get('discovery', {}).get('error_type') != 'RuntimeError':
        return _fail(f'adapter failure must be isolated with type, got {result.get("discovery")}')
    if 'ok' not in result:
        return _fail('news refresh path must still return')
    print('BATCH_LOCK_NEWS_REFRESH_ISOLATED error_type=RuntimeError')
    _pass('RSS_DISCOVERY_BATCH_LOCK_OK')
    return 0


def test_content_boundary(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import MAX_EXCERPT_LENGTH, get_sighting
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    huge = 'x' * 800
    art = _article(
        url='https://economictimes.example.com/content-boundary',
        description=huge,
        article_body='<html><body>SECRET_BODY</body></html>',
        full_article='FULL_ARTICLE_SECRET',
        html='<div>nope</div>',
        raw_html='<p>nope</p>',
        cookies='sid=abc',
        auth_token='tok',
        browser_state={'x': 1},
        session='sess',
    )
    stats = ingest_registry_articles([art])
    if stats.get('inserted') != 1:
        return _fail(f'oversized plain excerpt should persist bounded, got {stats}')
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    blob = json.dumps(store)
    row = next(iter(store['sightings'].values()))
    loaded = get_sighting(row['sighting_id'])
    print(
        'CONTENT_BOUNDARY_EVIDENCE '
        f'excerpt_len={len(loaded["bounded_excerpt"])} max={MAX_EXCERPT_LENGTH} '
        f'article_body={loaded.get("article_body")!r}'
    )
    if len(loaded['bounded_excerpt']) > MAX_EXCERPT_LENGTH:
        return _fail('bounded_excerpt exceeded max')
    if loaded.get('article_body') not in (None, ''):
        return _fail('article_body retained')
    for secret in ('SECRET_BODY', 'FULL_ARTICLE_SECRET', 'sid=abc', 'tok', '<html'):
        if secret in blob:
            return _fail(f'forbidden content persisted: {secret}')
    for bad in ('article_body', 'full_article', 'html', 'raw_html', 'cookies', 'auth_token', 'browser_state', 'session'):
        if loaded.get(bad) not in (None, '', {}) and bad in loaded and loaded.get(bad) not in (None, ''):
            if bad == 'article_body':
                continue
            if loaded.get(bad):
                return _fail(f'retained forbidden field {bad}')
    _pass('RSS_DISCOVERY_CONTENT_BOUNDARY_OK')
    return 0


def test_public_boundary(ctx: dict) -> int:
    global RAW_EXCEPTION_ESCAPES
    from backend.news.rss_discovery_adapter import ingest_registry_articles, article_to_sighting_payload

    cases = [
        ('surrogate_headline', _article(title='bad\ud800headline')),
        ('surrogate_source', _article(source_name='src\ud800')),
        ('surrogate_url', _article(url='https://example.com/\ud800')),
        ('bad_timestamp', _article(published_at='not-a-date')),
        ('container_fields', _article(source_name={'x': 1})),
        ('boolean_fields', _article(title=True, url=True, source_name=True)),
        ('numeric_fields', _article(title=123, source_name=456, url=789)),
        ('malformed_row', 42),
    ]
    print('RAW_EXCEPTION_MATRIX')
    for label, payload in cases:
        try:
            if isinstance(payload, dict):
                article_to_sighting_payload(payload)
                stats = ingest_registry_articles([payload])
            else:
                stats = ingest_registry_articles([payload])  # type: ignore[list-item]
            inserted = stats.get('inserted', 0)
            skipped = stats.get('skipped', 0) + stats.get('errors', 0)
            print(f'  {label} inserted={inserted} skipped_or_errors={skipped}')
            if inserted:
                RAW_EXCEPTION_ESCAPES += 1
                return _fail(f'{label} inserted instead of fail-closed')
        except Exception as exc:
            RAW_EXCEPTION_ESCAPES += 1
            print(f'  {label} RAW_ESCAPE {type(exc).__name__}')
            return _fail(f'{label} raw exception escape: {type(exc).__name__}: {exc}')
    print(f'RSS_DISCOVERY_RAW_EXCEPTION_ESCAPE_COUNT={RAW_EXCEPTION_ESCAPES}')
    _pass('RSS_DISCOVERY_PUBLIC_BOUNDARY_OK')
    return 0


def test_repo_data_safe(git_before: str, git_after: str) -> int:
    if git_after:
        return _fail(f'repository data/ is dirty: {git_after}')
    if git_before:
        return _fail(f'repository data/ was dirty before tests: {git_before}')
    print('DATA_STATUS clean')
    _pass('RSS_DISCOVERY_REPO_DATA_SAFE_OK')
    return 0


def main() -> int:
    from scripts._test_runtime_isolation import repo_data_root, snapshot_data_tree

    rc = test_build_identity()
    if rc:
        return rc
    rc = test_no_network_ai_trading_imports()
    if rc:
        return rc
    rc = test_no_primary_promotion()
    if rc:
        return rc
    rc = test_single_writer_route()
    if rc:
        return rc

    git_before = _git_data_status()
    before = snapshot_data_tree()
    real_root = repo_data_root().resolve()
    leaks: list[str] = []
    original_read_text = Path.read_text
    original_open = Path.open

    def _is_repo(path: Path) -> bool:
        try:
            path.resolve().relative_to(real_root)
            return True
        except (ValueError, OSError):
            return False

    def _guard_read_text(self, *a, **k):
        if _is_repo(self):
            leaks.append(str(self))
            raise RuntimeError(f'repo data read blocked: {self}')
        return original_read_text(self, *a, **k)

    def _guard_open(self, *a, **k):
        if _is_repo(self):
            leaks.append(str(self))
            raise RuntimeError(f'repo data open blocked: {self}')
        return original_open(self, *a, **k)

    with _isolated_discovery() as ctx, patch.object(Path, 'read_text', _guard_read_text), patch.object(
        Path, 'open', _guard_open
    ):
        for fn in (
            test_mapping,
            test_exchange_discovery_only,
            test_source_kind_boundary,
            test_required_fields_fail_closed,
            test_sighting_idempotence,
            test_source_identity_truth,
            test_multi_source_truth,
            test_empty_batch_noop,
            test_unhealthy_store_immutable,
            test_batch_lock,
            test_content_boundary,
            test_public_boundary,
        ):
            # Fresh store/lock per mutating test except where the test manages bytes.
            if fn in (
                test_mapping,
                test_exchange_discovery_only,
                test_source_kind_boundary,
                test_required_fields_fail_closed,
                test_sighting_idempotence,
                test_source_identity_truth,
                test_multi_source_truth,
                test_empty_batch_noop,
                test_unhealthy_store_immutable,
                test_batch_lock,
                test_content_boundary,
                test_public_boundary,
            ):
                store = ctx['store_path']
                if store.exists():
                    store.unlink()
                lock = ctx['lock_path']
                if lock.exists():
                    lock.unlink()
            rc = fn(ctx)
            if rc:
                return rc

    if leaks:
        return _fail(f'repository data leak: {leaks[:5]}')
    after = snapshot_data_tree()
    if before != after:
        return _fail('repository data/ snapshot changed')
    git_after = _git_data_status()
    rc = test_repo_data_safe(git_before, git_after)
    if rc:
        return rc

    required = (
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
    )
    missing = [m for m in required if m not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('RSS_DISCOVERY_ADAPTER_52R_A2_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
