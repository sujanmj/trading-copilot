#!/usr/bin/env python3
"""AstraEdge 52R-B1 — governed primary source verifier (isolated)."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
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
LATER = datetime(2099, 8, 1, 10, 15, 0, tzinfo=IST)
PASS_MARKERS: list[str] = []
RAW_EXCEPTION_ESCAPES = 0

VERIFIER_PATH = PROJECT_ROOT / 'backend' / 'news' / 'primary_source_verifier.py'
NSE_WAF_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'nse_announcements.py'

LOCK_SUBPROCESS_SCRIPT = r'''
import json
import os
import sys

from backend.news.primary_source_verifier import verify_linked_primary_sighting
from backend.news.rss_discovery_adapter import _BatchLock, discovery_lock_path

mode = sys.argv[1]
result = {'pid': os.getpid(), 'mode': mode}
if mode == 'verify':
    result['result'] = verify_linked_primary_sighting(sys.argv[2], sys.argv[3])
elif mode == 'acquire':
    lock = _BatchLock(discovery_lock_path())
    result['acquired'] = lock.try_acquire()
    if result['acquired']:
        lock.release()
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

TRADING_COUPLING_PATHS = (
    PROJECT_ROOT / 'backend' / 'intelligence' / 'stock_catalyst_radar.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'trade_card_engine.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'opening_rally_radar.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'weekly_signal_capture.py',
    PROJECT_ROOT / 'backend' / 'learning_engine.py',
    PROJECT_ROOT / 'backend' / 'outcome_tracker.py',
    PROJECT_ROOT / 'backend' / 'ai_router.py',
    PROJECT_ROOT / 'backend' / 'analyzers' / 'stock_scanner.py',
)

PRODUCTION_SCAN_SKIP = {
    VERIFIER_PATH.resolve(),
}


def _fail(msg: str) -> int:
    print(f'PRIMARY_SOURCE_VERIFIER_52R_B1_FAIL: {msg}', file=sys.stderr)
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
        'source_url': 'https://nsearchives.nseindia.com/corporate/INFY_ANNOUNCEMENT_1.xml',
        'source_headline': 'Infosys board meeting outcome',
        'source_published_at': PUB,
        'original_publisher': 'NSE',
        'bounded_excerpt': 'Board meeting outcome for Infosys.',
        'symbols': ['INFY'],
        'event_type': 'OTHER',
        'structured_facts': {},
    }
    row.update(extra)
    return row


def _publisher(*, source_name: str, source_url: str, **extra):
    row = {
        'source_name': source_name,
        'source_kind': 'NEWS_PUBLISHER',
        'source_url': source_url,
        'source_headline': 'Infosys other event publisher copy',
        'source_published_at': PUB,
        'original_publisher': source_name,
        'bounded_excerpt': 'Publisher copy.',
        'symbols': ['INFY'],
        'event_type': 'OTHER',
        'structured_facts': {},
    }
    row.update(extra)
    return row


def _run_lock_subprocess(mode: str, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
    args = [sys.executable, '-u', '-c', LOCK_SUBPROCESS_SCRIPT, mode, *extra]
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
def _isolated_verifier():
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

    allowed = {('52R-B1', 'AstraEdge 52R-B1'), ('52R-B2N', 'AstraEdge 52R-B2N')}
    mismatches = (
        ('52R-B1', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-B2N'),
    )
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'expected exact pair 52R-B1 / AstraEdge 52R-B1 or successor '
            f'52R-B2N / AstraEdge 52R-B2N, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    print(f'BUILD_PAIR {BUILD_STAGE} / {TELEGRAM_BUILD}')
    return 0


def test_no_network_ai_trading() -> int:
    src = VERIFIER_PATH.read_text(encoding='utf-8')
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
    text_hits = []
    for needle in FORBIDDEN_IMPORT_NEEDLES:
        if re.search(rf'(?:^|\s)(?:import|from)\s+{re.escape(needle)}\b', src, re.M):
            text_hits.append(needle)
        elif needle in imported:
            text_hits.append(needle)
    if text_hits:
        return _fail(f'verifier contains forbidden import/call tokens: {text_hits}')
    if 'SequenceMatcher' in src or 'embedding' in src.casefold():
        return _fail('verifier must not fuzzy-match or embed headlines')
    print('FORBIDDEN_IMPORT_EVIDENCE verifier_clean=True')
    _pass('PRIMARY_VERIFIER_NO_NETWORK_AI_TRADING_OK')
    return 0


def test_no_nse_waf_path() -> int:
    src = VERIFIER_PATH.read_text(encoding='utf-8')
    if 'nse_announcements' in src:
        return _fail('verifier must not mention nse_announcements')
    if not NSE_WAF_PATH.is_file():
        return _fail('expected nse_announcements.py to exist as the untouched WAF collector')
    print('NSE_WAF_PATH_EVIDENCE imported=False called=False')
    _pass('PRIMARY_VERIFIER_NO_NSE_WAF_PATH_OK')
    return 0


def test_dormant_production() -> int:
    hits: list[str] = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        if path.resolve() in PRODUCTION_SCAN_SKIP:
            continue
        text = path.read_text(encoding='utf-8')
        if 'primary_source_verifier' in text or 'verify_linked_primary_sighting' in text:
            hits.append(str(path.relative_to(PROJECT_ROOT)).replace('\\', '/'))
    if hits:
        return _fail(f'production callers of governed verifier: {hits}')
    tracker = (PROJECT_ROOT / 'backend/collectors/live_news_tracker.py').read_text(encoding='utf-8')
    registry = (PROJECT_ROOT / 'backend/collectors/news_provider_registry.py').read_text(encoding='utf-8')
    if 'verify_primary' in tracker or 'verify_primary' in registry:
        return _fail('live tracker/registry must not opt into primary verification')
    print('PRODUCTION_CALLERS none')
    _pass('PRIMARY_VERIFIER_DORMANT_PRODUCTION_OK')
    return 0


def test_no_trading_coupling() -> int:
    src = VERIFIER_PATH.read_text(encoding='utf-8')
    for needle in (
        'stock_catalyst_radar',
        'stock_scanner',
        'opening_rally_radar',
        'trade_card_engine',
        'weekly_signal_capture',
        'candidate_outcome_learning',
        'learning_engine',
        'outcome_tracker',
        'ai_router',
    ):
        if needle in src:
            return _fail(f'verifier couples to {needle}')
    for path in TRADING_COUPLING_PATHS:
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        if 'primary_source_verifier' in text or 'verify_linked_primary_sighting' in text:
            return _fail(f'{path.name} must not import the B1 verifier')
    print('TRADING_COUPLING_EVIDENCE none')
    _pass('PRIMARY_VERIFIER_NO_TRADING_COUPLING_OK')
    return 0


def test_exchange_promotion(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import (
        CLASS_EXCHANGE_PRIMARY,
        verify_linked_primary_sighting,
    )

    seeded = upsert_sighting(_exchange())
    result = verify_linked_primary_sighting(
        seeded['event_id'],
        seeded['sighting_id'],
        now=PUB,
    )
    event = get_event(seeded['event_id'])
    print(
        'EXCHANGE_PROMOTION_EVIDENCE '
        f'ok={result.get("ok")} promoted={result.get("promoted")} '
        f'class={result.get("verification_class")} '
        f'status={event.get("verification_status") if event else None} '
        f'url={event.get("primary_source_url") if event else None}'
    )
    if not result.get('ok') or not result.get('promoted'):
        return _fail(f'valid EXCHANGE sighting must promote: {result}')
    if result.get('verification_class') != CLASS_EXCHANGE_PRIMARY:
        return _fail(f'verification_class {result.get("verification_class")!r}')
    if not event or event.get('verification_status') != VERIFICATION_PRIMARY:
        return _fail(f'event status {event}')
    if event.get('primary_source_url') != seeded['sighting']['source_url']:
        return _fail('primary URL must come from the linked sighting')
    _pass('PRIMARY_EXCHANGE_PROMOTION_OK')
    return 0


def test_publisher_rejected(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_DISCOVERY_ONLY,
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    publishers = (
        ('ET Markets', 'https://economictimes.example.com/et-1'),
        ('Mint', 'https://mint.example.com/mint-1'),
        ('NDTV Profit', 'https://ndtv.example.com/ndtv-1'),
        ('Investing.com India', 'https://investing.example.com/inv-1'),
    )
    print('PUBLISHER_REJECTION_TABLE')
    for name, url in publishers:
        seeded = upsert_sighting(_publisher(
            source_name=name,
            source_url=url,
            source_headline=f'{name} unique headline',
            symbols=['PUB1'],
        ))
        result = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
        event = get_event(seeded['event_id'])
        print(f'  {name} reason={result.get("reason")} status={event.get("verification_status") if event else None}')
        if result.get('ok') or result.get('promoted'):
            return _fail(f'{name} must not promote')
        if event and event.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail(f'{name} became PRIMARY')
        if event and event.get('verification_status') != VERIFICATION_DISCOVERY_ONLY:
            return _fail(f'{name} unexpected status {event.get("verification_status")!r}')

    spoof = upsert_sighting(_publisher(
        source_name='ET Markets Official Looking',
        source_url='https://www.nseindia.com/corporate/INFY-publisher.xml',
        source_headline='Publisher with official looking host',
        symbols=['PUB2'],
    ))
    spoof_result = verify_linked_primary_sighting(spoof['event_id'], spoof['sighting_id'])
    spoof_event = get_event(spoof['event_id'])
    print(
        'NEWS_PUBLISHER + official-looking host != PRIMARY '
        f'reason={spoof_result.get("reason")} status={spoof_event.get("verification_status") if spoof_event else None}'
    )
    if spoof_result.get('ok') or (spoof_event and spoof_event.get('verification_status') == VERIFICATION_PRIMARY):
        return _fail('NEWS_PUBLISHER + NSE host must not become PRIMARY')

    ir = upsert_sighting(_exchange(
        source_name='Infosys IR',
        source_kind='COMPANY_IR',
        source_url='https://www.nseindia.com/corporate/INFY-ir.xml',
        source_headline='Company IR must not auto-promote in B1',
        symbols=['IR1'],
    ))
    ir_result = verify_linked_primary_sighting(ir['event_id'], ir['sighting_id'])
    print(f'COMPANY_IR_B1_NOT_IMPLEMENTED reason={ir_result.get("reason")} class={ir_result.get("verification_class")}')
    if ir_result.get('ok') or ir_result.get('promoted'):
        return _fail('COMPANY_IR must not be an active B1 promotion path')
    _pass('PRIMARY_PUBLISHER_REJECTED_OK')
    return 0


def test_secondary_multi_source_not_primary(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_MULTI_SOURCE,
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    headline = 'Canonical identical headline for conservative grouping'
    et = upsert_sighting(_publisher(
        source_name='ET Markets',
        source_url='https://economictimes.example.com/ms-et',
        source_headline=headline,
        symbols=['INFY'],
    ))
    mint = upsert_sighting(_publisher(
        source_name='Mint',
        source_url='https://mint.example.com/ms-mint',
        source_headline=headline,
        symbols=['INFY'],
    ))
    if et['event_id'] != mint['event_id']:
        return _fail('ET + Mint must group to one event')
    event = get_event(et['event_id'])
    if not event or event.get('verification_status') != VERIFICATION_MULTI_SOURCE:
        return _fail(f'expected MULTI_SOURCE_CONFIRMED, got {event}')
    print(
        'MULTI_SOURCE_EVIDENCE ET+Mint '
        f'status={event.get("verification_status")} source_count={event.get("source_count")}'
    )
    for label, row in (('ET Markets', et), ('Mint', mint)):
        result = verify_linked_primary_sighting(row['event_id'], row['sighting_id'])
        print(f'  {label} verify reason={result.get("reason")} ok={result.get("ok")}')
        if result.get('ok') or result.get('promoted'):
            return _fail(f'{label} publisher sighting must not promote MULTI_SOURCE')
    still = get_event(et['event_id'])
    if not still or still.get('verification_status') != VERIFICATION_MULTI_SOURCE:
        return _fail(f'MULTI_SOURCE must remain, got {still}')
    if still.get('verification_status') == VERIFICATION_PRIMARY:
        return _fail('MULTI_SOURCE must not become PRIMARY via publisher sightings')
    _pass('SECONDARY_MULTI_SOURCE_NOT_PRIMARY_OK')
    return 0


def test_host_policy(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import get_event, upsert_sighting
    from backend.news.primary_source_verifier import (
        classify_exchange_primary_url,
        verify_linked_primary_sighting,
    )

    persistable = (
        ('suffix', 'https://nseindia.com.attacker.example/corporate/INFY.xml'),
        ('path_host', 'https://evil.example/nseindia.com/corporate/INFY.xml'),
        ('http', 'http://www.nseindia.com/corporate/INFY.xml'),
        ('ipv4', 'https://127.0.0.1/corporate/INFY.xml'),
        ('ipv6', 'https://[::1]/corporate/INFY.xml'),
    )
    print('HOST_POLICY_PERSISTED_TABLE')
    for label, url in persistable:
        seeded = upsert_sighting(_exchange(
            source_url=url,
            source_headline=f'Host policy {label}',
            symbols=['HST1'],
        ))
        result = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
        event = get_event(seeded['event_id'])
        print(f'  {label} url={url} reason={result.get("reason")} ok={result.get("ok")}')
        if result.get('ok') or result.get('promoted'):
            return _fail(f'{label} must fail host policy')
        if event and event.get('primary_source_url'):
            return _fail(f'{label} wrote a primary URL')

    classifier_only = (
        'https://www.bseindia.com@evil.example/corporate/INFY.xml',
        'file://www.nseindia.com/corporate/INFY.xml',
        'javascript:alert(1)',
        'https://localhost/corporate/INFY.xml',
    )
    print('HOST_POLICY_CLASSIFIER_TABLE')
    for raw in classifier_only:
        info = classify_exchange_primary_url(raw)
        print(f'  {raw!r} ok={info.get("ok")} reason={info.get("reason")}')
        if info.get('ok'):
            return _fail(f'classifier accepted {raw!r}')
    _pass('PRIMARY_HOST_POLICY_OK')
    return 0


def test_generic_feed_rejected(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import get_event, upsert_sighting
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    cases = (
        ('nse_rss_feed', 'https://www.nseindia.com/rss-feed'),
        ('bse_notices', 'https://www.bseindia.com/data/xml/notices.xml'),
        ('nse_root', 'https://www.nseindia.com/'),
        ('nse_empty_path', 'https://www.nseindia.com'),
        ('bse_root', 'https://bseindia.com/'),
    )
    print('GENERIC_FEED_REJECTION_TABLE')
    for label, url in cases:
        seeded = upsert_sighting(_exchange(
            source_url=url,
            source_headline=f'Generic feed {label}',
            symbols=['GEN1'],
        ))
        result = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
        event = get_event(seeded['event_id'])
        print(f'  {label} reason={result.get("reason")} ok={result.get("ok")}')
        if result.get('ok') or result.get('promoted'):
            return _fail(f'{label} generic feed must not verify')
        if result.get('reason') != 'generic_feed_rejected':
            return _fail(f'{label} expected generic_feed_rejected, got {result}')
        if event and event.get('primary_source_url'):
            return _fail(f'{label} wrote primary URL')
    _pass('PRIMARY_GENERIC_FEED_REJECTED_OK')
    return 0


def test_event_specific_path_policy(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import (
        classify_exchange_primary_url,
        verify_linked_primary_sighting,
    )

    unsupported = (
        ('nse_about_us', 'https://www.nseindia.com/about-us'),
        ('nse_foo', 'https://www.nseindia.com/foo'),
        ('nse_archives_about', 'https://nsearchives.nseindia.com/about'),
        ('bse_random', 'https://www.bseindia.com/random-page'),
        ('bse_corpfiling_root', 'https://www.bseindia.com/xml-data/corpfiling/'),
        ('nse_corporate_root', 'https://nsearchives.nseindia.com/corporate/'),
    )
    print('EVENT_PATH_UNSUPPORTED_TABLE')
    for label, url in unsupported:
        info = classify_exchange_primary_url(url)
        seeded = upsert_sighting(_exchange(
            source_url=url,
            source_headline=f'Unsupported event path {label}',
            symbols=['PTH1'],
        ))
        result = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
        event = get_event(seeded['event_id'])
        print(
            f'  {label} classifier={info.get("reason")} verify={result.get("reason")} '
            f'ok={result.get("ok")} promoted={result.get("promoted")} '
            f'primary={event.get("primary_source_url") if event else None!r}'
        )
        if info.get('ok'):
            return _fail(f'{label} classifier must reject unsupported event path')
        if info.get('reason') == 'host_policy_rejected':
            return _fail(f'{label} official host must not be reported as spoofed')
        if result.get('ok') or result.get('promoted'):
            return _fail(f'{label} must not promote')
        if result.get('reason') != 'event_path_not_authoritative':
            return _fail(f'{label} expected event_path_not_authoritative, got {result}')
        if event and event.get('primary_source_url'):
            return _fail(f'{label} wrote a primary URL')
        if event and event.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail(f'{label} became PRIMARY')

    positives = (
        ('nse_archive_xml', 'https://nsearchives.nseindia.com/corporate/VALID1.xml', 'PTHA'),
        (
            'bse_attachlive_pdf',
            'https://www.bseindia.com/xml-data/corpfiling/AttachLive/VALID2.pdf',
            'PTHB',
        ),
        (
            'nse_archive_nested',
            'https://nsearchives.nseindia.com/corporate/subdir/VALID1.pdf',
            'PTHC',
        ),
    )
    print('EVENT_PATH_POSITIVE_TABLE')
    for label, url, symbol in positives:
        info = classify_exchange_primary_url(url)
        seeded = upsert_sighting(_exchange(
            source_name='BSE Corporate Announcements' if 'bse' in label else 'NSE Corporate Information',
            source_url=url,
            source_headline=f'Authoritative event path {label}',
            symbols=[symbol],
        ))
        result = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
        event = get_event(seeded['event_id'])
        print(
            f'  {label} classifier_ok={info.get("ok")} promoted={result.get("promoted")} '
            f'status={event.get("verification_status") if event else None}'
        )
        if not info.get('ok'):
            return _fail(f'{label} URL policy must accept event-document path: {info}')
        if not result.get('ok') or not result.get('promoted'):
            return _fail(f'{label} must promote: {result}')
        if not event or event.get('verification_status') != VERIFICATION_PRIMARY:
            return _fail(f'{label} event was not PRIMARY')
        if event.get('primary_source_url') != seeded['sighting']['source_url']:
            return _fail(f'{label} primary URL mismatch')
    _pass('PRIMARY_EVENT_SPECIFIC_PATH_POLICY_OK')
    return 0


def test_event_path_traversal_rejected(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_PRIMARY,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import (
        classify_exchange_primary_url,
        verify_linked_primary_sighting,
    )

    cases = (
        ('nse_dotdot', 'https://nsearchives.nseindia.com/corporate/../about-us'),
        ('nse_dot_segment', 'https://nsearchives.nseindia.com/corporate/./VALID.xml'),
        ('nse_pct_dotdot_lower', 'https://nsearchives.nseindia.com/corporate/%2e%2e/about-us'),
        ('nse_pct_dotdot_upper', 'https://nsearchives.nseindia.com/corporate/%2E%2E/about-us'),
        ('nse_pct_slash_dotdot', 'https://nsearchives.nseindia.com/corporate/foo%2f..%2fabout'),
        ('nse_backslash', 'https://nsearchives.nseindia.com/corporate/foo\\bar'),
        ('bse_dotdot', 'https://www.bseindia.com/xml-data/corpfiling/../random'),
        ('bse_pct_dotdot', 'https://www.bseindia.com/xml-data/corpfiling/%2e%2e/random'),
        ('bse_pct_backslash', 'https://www.bseindia.com/xml-data/corpfiling/foo%5cbar'),
    )
    print('EVENT_PATH_TRAVERSAL_TABLE')
    for label, url in cases:
        info = classify_exchange_primary_url(url)
        print(f'  {label} classifier_ok={info.get("ok")} classifier_reason={info.get("reason")}')
        if info.get('ok'):
            return _fail(f'{label} classifier must reject traversal/structural escape')
        if info.get('reason') != 'event_path_not_authoritative':
            return _fail(f'{label} expected event_path_not_authoritative, got {info}')
        seeded = upsert_sighting(_exchange(
            source_name='BSE Corporate Announcements' if label.startswith('bse_') else 'NSE Corporate Information',
            source_url=url,
            source_headline=f'Traversal escape {label}',
            symbols=['TRV1'],
        ))
        before = ctx['store_path'].read_bytes() if ctx['store_path'].exists() else b''
        result = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
        after = ctx['store_path'].read_bytes() if ctx['store_path'].exists() else b''
        event = get_event(seeded['event_id'])
        print(
            f'    verify_ok={result.get("ok")} promoted={result.get("promoted")} '
            f'reason={result.get("reason")} primary={event.get("primary_source_url") if event else None!r} '
            f'unchanged={before == after}'
        )
        if result.get('ok') or result.get('promoted'):
            return _fail(f'{label} must not promote')
        if result.get('reason') != 'event_path_not_authoritative':
            return _fail(f'{label} verify reason {result}')
        if event and event.get('primary_source_url'):
            return _fail(f'{label} wrote a primary URL')
        if event and event.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail(f'{label} became PRIMARY')
        if before != after:
            return _fail(f'{label} mutated store bytes')
    _pass('PRIMARY_EVENT_PATH_TRAVERSAL_REJECTED_OK')
    return 0


def test_event_linkage(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import get_event, upsert_sighting
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    a = upsert_sighting(_exchange(
        source_headline='Event A headline unique',
        symbols=['LNKA'],
        source_url='https://nsearchives.nseindia.com/corporate/LNKA.xml',
    ))
    b = upsert_sighting(_exchange(
        source_name='BSE Corporate Announcements',
        source_headline='Event B headline unique',
        symbols=['LNKB'],
        source_url='https://www.bseindia.com/xml-data/corpfiling/LNKB.xml',
    ))
    result = verify_linked_primary_sighting(a['event_id'], b['sighting_id'])
    print(
        'LINKAGE_EVIDENCE '
        f'event_a={a["event_id"]} sighting_b={b["sighting_id"]} '
        f'reason={result.get("reason")} ok={result.get("ok")}'
    )
    if result.get('ok') or result.get('reason') != 'linkage_mismatch':
        return _fail(f'unrelated sighting must fail linkage: {result}')
    event_a = get_event(a['event_id'])
    if event_a and event_a.get('primary_source_url'):
        return _fail('event A must not be promoted via event B sighting')
    _pass('PRIMARY_EVENT_LINKAGE_OK')
    return 0


def test_headline_identity(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        attach_sighting_to_event,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    a = upsert_sighting(_exchange(
        source_headline='Canonical event A headline',
        symbols=['HDL1'],
        source_url='https://nsearchives.nseindia.com/corporate/HDL1A.xml',
    ))
    b = upsert_sighting(_exchange(
        source_name='BSE Corporate Announcements',
        source_headline='Completely different headline',
        symbols=['HDL1'],
        source_url='https://www.bseindia.com/xml-data/corpfiling/HDL1B.xml',
    ))
    attach_sighting_to_event(b['sighting_id'], a['event_id'])
    result = verify_linked_primary_sighting(a['event_id'], b['sighting_id'])
    event = get_event(a['event_id'])
    print(
        'HEADLINE_IDENTITY_EVIDENCE '
        f'reason={result.get("reason")} status={event.get("verification_status") if event else None}'
    )
    if result.get('ok') or result.get('reason') != 'headline_mismatch':
        return _fail(f'mismatched headline must fail: {result}')
    _pass('PRIMARY_HEADLINE_IDENTITY_OK')
    return 0


def test_date_identity(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        attach_sighting_to_event,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    headline = 'Same headline different date bucket'
    a = upsert_sighting(_exchange(
        source_headline=headline,
        symbols=['DAT1'],
        source_published_at=PUB,
        source_url='https://nsearchives.nseindia.com/corporate/DAT1A.xml',
    ))
    b = upsert_sighting(_exchange(
        source_name='BSE Corporate Announcements',
        source_headline=headline,
        symbols=['DAT1'],
        source_published_at=LATER,
        source_url='https://www.bseindia.com/xml-data/corpfiling/DAT1B.xml',
    ))
    if a['event_id'] == b['event_id']:
        return _fail('different date buckets must be distinct events')
    attach_sighting_to_event(b['sighting_id'], a['event_id'])
    result = verify_linked_primary_sighting(a['event_id'], b['sighting_id'])
    event = get_event(a['event_id'])
    print(
        'DATE_IDENTITY_EVIDENCE '
        f'reason={result.get("reason")} status={event.get("verification_status") if event else None}'
    )
    if result.get('ok') or result.get('reason') != 'date_bucket_mismatch':
        return _fail(f'date bucket mismatch must fail: {result}')
    _pass('PRIMARY_DATE_IDENTITY_OK')
    return 0


def test_rejected_terminal(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_REJECTED,
        get_event,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    seeded = upsert_sighting(_exchange(
        source_headline='Rejected terminal exchange event',
        symbols=['REJ1'],
        source_url='https://nsearchives.nseindia.com/corporate/REJ1.xml',
    ))
    path = ctx['store_path']
    store = json.loads(path.read_text(encoding='utf-8'))
    store['events'][seeded['event_id']]['verification_status'] = VERIFICATION_REJECTED
    store['events'][seeded['event_id']]['primary_source_url'] = ''
    path.write_text(json.dumps(store), encoding='utf-8')
    before = path.read_bytes()
    result = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
    after = path.read_bytes()
    event = get_event(seeded['event_id'])
    print(
        'REJECTED_TERMINAL_EVIDENCE '
        f'reason={result.get("reason")} status={event.get("verification_status") if event else None} '
        f'unchanged={before == after}'
    )
    if result.get('ok') or result.get('promoted') or result.get('reason') != 'rejected_terminal':
        return _fail(f'REJECTED must not promote: {result}')
    if before != after:
        return _fail('REJECTED promotion attempt must not mutate store bytes')
    if not event or event.get('verification_status') != VERIFICATION_REJECTED:
        return _fail('REJECTED status must remain')
    _pass('PRIMARY_REJECTED_TERMINAL_OK')
    return 0


def test_idempotence(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import get_event, upsert_sighting
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    seeded = upsert_sighting(_exchange(
        source_headline='Idempotent primary event',
        symbols=['IDM1'],
        source_url='https://nsearchives.nseindia.com/corporate/IDM1.xml',
    ))
    first = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'], now=PUB)
    if not first.get('promoted'):
        return _fail(f'first verify must promote: {first}')
    path = ctx['store_path']
    before = path.read_bytes()
    event_before = get_event(seeded['event_id'])
    second = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'], now=LATER)
    after = path.read_bytes()
    event_after = get_event(seeded['event_id'])
    print(
        'IDEMPOTENCE_EVIDENCE '
        f'ok={second.get("ok")} idempotent={second.get("idempotent")} '
        f'promoted={second.get("promoted")} unchanged={before == after}'
    )
    if not second.get('ok') or not second.get('idempotent') or second.get('promoted'):
        return _fail(f'same PRIMARY URL must be idempotent: {second}')
    if before != after:
        return _fail('idempotent verify must not rewrite store bytes')
    if event_before and event_after and event_before.get('updated_at') != event_after.get('updated_at'):
        return _fail('idempotent verify must not churn timestamps')
    _pass('PRIMARY_IDEMPOTENCE_OK')
    return 0


def test_canonical_url_idempotence(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        get_event,
        normalize_url,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    raw = 'https://NSEARCHIVES.NSEINDIA.COM:443/corporate/CANON1.xml#section'
    canonical = normalize_url(raw)
    print(
        'CANONICAL_URL_EVIDENCE '
        f'raw={raw} canonical={canonical} changed={raw != canonical}'
    )
    if raw == canonical:
        return _fail('fixture URL must exercise foundation normalize_url')
    if 'nsearchives.nseindia.com' not in canonical or canonical.endswith('#section'):
        return _fail(f'unexpected canonical form: {canonical!r}')
    if ':443' in canonical:
        return _fail(f'default HTTPS port must be stripped: {canonical!r}')

    seeded = upsert_sighting(_exchange(
        source_headline='Canonical URL idempotence event',
        symbols=['CAN1'],
        source_url=raw,
    ))
    stored = seeded['sighting']['source_url']
    if stored != canonical:
        return _fail(f'stored sighting URL must be canonical, got {stored!r}')
    first = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'], now=PUB)
    if not first.get('promoted'):
        return _fail(f'first verify must promote canonical URL: {first}')
    event = get_event(seeded['event_id'])
    if not event or event.get('primary_source_url') != canonical:
        return _fail(f'PRIMARY must persist canonical URL, got {event}')

    again = upsert_sighting(_exchange(
        source_headline='Canonical URL idempotence event',
        symbols=['CAN1'],
        source_url=raw,
    ))
    if again['sighting_id'] != seeded['sighting_id'] or again['event_id'] != seeded['event_id']:
        return _fail('equivalent normalized URL must remain the same linked source')

    path = ctx['store_path']
    before = path.read_bytes()
    event_before = get_event(seeded['event_id'])
    second = verify_linked_primary_sighting(
        seeded['event_id'],
        seeded['sighting_id'],
        now=LATER,
    )
    after = path.read_bytes()
    event_after = get_event(seeded['event_id'])
    print(
        'CANONICAL_IDEMPOTENCE_EVIDENCE '
        f'ok={second.get("ok")} idempotent={second.get("idempotent")} '
        f'promoted={second.get("promoted")} reason={second.get("reason")} '
        f'unchanged={before == after}'
    )
    if second.get('reason') == 'primary_conflict':
        return _fail('canonical equivalent URL must not be treated as conflict')
    if not second.get('ok') or not second.get('idempotent') or second.get('promoted'):
        return _fail(f'canonical equivalent must be idempotent: {second}')
    if before != after:
        return _fail('canonical idempotent verify must not rewrite store bytes')
    if event_before and event_after and event_before.get('updated_at') != event_after.get('updated_at'):
        return _fail('canonical idempotent verify must not churn timestamps')
    _pass('PRIMARY_CANONICAL_URL_IDEMPOTENCE_OK')
    return 0


def test_conflict_refused(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import get_event, upsert_sighting
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    headline = 'Conflict primary candidate pair'
    a = upsert_sighting(_exchange(
        source_headline=headline,
        symbols=['CNF1'],
        source_url='https://nsearchives.nseindia.com/corporate/CNF1A.xml',
    ))
    b = upsert_sighting(_exchange(
        source_name='BSE Corporate Announcements',
        source_headline=headline,
        symbols=['CNF1'],
        source_url='https://www.bseindia.com/xml-data/corpfiling/CNF1B.xml',
    ))
    if a['event_id'] != b['event_id']:
        return _fail('conflict candidates must share one event')
    first = verify_linked_primary_sighting(a['event_id'], a['sighting_id'])
    if not first.get('promoted'):
        return _fail(f'first PRIMARY must promote: {first}')
    path = ctx['store_path']
    before = path.read_bytes()
    second = verify_linked_primary_sighting(b['event_id'], b['sighting_id'])
    after = path.read_bytes()
    event = get_event(a['event_id'])
    print(
        'PRIMARY_CONFLICT_EVIDENCE '
        f'reason={second.get("reason")} ok={second.get("ok")} '
        f'kept={event.get("primary_source_url") if event else None} unchanged={before == after}'
    )
    if second.get('ok') or second.get('promoted') or second.get('reason') != 'primary_conflict':
        return _fail(f'different PRIMARY URL must conflict: {second}')
    if before != after:
        return _fail('conflict must not overwrite existing PRIMARY')
    if not event or event.get('primary_source_url') != a['sighting']['source_url']:
        return _fail('existing PRIMARY A must be preserved')
    _pass('PRIMARY_CONFLICT_REFUSED_OK')
    return 0


def test_unhealthy_store_immutable(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        HEALTH_MALFORMED,
        HEALTH_PARTIAL,
        HEALTH_UNREADABLE,
        build_canonical_event,
        get_store_health,
        upsert_sighting,
    )
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    seeded = upsert_sighting(_exchange(
        source_headline='Unhealthy store candidate',
        symbols=['UNH1'],
        source_url='https://nsearchives.nseindia.com/corporate/UNH1.xml',
    ))
    path = ctx['store_path']
    eid = seeded['event_id']
    sid = seeded['sighting_id']

    print('UNHEALTHY_STORE_TABLE')
    path.write_bytes(b'\xff\xfe not-utf8')
    before = path.read_bytes()
    unread = verify_linked_primary_sighting(eid, sid)
    after = path.read_bytes()
    health = get_store_health().get('health')
    print(f'  UNREADABLE reason={unread.get("reason")} health={health} unchanged={before == after}')
    if unread.get('ok') or unread.get('promoted') or before != after:
        return _fail('UNREADABLE store must be immutable')
    if health != HEALTH_UNREADABLE:
        return _fail(f'expected UNREADABLE, got {health}')

    path.write_text('{not json', encoding='utf-8')
    before = path.read_bytes()
    malformed = verify_linked_primary_sighting(eid, sid)
    after = path.read_bytes()
    health = get_store_health().get('health')
    print(f'  MALFORMED reason={malformed.get("reason")} health={health} unchanged={before == after}')
    if malformed.get('ok') or malformed.get('promoted') or before != after:
        return _fail('MALFORMED store must be immutable')
    if health != HEALTH_MALFORMED:
        return _fail(f'expected MALFORMED, got {health}')

    good = build_canonical_event(
        event_type='OTHER',
        symbols=['UNH1'],
        canonical_headline='Unhealthy store candidate',
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
    partial = verify_linked_primary_sighting(good['event_id'], sid)
    after = path.read_bytes()
    health = get_store_health().get('health')
    print(f'  PARTIAL reason={partial.get("reason")} health={health} unchanged={before == after}')
    if partial.get('ok') or partial.get('promoted') or before != after:
        return _fail('PARTIAL store must be immutable')
    if health != HEALTH_PARTIAL:
        return _fail(f'expected PARTIAL, got {health}')
    _pass('PRIMARY_UNHEALTHY_STORE_IMMUTABLE_OK')
    return 0


def test_shared_store_lock(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import upsert_sighting
    from backend.news.primary_source_verifier import verify_linked_primary_sighting
    from backend.news.rss_discovery_adapter import _BatchLock, discovery_lock_path

    seeded = upsert_sighting(_exchange(
        source_headline='Shared lock candidate',
        symbols=['LCK1'],
        source_url='https://nsearchives.nseindia.com/corporate/LCK1.xml',
    ))
    path = ctx['store_path']
    before = path.read_bytes()
    lock = _BatchLock(discovery_lock_path())
    if not lock.try_acquire():
        return _fail('parent must acquire the A2 discovery store lock')
    try:
        inproc = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
        print(
            'SHARED_LOCK_INPROCESS '
            f'lock_contended={inproc.get("lock_contended")} reason={inproc.get("reason")} '
            f'promoted={inproc.get("promoted")}'
        )
        if inproc.get('lock_contended') is not True:
            return _fail('verifier must report lock contention against the A2 lock')
        if inproc.get('ok') or inproc.get('promoted'):
            return _fail('contended verifier must not promote')
        if path.read_bytes() != before:
            return _fail('contended verifier must perform zero writes')

        proc, child = _run_lock_subprocess('verify', seeded['event_id'], seeded['sighting_id'])
        child_result = child.get('result') or {}
        print(
            'SHARED_LOCK_CROSS_PROCESS '
            f'owner_pid={os.getpid()} contender_pid={child.get("pid")} '
            f'lock_contended={child_result.get("lock_contended")} rc={proc.returncode}'
        )
        if proc.returncode != 0 or not child:
            return _fail(
                f'cross-process contender failed: rc={proc.returncode} '
                f'stdout={proc.stdout!r} stderr={proc.stderr!r}'
            )
        if child_result.get('lock_contended') is not True:
            return _fail(f'cross-process verifier acquired live A2 lock: {child_result}')
        if child_result.get('promoted') or child_result.get('ok'):
            return _fail('cross-process contender must not promote')
        if path.read_bytes() != before:
            return _fail('cross-process contender wrote the discovery store')
        if lock._fd is None:
            return _fail('cross-process contention displaced the live A2 holder')
    finally:
        lock.release()

    after_release = verify_linked_primary_sighting(seeded['event_id'], seeded['sighting_id'])
    if not after_release.get('promoted'):
        return _fail(f'verifier after lock release must promote, got {after_release}')
    print('SHARED_LOCK_EVIDENCE A2_lock_reused=True zero_writes_on_contention=True')
    _pass('PRIMARY_VERIFIER_SHARED_STORE_LOCK_OK')
    return 0


def test_raw_exception_matrix(ctx: dict) -> int:
    global RAW_EXCEPTION_ESCAPES
    from backend.news.primary_source_verifier import verify_linked_primary_sighting

    cases = [
        ('none_ids', (None, None), {}),
        ('int_ids', (123, 456), {}),
        ('bool_ids', (True, False), {}),
        ('dict_ids', ({'x': 1}, {'y': 2}), {}),
        ('list_ids', (['a'], ['b']), {}),
        ('empty_str', ('', ''), {}),
        ('spaces', ('  ', '  '), {}),
        ('not_uuid', ('not-a-uuid', 'also-not'), {}),
        ('uppercase_uuid', ('ABCDEF01-2345-4678-9ABC-DEF012345678', 'ABCDEF01-2345-4678-9ABC-DEF012345678'), {}),
        ('bytes_ids', (b'abc', b'def'), {}),
        ('surrogate', ('bad\ud800id', 'bad\ud800id'), {}),
        ('missing_second', ('11111111-1111-4111-8111-111111111111',), {}),
        ('extra_positional', (
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
            'third',
        ), {}),
        (
            'caller_primary_url',
            ('11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'),
            {'primary_source_url': 'https://www.nseindia.com/corporate/INJECT.xml'},
        ),
        ('unknown_kwarg', (
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
        ), {'unexpected': 1}),
        ('object_now', (
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
        ), {'now': object()}),
    ]
    print('RAW_EXCEPTION_MATRIX')
    for label, args, kwargs in cases:
        try:
            result = verify_linked_primary_sighting(*args, **kwargs)
            if not isinstance(result, dict):
                RAW_EXCEPTION_ESCAPES += 1
                return _fail(f'{label} did not return a dict')
            if result.get('ok') or result.get('promoted'):
                RAW_EXCEPTION_ESCAPES += 1
                return _fail(f'{label} promoted instead of fail-closed: {result}')
            if 'traceback' in str(result).casefold() or 'Traceback' in str(result):
                RAW_EXCEPTION_ESCAPES += 1
                return _fail(f'{label} leaked a traceback: {result}')
            print(f'  {label} reason={result.get("reason")} ok={result.get("ok")}')
        except Exception as exc:
            RAW_EXCEPTION_ESCAPES += 1
            print(f'  {label} RAW_ESCAPE {type(exc).__name__}')
            return _fail(f'{label} raw exception escape: {type(exc).__name__}: {exc}')
    print(f'PRIMARY_VERIFIER_RAW_EXCEPTION_ESCAPE_COUNT={RAW_EXCEPTION_ESCAPES}')
    return 0


def test_repo_data_safe(git_before: str, git_after: str) -> int:
    if git_after:
        return _fail(f'repository data/ is dirty: {git_after}')
    if git_before:
        return _fail(f'repository data/ was dirty before tests: {git_before}')
    print('DATA_STATUS clean')
    _pass('PRIMARY_VERIFIER_REPO_DATA_SAFE_OK')
    return 0


def main() -> int:
    from scripts._test_runtime_isolation import repo_data_root, snapshot_data_tree

    rc = test_build_identity()
    if rc:
        return rc
    rc = test_no_network_ai_trading()
    if rc:
        return rc
    rc = test_no_nse_waf_path()
    if rc:
        return rc
    rc = test_dormant_production()
    if rc:
        return rc
    rc = test_no_trading_coupling()
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

    mutating = (
        test_exchange_promotion,
        test_publisher_rejected,
        test_secondary_multi_source_not_primary,
        test_host_policy,
        test_generic_feed_rejected,
        test_event_specific_path_policy,
        test_event_path_traversal_rejected,
        test_event_linkage,
        test_headline_identity,
        test_date_identity,
        test_rejected_terminal,
        test_idempotence,
        test_canonical_url_idempotence,
        test_conflict_refused,
        test_unhealthy_store_immutable,
        test_shared_store_lock,
        test_raw_exception_matrix,
    )
    with _isolated_verifier() as ctx, patch.object(Path, 'read_text', _guard_read_text), patch.object(
        Path, 'open', _guard_open
    ):
        for fn in mutating:
            _reset(ctx)
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
        'PRIMARY_VERIFIER_NO_NETWORK_AI_TRADING_OK',
        'PRIMARY_VERIFIER_NO_NSE_WAF_PATH_OK',
        'PRIMARY_VERIFIER_DORMANT_PRODUCTION_OK',
        'PRIMARY_VERIFIER_NO_TRADING_COUPLING_OK',
        'PRIMARY_VERIFIER_REPO_DATA_SAFE_OK',
    )
    missing = [m for m in required if m not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    if RAW_EXCEPTION_ESCAPES != 0:
        return _fail(f'raw exception escapes={RAW_EXCEPTION_ESCAPES}')
    print('PRIMARY_SOURCE_VERIFIER_52R_B1_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
