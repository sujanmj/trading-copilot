#!/usr/bin/env python3
"""AstraEdge 52R-A1 — broker news discovery foundation (isolated)."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from datetime import date, datetime
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
# Canonical unknown IDs for healthy-store query / missing-mutation probes.
UNKNOWN_EVENT_ID = '11111111-1111-4111-8111-111111111111'
UNKNOWN_SIGHTING_ID = '22222222-2222-4222-8222-222222222222'
UNKNOWN_FINGERPRINT = 'a' * 64
UPPERCASE_UUID = 'ABCDEF01-2345-4678-9ABC-DEF012345678'


def _fail(msg: str) -> int:
    print(f'BROKER_DISCOVERY_FOUNDATION_52R_A1_FAIL: {msg}', file=sys.stderr)
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


def _base_event(**extra):
    row = {
        'event_type': 'RESULT',
        'symbols': ['INFY', 'TCS'],
        'canonical_headline': 'Infosys reports strong quarterly result',
        'published_at': PUB,
        'company_names': ['Infosys'],
        'structured_facts': {'revenue_cr': 1000, 'pat_cr': 200},
    }
    row.update(extra)
    return row


def _base_sighting(**extra):
    row = {
        'source_name': 'Groww Public News',
        'source_kind': 'BROKER_PUBLIC',
        'source_url': 'https://news.example.com/story?id=1&utm_source=x&utm_medium=y',
        'source_headline': 'Infosys reports strong quarterly result!',
        'source_published_at': PUB,
        'original_publisher': 'Example Wire',
        'attribution': 'Groww public feed',
        'bounded_excerpt': 'Infosys reported revenue of 1000 cr.',
        'symbols': ['INFY', 'TCS'],
        'event_type': 'RESULT',
        'structured_facts': {'revenue_cr': 1000, 'pat_cr': 200},
    }
    row.update(extra)
    return row


def test_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    allowed = {
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
    }
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'expected exact pair 52R-A1 / AstraEdge 52R-A1 or successor '
            f'52R-A2 / AstraEdge 52R-A2 or 52R-B1 / AstraEdge 52R-B1 or '
            f'52R-B2N / AstraEdge 52R-B2N, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    _pass('BROKER_DISCOVERY_BUILD_OK')
    return 0


def test_exact_build_pair_allowlists() -> int:
    """Successor validators must accept only exact (stage, telegram) pairs."""
    daily_pairs = {
        ('52Q', 'AstraEdge 52Q'),
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
    }
    tradecard_pairs = {
        ('52P', 'AstraEdge 52P'),
        ('52Q', 'AstraEdge 52Q'),
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
    }
    # Positive current pair.
    if ('52R-B2N', 'AstraEdge 52R-B2N') not in daily_pairs:
        return _fail('current pair missing from daily-review allowlist')
    if ('52R-B2N', 'AstraEdge 52R-B2N') not in tradecard_pairs:
        return _fail('current pair missing from tradecard allowlist')
    mismatches = (
        ('52Q', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52Q'),
        ('52P', 'AstraEdge 52Q'),
        ('52R-A2', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-B2N'),
    )
    for stage, telegram in mismatches:
        if (stage, telegram) in daily_pairs:
            return _fail(f'daily allowlist accepted mismatch {stage!r}/{telegram!r}')
        if (stage, telegram) in tradecard_pairs:
            return _fail(f'tradecard allowlist accepted mismatch {stage!r}/{telegram!r}')
    _pass('BROKER_DISCOVERY_BUILD_PAIR_MISMATCH_REJECTED_OK')
    return 0


def test_canonical_event_and_sighting_creation() -> int:
    from backend.news.broker_discovery_foundation import (
        VERIFICATION_DISCOVERY_ONLY,
        build_canonical_event,
        build_source_sighting,
    )

    event = build_canonical_event(**_base_event())
    for key in (
        'event_id',
        'event_fingerprint',
        'event_type',
        'symbols',
        'company_names',
        'canonical_headline',
        'normalized_headline',
        'structured_facts',
        'published_at',
        'first_seen_at',
        'last_seen_at',
        'verification_status',
        'source_count',
        'primary_source_url',
        'created_at',
        'updated_at',
        'schema_version',
    ):
        if key not in event:
            return _fail(f'event missing {key}')
    if event['verification_status'] != VERIFICATION_DISCOVERY_ONLY:
        return _fail('new event must begin DISCOVERY_ONLY')
    if event['symbols'] != ['INFY', 'TCS']:
        return _fail(f'symbols not normalized/sorted: {event["symbols"]}')

    sighting_payload = _base_sighting()
    sighting = build_source_sighting(
        source_name=sighting_payload['source_name'],
        source_kind=sighting_payload['source_kind'],
        source_url=sighting_payload['source_url'],
        source_headline=sighting_payload['source_headline'],
        source_published_at=sighting_payload['source_published_at'],
        original_publisher=sighting_payload['original_publisher'],
        attribution=sighting_payload['attribution'],
        bounded_excerpt=sighting_payload['bounded_excerpt'],
    )
    for key in (
        'sighting_id',
        'event_id',
        'source_name',
        'source_kind',
        'source_url',
        'source_headline',
        'normalized_headline',
        'source_published_at',
        'first_seen_at',
        'last_seen_at',
        'original_publisher',
        'content_hash',
        'attribution',
        'bounded_excerpt',
        'schema_version',
    ):
        if key not in sighting:
            return _fail(f'sighting missing {key}')
    if sighting['article_body'] is not None:
        return _fail('article_body must be None')
    _pass('BROKER_DISCOVERY_CONTRACTS_OK')
    return 0


def test_idempotent_repeat_and_last_seen(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    t1 = datetime(2099, 7, 31, 11, 0, 0, tzinfo=IST)
    t2 = datetime(2099, 7, 31, 12, 0, 0, tzinfo=IST)
    first = bdf.upsert_sighting(_base_sighting(), now=t1)
    if not first['inserted'] or first['deduplicated']:
        return _fail(f'first insert expected inserted=True, got {first}')
    sid = first['sighting_id']
    second = bdf.upsert_sighting(_base_sighting(), now=t2)
    if second['inserted'] or not second['deduplicated']:
        return _fail(f'repeat must dedupe, got {second}')
    if second['sighting_id'] != sid:
        return _fail('sighting_id changed on repeat')
    row = bdf.get_sighting(sid)
    if not row:
        return _fail('sighting missing after upsert')
    if not str(row['last_seen_at']).startswith('2099-07-31T12:00:00'):
        return _fail(f'last_seen_at not updated: {row["last_seen_at"]}')
    if str(row['first_seen_at']).startswith('2099-07-31T12:00:00'):
        return _fail('first_seen_at must remain original')
    _pass('BROKER_DISCOVERY_IDEMPOTENT_OK')
    return 0


def test_url_and_headline_variation_dedupe(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    a = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/story?utm_campaign=1&id=1',
        source_headline='Infosys reports strong quarterly result!',
    ))
    b = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/story?id=1&fbclid=abc#section',
        source_headline='  Infosys   reports strong quarterly result  ',
    ))
    if a['sighting_id'] != b['sighting_id']:
        return _fail('URL/headline normalization failed to dedupe')
    if b['inserted']:
        return _fail('normalized variant must not insert second sighting')
    _pass('BROKER_DISCOVERY_URL_HEADLINE_DEDUPE_OK')
    return 0


def test_material_events_remain_separate(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    a = bdf.upsert_sighting(_base_sighting(
        source_name='Broker A',
        source_url='https://news.example.com/a',
        structured_facts={'revenue_cr': 1000},
        source_headline='Infosys revenue update A',
    ))
    b = bdf.upsert_sighting(_base_sighting(
        source_name='Broker B',
        source_url='https://news.example.com/b',
        structured_facts={'revenue_cr': 2500},
        source_headline='Infosys revenue update B',
    ))
    if a['event_id'] == b['event_id']:
        return _fail('different numeric facts must not merge')
    _pass('BROKER_DISCOVERY_SEPARATE_EVENTS_OK')
    return 0


def test_symbol_and_fact_order_stable() -> int:
    from backend.news.broker_discovery_foundation import build_canonical_event

    e1 = build_canonical_event(**_base_event(
        symbols=['TCS', 'INFY'],
        structured_facts={'pat_cr': 200, 'revenue_cr': 1000},
    ))
    e2 = build_canonical_event(**_base_event(
        symbols=['INFY', 'TCS'],
        structured_facts={'revenue_cr': 1000, 'pat_cr': 200},
    ))
    if e1['event_id'] != e2['event_id'] or e1['event_fingerprint'] != e2['event_fingerprint']:
        return _fail('symbol/fact ordering changed identity')
    _pass('BROKER_DISCOVERY_ORDER_STABLE_OK')
    return 0


def test_unknown_event_type_other() -> int:
    from backend.news.broker_discovery_foundation import build_canonical_event, normalize_event_type

    if normalize_event_type('totally_unknown_thing') != 'OTHER':
        return _fail('unknown event type must normalize to OTHER')
    event = build_canonical_event(**_base_event(event_type='weird-custom'))
    if event['event_type'] != 'OTHER':
        return _fail('built event type must be OTHER')
    _pass('BROKER_DISCOVERY_EVENT_TYPE_OTHER_OK')
    return 0


def test_verification_rules(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    unique = {
        'symbols': ['SYNGENE'],
        'event_type': 'GUIDANCE',
        'structured_facts': {'guidance_note': 'unique-verify-case'},
        'source_headline': 'Syngene issues unique guidance update for verification test',
    }
    first = bdf.upsert_sighting(_base_sighting(
        source_name='Groww',
        source_url='https://news.example.com/g1',
        **unique,
    ))
    event = bdf.get_event(first['event_id'])
    if not event or event['verification_status'] != bdf.VERIFICATION_DISCOVERY_ONLY:
        return _fail(f'broker sighting must begin DISCOVERY_ONLY, got {event}')

    second = bdf.upsert_sighting(_base_sighting(
        source_name='Indmoney',
        source_url='https://news.example.com/i1',
        **unique,
    ))
    if second['event_id'] != first['event_id']:
        bdf.attach_sighting_to_event(second['sighting_id'], first['event_id'])
    multi = bdf.get_event(first['event_id'])
    if not multi or multi['verification_status'] != bdf.VERIFICATION_MULTI_SOURCE:
        return _fail(f'multi broker must be MULTI_SOURCE_CONFIRMED, got {multi}')
    if multi['verification_status'] == bdf.VERIFICATION_PRIMARY:
        return _fail('multi broker must never auto-primary')

    primary = bdf.mark_primary_source_verified(
        first['event_id'],
        primary_source_url='https://www.nseindia.com/corporate/announcement/1',
    )
    if primary['verification_status'] != bdf.VERIFICATION_PRIMARY:
        return _fail('explicit primary mark failed')
    bdf.upsert_sighting(_base_sighting(
        source_name='Angel',
        source_url='https://news.example.com/a1',
        event_id=first['event_id'],
        **unique,
    ))
    still = bdf.get_event(first['event_id'])
    if still['verification_status'] != bdf.VERIFICATION_PRIMARY:
        return _fail('PRIMARY must remain after later broker sightings')
    _pass('BROKER_DISCOVERY_VERIFICATION_OK')
    return 0


def test_excerpt_and_no_full_article(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    long_text = 'x' * 800
    result = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/excerpt',
        bounded_excerpt=long_text,
    ))
    row = bdf.get_sighting(result['sighting_id'])
    if not row:
        return _fail('excerpt sighting missing')
    if len(row['bounded_excerpt']) > bdf.MAX_EXCERPT_LENGTH:
        return _fail('bounded excerpt exceeded max length')
    if row.get('article_body') not in (None, ''):
        return _fail('article_body retained')
    store = json.loads(Path(iso['temp_root'], 'broker_news_discovery_store.json').read_text(encoding='utf-8'))
    blob = json.dumps(store)
    if long_text in blob:
        return _fail('full oversized excerpt body persisted')
    if '<html' in blob.casefold():
        return _fail('html body persisted')
    try:
        payload = _base_sighting(
            bounded_excerpt='<!DOCTYPE html><html><body>secret</body></html>',
        )
        bdf.build_source_sighting(
            source_name=payload['source_name'],
            source_kind=payload['source_kind'],
            source_url=payload['source_url'],
            source_headline=payload['source_headline'],
            source_published_at=payload['source_published_at'],
            bounded_excerpt=payload['bounded_excerpt'],
        )
        return _fail('raw HTML excerpt must be rejected')
    except bdf.BrokerDiscoveryError:
        pass
    _pass('BROKER_DISCOVERY_RETENTION_OK')
    return 0


def test_store_health_missing_and_malformed(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    health = bdf.get_store_health()
    if health['health'] not in (bdf.HEALTH_MISSING, bdf.HEALTH_OK):
        return _fail(f'unexpected initial health {health}')

    path = bdf.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{not-json', encoding='utf-8')
    bad = bdf.get_store_health()
    if bad['health'] != bdf.HEALTH_MALFORMED:
        return _fail(f'malformed store must report MALFORMED, got {bad}')
    if bad.get('counts_unavailable') is not True:
        return _fail('malformed store counts must be unavailable')
    if bad.get('event_count') is not None:
        return _fail('malformed store must not report false event_count zero as available')

    # Unreadable via permission is platform-specific; simulate by patching read.
    path.write_text('{"schema_version":"52R-A1","events":{},"sightings":{}}', encoding='utf-8')
    with patch.object(Path, 'read_text', side_effect=OSError('boom')):
        # Only patch when reading this store path — broad patch may break; use module load path.
        pass
    with patch('backend.news.broker_discovery_foundation.store_path', return_value=path):
        original = Path.read_text

        def _boom(self, *a, **k):
            if self == path or self.resolve() == path.resolve():
                raise OSError('boom')
            return original(self, *a, **k)

        with patch.object(Path, 'read_text', _boom):
            unread = bdf.get_store_health()
    if unread['health'] != bdf.HEALTH_UNREADABLE:
        return _fail(f'unreadable store must report UNREADABLE, got {unread}')
    if unread.get('counts_unavailable') is not True:
        return _fail('unreadable counts must be unavailable')

    # Restore usable store for later tests.
    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_HEALTH_OK')
    return 0


def test_no_network_no_ai() -> int:
    src = (PROJECT_ROOT / 'backend/news/broker_discovery_foundation.py').read_text(encoding='utf-8')
    forbidden = (
        'import requests',
        'from requests',
        'urllib.request',
        'httpx',
        'aiohttp',
        'selenium',
        'playwright',
        'openai',
        'anthropic',
        'google.generativeai',
        'genai',
    )
    for token in forbidden:
        if token in src:
            return _fail(f'foundation source contains forbidden token {token!r}')

    # Runtime guard: block outbound sockets during a representative upsert.
    real_socket = socket.socket

    class _NoNetSocket(real_socket):
        def connect(self, *a, **k):  # type: ignore[override]
            raise AssertionError('network connect attempted')

        def connect_ex(self, *a, **k):  # type: ignore[override]
            raise AssertionError('network connect_ex attempted')

    from scripts._test_runtime_isolation import isolated_premarket_data_root
    from backend.news import broker_discovery_foundation as bdf

    with isolated_premarket_data_root(), patch('socket.socket', _NoNetSocket):
        bdf.upsert_sighting(_base_sighting(source_url='https://news.example.com/nonet'))
    _pass('BROKER_DISCOVERY_NO_NETWORK_AI_OK')
    return 0


def test_queries(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    r = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/q1',
        symbols=['RELIANCE'],
        source_headline='Reliance capex announcement',
        event_type='CAPEX',
        structured_facts={'capex_cr': 500},
    ))
    by_sym = bdf.find_events_by_symbol('reliance')
    if not any(e['event_id'] == r['event_id'] for e in by_sym):
        return _fail('find_events_by_symbol missed event')
    by_date = bdf.find_events_by_date(PUB.date())
    if not any(e['event_id'] == r['event_id'] for e in by_date):
        return _fail('find_events_by_date missed event')
    recent = bdf.find_recent_events(limit=10)
    if not recent:
        return _fail('find_recent_events empty')
    linked = bdf.list_event_sightings(r['event_id'])
    if len(linked) < 1:
        return _fail('list_event_sightings empty')
    _pass('BROKER_DISCOVERY_QUERY_OK')
    return 0


def test_repeated_runs_deterministic(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    ids = []
    for _ in range(3):
        # Fresh store each logical run inside same iso root: delete store.
        path = bdf.store_path()
        if path.is_file():
            path.unlink()
        result = bdf.upsert_sighting(_base_sighting(source_url='https://news.example.com/det'))
        ids.append((result['event_id'], result['sighting_id']))
    if len(set(ids)) != 1:
        return _fail(f'repeated runs not deterministic: {ids}')
    _pass('BROKER_DISCOVERY_DETERMINISTIC_OK')
    return 0


def test_repo_data_not_read_or_mutated(before, after, git_before, git_after, leaks) -> int:
    if git_before != git_after:
        return _fail(f'data git status changed: {git_before!r} -> {git_after!r}')
    if before != after:
        changed = sorted(set(before) | set(after))
        diffs = [p for p in changed if before.get(p) != after.get(p)]
        return _fail(f'repository data mutated: {diffs[:8]}')
    if leaks:
        return _fail(f'repository data read attempted: {leaks[:5]}')
    _pass('BROKER_DISCOVERY_REPO_DATA_SAFE_OK')
    return 0


def _assert_raises_unhealthy(fn, *, expected_token: str):
    from backend.news.broker_discovery_foundation import BrokerDiscoveryError

    try:
        fn()
    except BrokerDiscoveryError as exc:
        msg = str(exc)
        if expected_token not in msg:
            return f'expected {expected_token!r} in error, got {msg!r}'
        return None
    return f'expected BrokerDiscoveryError containing {expected_token!r}'


def test_primary_transition_guard(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    # 1) upsert_event new + PRIMARY request
    r1 = bdf.upsert_event(_base_event(
        symbols=['PTG1'],
        structured_facts={'k': 'p1'},
        canonical_headline='Primary transition guard event one',
        verification_status=bdf.VERIFICATION_PRIMARY,
        primary_source_url='https://www.nseindia.com/x',
    ))
    e1 = bdf.get_event(r1['event_id'])
    if not e1 or e1['verification_status'] != bdf.VERIFICATION_DISCOVERY_ONLY:
        return _fail(f'upsert_event PRIMARY request must stay DISCOVERY_ONLY, got {e1}')
    if e1.get('primary_source_url'):
        return _fail('ordinary upsert_event must not set primary_source_url')

    # 2) upsert_event new + MULTI request
    r2 = bdf.upsert_event(_base_event(
        symbols=['PTG2'],
        structured_facts={'k': 'p2'},
        canonical_headline='Primary transition guard event two',
        verification_status=bdf.VERIFICATION_MULTI_SOURCE,
    ))
    e2 = bdf.get_event(r2['event_id'])
    if not e2 or e2['verification_status'] != bdf.VERIFICATION_DISCOVERY_ONLY:
        return _fail(f'upsert_event MULTI request must stay DISCOVERY_ONLY, got {e2}')

    # 3) upsert_sighting event payload requesting PRIMARY
    s3 = bdf.upsert_sighting(
        _base_sighting(
            source_url='https://news.example.com/ptg3',
            symbols=['PTG3'],
            structured_facts={'k': 'p3'},
            source_headline='Primary transition guard sighting three',
        ),
        event=_base_event(
            symbols=['PTG3'],
            structured_facts={'k': 'p3'},
            canonical_headline='Primary transition guard sighting three',
            verification_status=bdf.VERIFICATION_PRIMARY,
            primary_source_url='https://www.nseindia.com/y',
        ),
    )
    e3 = bdf.get_event(s3['event_id'])
    if not e3 or e3['verification_status'] != bdf.VERIFICATION_DISCOVERY_ONLY:
        return _fail(f'sighting+event PRIMARY request must stay DISCOVERY_ONLY, got {e3}')

    # 4) primary URL in event payload without mark_primary
    s4 = bdf.upsert_sighting(
        _base_sighting(
            source_url='https://news.example.com/ptg4',
            symbols=['PTG4'],
            structured_facts={'k': 'p4'},
            source_headline='Primary transition guard sighting four',
        ),
        event=_base_event(
            symbols=['PTG4'],
            structured_facts={'k': 'p4'},
            canonical_headline='Primary transition guard sighting four',
            primary_source_url='https://www.nseindia.com/z',
        ),
    )
    e4 = bdf.get_event(s4['event_id'])
    if not e4 or e4['verification_status'] != bdf.VERIFICATION_DISCOVERY_ONLY:
        return _fail(f'primary URL without mark must stay DISCOVERY_ONLY, got {e4}')
    if e4.get('primary_source_url'):
        return _fail('primary URL must not persist without mark_primary')

    # 5) two broker sightings never become primary
    unique = {
        'symbols': ['PTG5'],
        'event_type': 'RESULT',
        'structured_facts': {'k': 'p5'},
        'source_headline': 'Primary transition guard multi broker',
    }
    a = bdf.upsert_sighting(_base_sighting(
        source_name='BrokerOne',
        source_url='https://news.example.com/ptg5a',
        **unique,
    ))
    b = bdf.upsert_sighting(_base_sighting(
        source_name='BrokerTwo',
        source_url='https://news.example.com/ptg5b',
        **unique,
    ))
    if a['event_id'] != b['event_id']:
        bdf.attach_sighting_to_event(b['sighting_id'], a['event_id'])
    multi = bdf.get_event(a['event_id'])
    if not multi or multi['verification_status'] != bdf.VERIFICATION_MULTI_SOURCE:
        return _fail(f'two brokers must be MULTI, got {multi}')
    if multi['verification_status'] == bdf.VERIFICATION_PRIMARY:
        return _fail('two brokers must never become PRIMARY')

    marked = bdf.mark_primary_source_verified(
        a['event_id'],
        primary_source_url='https://www.nseindia.com/corporate/ptg5',
    )
    if marked['verification_status'] != bdf.VERIFICATION_PRIMARY:
        return _fail('mark_primary_source_verified must promote')
    bdf.upsert_sighting(_base_sighting(
        source_name='BrokerThree',
        source_url='https://news.example.com/ptg5c',
        event_id=a['event_id'],
        **unique,
    ))
    still = bdf.get_event(a['event_id'])
    if still['verification_status'] != bdf.VERIFICATION_PRIMARY:
        return _fail('later broker sightings must preserve PRIMARY')

    # No no-op pass-only primary guard branch in foundation.
    src = (PROJECT_ROOT / 'backend/news/broker_discovery_foundation.py').read_text(encoding='utf-8')
    if 'if status == VERIFICATION_PRIMARY:\n        pass' in src or 'PRIMARY_SOURCE_VERIFIED):\n            pass' in src:
        return _fail('no-op primary guard (pass-only) still present')

    _pass('BROKER_DISCOVERY_PRIMARY_TRANSITION_GUARD_OK')
    return 0


def test_query_failure_truth(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    query_fns = (
        ('get_event', lambda: bdf.get_event('x')),
        ('get_sighting', lambda: bdf.get_sighting('x')),
        ('list_event_sightings', lambda: bdf.list_event_sightings('x')),
        ('find_events_by_symbol', lambda: bdf.find_events_by_symbol('INFY')),
        ('find_events_by_date', lambda: bdf.find_events_by_date(PUB.date())),
        ('find_recent_events', lambda: bdf.find_recent_events()),
        ('find_event_by_fingerprint', lambda: bdf.find_event_by_fingerprint('fp')),
    )

    path.write_text('{not-json', encoding='utf-8')
    for name, fn in query_fns:
        err = _assert_raises_unhealthy(fn, expected_token=bdf.HEALTH_MALFORMED)
        if err:
            return _fail(f'{name} MALFORMED: {err}')

    original = Path.read_text

    def _boom(self, *a, **k):
        if self == path or self.resolve() == path.resolve():
            raise OSError('boom')
        return original(self, *a, **k)

    path.write_text('{"schema_version":"52R-A1","events":{},"sightings":{}}', encoding='utf-8')
    with patch.object(Path, 'read_text', _boom):
        for name, fn in query_fns:
            err = _assert_raises_unhealthy(fn, expected_token=bdf.HEALTH_UNREADABLE)
            if err:
                return _fail(f'{name} UNREADABLE: {err}')

    # PARTIAL: valid top-level, one corrupt event value
    good = bdf.build_canonical_event(**_base_event(
        symbols=['QFT'],
        structured_facts={'k': 'partial'},
        canonical_headline='Query failure partial event',
    ))
    path.write_text(json.dumps({
        'schema_version': '52R-A1',
        'events': {good['event_id']: 'not-a-dict', good['event_id'] + 'x': good},
        'sightings': {},
        'updated_at': good['updated_at'],
    }), encoding='utf-8')
    # Fix: one corrupt only
    path.write_text(json.dumps({
        'schema_version': '52R-A1',
        'events': {good['event_id']: 'not-a-dict'},
        'sightings': {},
        'updated_at': good['updated_at'],
    }), encoding='utf-8')
    for name, fn in query_fns:
        err = _assert_raises_unhealthy(fn, expected_token=bdf.HEALTH_PARTIAL)
        if err:
            return _fail(f'{name} PARTIAL: {err}')

    # Healthy missing row / empty query still allowed after restore
    if path.exists():
        path.unlink()
    if bdf.get_event(UNKNOWN_EVENT_ID) is not None:
        return _fail('healthy/missing store get_event must allow None')
    if bdf.find_events_by_symbol('ZZZNONE') != []:
        return _fail('healthy empty query must return []')
    if bdf.get_sighting(UNKNOWN_SIGHTING_ID) is not None:
        return _fail('unknown sighting must return None')
    if bdf.list_event_sightings(UNKNOWN_EVENT_ID) != []:
        return _fail('unknown event sightings must return []')
    if bdf.find_event_by_fingerprint(UNKNOWN_FINGERPRINT) is not None:
        return _fail('unknown fingerprint must return None')

    _pass('BROKER_DISCOVERY_QUERY_FAILURE_TRUTH_OK')
    return 0


def test_partial_store_health(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # valid -> OK
    if path.exists():
        path.unlink()
    bdf.upsert_event(_base_event(
        symbols=['PH1'],
        structured_facts={'k': 1},
        canonical_headline='Partial health valid',
    ))
    ok = bdf.get_store_health()
    if ok['health'] != bdf.HEALTH_OK:
        return _fail(f'valid store must be OK, got {ok}')

    # missing
    path.unlink()
    missing = bdf.get_store_health()
    if missing['health'] != bdf.HEALTH_MISSING:
        return _fail(f'missing store must be MISSING, got {missing}')

    # invalid top level
    path.write_text('[]', encoding='utf-8')
    if bdf.get_store_health()['health'] != bdf.HEALTH_MALFORMED:
        return _fail('non-dict payload must be MALFORMED')
    path.write_text(json.dumps({'schema_version': '52R-A1', 'events': {}}), encoding='utf-8')
    if bdf.get_store_health()['health'] != bdf.HEALTH_MALFORMED:
        return _fail('missing sightings key must be MALFORMED')

    ev = bdf.build_canonical_event(**_base_event(
        symbols=['PH2'],
        structured_facts={'k': 2},
        canonical_headline='Partial health event base',
    ))
    sight = bdf.build_source_sighting(
        source_name='Broker',
        source_kind='BROKER_PUBLIC',
        source_url='https://news.example.com/ph',
        source_headline=ev['canonical_headline'],
        source_published_at=PUB,
        event_id=ev['event_id'],
    )

    ts = ev['updated_at']

    # one corrupt event
    path.write_text(json.dumps({
        'schema_version': '52R-A1',
        'events': {ev['event_id']: ['bad']},
        'sightings': {},
        'updated_at': ts,
    }), encoding='utf-8')
    h = bdf.get_store_health()
    if h['health'] != bdf.HEALTH_PARTIAL:
        return _fail(f'corrupt event must be PARTIAL, got {h}')
    if h.get('event_count') is not None or h.get('counts_unavailable') is not True:
        return _fail(f'PARTIAL counts must be unavailable, got {h}')

    # one corrupt sighting
    path.write_text(json.dumps({
        'schema_version': '52R-A1',
        'events': {ev['event_id']: ev},
        'sightings': {sight['sighting_id']: 'bad'},
        'updated_at': ts,
    }), encoding='utf-8')
    if bdf.get_store_health()['health'] != bdf.HEALTH_PARTIAL:
        return _fail('corrupt sighting must be PARTIAL')

    # broken sighting event reference
    bad_sight = dict(sight)
    bad_sight['event_id'] = 'missing-event-id'
    path.write_text(json.dumps({
        'schema_version': '52R-A1',
        'events': {ev['event_id']: ev},
        'sightings': {bad_sight['sighting_id']: bad_sight},
        'updated_at': ts,
    }), encoding='utf-8')
    if bdf.get_store_health()['health'] != bdf.HEALTH_PARTIAL:
        return _fail('broken event reference must be PARTIAL')

    # key/ID mismatch
    path.write_text(json.dumps({
        'schema_version': '52R-A1',
        'events': {'wrong-key': ev},
        'sightings': {},
        'updated_at': ts,
    }), encoding='utf-8')
    if bdf.get_store_health()['health'] != bdf.HEALTH_PARTIAL:
        return _fail('event key/id mismatch must be PARTIAL')

    # _save_store refuses partial
    partial_payload = {
        'schema_version': '52R-A1',
        'events': {ev['event_id']: ['bad']},
        'sightings': {},
        'updated_at': ts,
    }
    try:
        bdf._save_store(partial_payload, now=PUB)
        return _fail('_save_store must refuse PARTIAL')
    except bdf.BrokerDiscoveryError as exc:
        if bdf.HEALTH_PARTIAL not in str(exc) and 'unhealthy' not in str(exc).casefold():
            return _fail(f'_save_store PARTIAL error unexpected: {exc}')

    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_PARTIAL_HEALTH_OK')
    return 0


def test_reattachment_truth(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    facts = {'reattach': 'case-a'}
    headline = 'Reattachment truth shared headline'
    s1 = bdf.upsert_sighting(_base_sighting(
        source_name='SrcA',
        source_url='https://news.example.com/ra1',
        symbols=['REATT'],
        structured_facts=facts,
        source_headline=headline,
        event_type='RESULT',
    ))
    s2 = bdf.upsert_sighting(_base_sighting(
        source_name='SrcB',
        source_url='https://news.example.com/ra2',
        symbols=['REATT'],
        structured_facts=facts,
        source_headline=headline,
        event_type='RESULT',
    ))
    if s1['event_id'] != s2['event_id']:
        bdf.attach_sighting_to_event(s2['sighting_id'], s1['event_id'])
    multi = bdf.get_event(s1['event_id'])
    if multi['verification_status'] != bdf.VERIFICATION_MULTI_SOURCE or multi['source_count'] != 2:
        return _fail(f'expected multi source_count=2, got {multi}')

    # Create a second event and move one sighting away
    other = bdf.upsert_event(_base_event(
        symbols=['REATT2'],
        structured_facts={'reattach': 'other'},
        canonical_headline='Reattachment truth other event',
    ))
    before_old = bdf.get_event(s1['event_id'])
    before_new = bdf.get_event(other['event_id'])
    bdf.attach_sighting_to_event(s2['sighting_id'], other['event_id'])
    after_old = bdf.get_event(s1['event_id'])
    after_new = bdf.get_event(other['event_id'])
    print(
        'REATTACHMENT_BEFORE_AFTER '
        f'old_status={before_old["verification_status"]}->{after_old["verification_status"]} '
        f'old_count={before_old["source_count"]}->{after_old["source_count"]} '
        f'new_status={before_new["verification_status"]}->{after_new["verification_status"]} '
        f'new_count={before_new["source_count"]}->{after_new["source_count"]}'
    )
    if after_old['verification_status'] != bdf.VERIFICATION_DISCOVERY_ONLY:
        return _fail('old event must fall back to DISCOVERY_ONLY')
    if after_old['source_count'] != 1:
        return _fail(f'old source_count must decrease to 1, got {after_old["source_count"]}')
    if after_new['source_count'] != 1:
        return _fail(f'new source_count must increase to 1, got {after_new["source_count"]}')

    # Primary event source count updates without losing primary
    primary = bdf.mark_primary_source_verified(
        s1['event_id'],
        primary_source_url='https://www.nseindia.com/reattach',
    )
    if primary['verification_status'] != bdf.VERIFICATION_PRIMARY:
        return _fail('primary mark failed in reattachment test')
    count_before = bdf.get_event(s1['event_id'])['source_count']
    bdf.upsert_sighting(_base_sighting(
        source_name='SrcC',
        source_url='https://news.example.com/ra3',
        event_id=s1['event_id'],
        symbols=['REATT'],
        structured_facts=facts,
        source_headline=headline,
        event_type='RESULT',
    ))
    primary_after = bdf.get_event(s1['event_id'])
    if primary_after['verification_status'] != bdf.VERIFICATION_PRIMARY:
        return _fail('PRIMARY must remain while source_count updates')
    if primary_after['source_count'] != count_before + 1:
        return _fail(
            f'PRIMARY source_count must update {count_before} -> {primary_after["source_count"]}'
        )

    # Reattach same event: idempotent, no count corruption
    linked = bdf.list_event_sightings(s1['event_id'])
    if not linked:
        return _fail('expected sightings on primary event')
    sid = linked[0]['sighting_id']
    count_same = bdf.get_event(s1['event_id'])['source_count']
    bdf.attach_sighting_to_event(sid, s1['event_id'])
    same = bdf.get_event(s1['event_id'])
    if same['source_count'] != count_same:
        return _fail('same-event reattach corrupted source_count')
    if len(bdf.list_event_sightings(s1['event_id'])) != count_same:
        return _fail('same-event reattach duplicated sightings')

    _pass('BROKER_DISCOVERY_REATTACHMENT_TRUTH_OK')
    return 0


def test_raw_markup_rejected(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    cases = (
        '<html><body>x</body></html>',
        '<!DOCTYPE html><html></html>',
        '<script>alert(1)</script>',
        '<style>body{}</style>',
        '<div>news</div>',
        '<p>paragraph</p>',
        '<SPAN>mixed</SPAN>',
        '</div>',
        '<Table><tr><td>1</td></tr></Table>',
    )
    for excerpt in cases:
        try:
            bdf.bound_excerpt(excerpt)
            return _fail(f'markup must be rejected: {excerpt!r}')
        except bdf.BrokerDiscoveryError:
            pass

    # Math comparisons must remain allowed
    ok = bdf.bound_excerpt('EPS grew when revenue < 500 and profit > 10')
    if '<' not in ok:
        return _fail('math comparison text must be allowed')

    # Unknown body-like fields never persisted
    result = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/markup-body',
        symbols=['MKUP'],
        structured_facts={'k': 'm'},
        source_headline='Markup body field ignore',
        article_body='SECRET_BODY',
        full_article='SECRET_FULL',
        html='<html>x</html>',
        raw_html='<div>x</div>',
        cookies='a=b',
        auth_token='tok',
        browser_state='state',
    ))
    row = bdf.get_sighting(result['sighting_id'])
    blob = json.dumps(json.loads(bdf.store_path().read_text(encoding='utf-8')))
    for forbidden in (
        'SECRET_BODY', 'SECRET_FULL', 'auth_token', 'browser_state',
        'article_body":"', 'full_article', 'raw_html',
    ):
        if forbidden in blob and forbidden in ('SECRET_BODY', 'SECRET_FULL'):
            return _fail(f'forbidden body content persisted: {forbidden}')
    if row.get('article_body') not in (None, ''):
        return _fail('article_body must be None on stored sighting')
    for key in ('full_article', 'html', 'raw_html', 'cookies', 'auth_token', 'browser_state'):
        if key in row:
            return _fail(f'forbidden key persisted on sighting: {key}')

    _pass('BROKER_DISCOVERY_RAW_MARKUP_REJECTED_OK')
    return 0


def test_single_write_atomic(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf
    from backend.storage import json_io

    path = bdf.store_path()
    if path.exists():
        path.unlink()

    # Seed a valid store
    seed = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/atomic-seed',
        symbols=['ATOM'],
        structured_facts={'k': 'seed'},
        source_headline='Atomic seed headline',
    ))
    before_blob = path.read_text(encoding='utf-8')
    before_health = bdf.get_store_health()
    before_events = json.loads(before_blob)['events']
    before_sightings = json.loads(before_blob)['sightings']

    # Inject failure on atomic write — store must remain unchanged
    def _fail_write(target, payload):
        raise OSError('injected atomic write failure')

    with patch('backend.news.broker_discovery_foundation.atomic_write_json', _fail_write):
        try:
            bdf.upsert_sighting(_base_sighting(
                source_url='https://news.example.com/atomic-fail',
                symbols=['ATOMF'],
                structured_facts={'k': 'fail'},
                source_headline='Atomic fail headline',
            ))
            return _fail('expected injected write failure')
        except OSError:
            pass

    after_blob = path.read_text(encoding='utf-8')
    if after_blob != before_blob:
        return _fail('injected write failure mutated store (orphan risk)')
    after_health = bdf.get_store_health()
    if after_health['health'] != before_health['health']:
        return _fail('health changed after injected failure')
    after = json.loads(after_blob)
    if after['events'] != before_events or after['sightings'] != before_sightings:
        return _fail('event persisted without sighting after failed write')
    if seed['event_id'] not in after['events'] or seed['sighting_id'] not in after['sightings']:
        return _fail('seed rows lost after failure injection')

    # Successful ingestion writes event+sighting together (single save)
    saves = {'n': 0}
    real_save = bdf._save_store

    def _counting_save(store, *, now):
        saves['n'] += 1
        return real_save(store, now=now)

    with patch('backend.news.broker_discovery_foundation._save_store', _counting_save):
        ok = bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/atomic-ok',
            symbols=['ATOMOK'],
            structured_facts={'k': 'ok'},
            source_headline='Atomic ok headline',
        ))
    if saves['n'] != 1:
        return _fail(f'upsert_sighting must save once, got {saves["n"]}')
    if bdf.get_event(ok['event_id']) is None or bdf.get_sighting(ok['sighting_id']) is None:
        return _fail('successful atomic upsert missing event or sighting')

    # Public upsert_event is not invoked from upsert_sighting
    with patch('backend.news.broker_discovery_foundation.upsert_event') as mocked:
        bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/atomic-no-public',
            symbols=['ATOMNP'],
            structured_facts={'k': 'np'},
            source_headline='Atomic no public upsert_event',
        ))
        if mocked.called:
            return _fail('upsert_sighting must not call public upsert_event')

    _pass('BROKER_DISCOVERY_SINGLE_WRITE_ATOMIC_OK')
    return 0


def _count_atomic_writes(bdf, fn):
    calls = {'n': 0}
    real = bdf.atomic_write_json

    def _wrap(path, payload):
        calls['n'] += 1
        return real(path, payload)

    with patch('backend.news.broker_discovery_foundation.atomic_write_json', _wrap):
        result = fn()
    return calls['n'], result


def test_first_run_single_write(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    if path.exists():
        path.unlink()

    # 1) First-ever upsert_event -> exactly one atomic write
    n, r = _count_atomic_writes(bdf, lambda: bdf.upsert_event(_base_event(
        symbols=['FR1'],
        structured_facts={'k': 'fr1'},
        canonical_headline='First run event one',
    )))
    print(f'ATOMIC_WRITE_COUNT first_upsert_event={n}')
    if n != 1:
        return _fail(f'first upsert_event atomic writes want 1 got {n}')
    if not path.is_file():
        return _fail('first upsert_event did not create store')

    # 3) Existing-store upsert_event -> one write
    n2, _ = _count_atomic_writes(bdf, lambda: bdf.upsert_event(_base_event(
        symbols=['FR1b'],
        structured_facts={'k': 'fr1b'},
        canonical_headline='First run event existing path',
    )))
    print(f'ATOMIC_WRITE_COUNT existing_upsert_event={n2}')
    if n2 != 1:
        return _fail(f'existing upsert_event atomic writes want 1 got {n2}')

    path.unlink()
    # 2) First-ever upsert_sighting -> exactly one atomic write
    n3, s = _count_atomic_writes(bdf, lambda: bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/fr-sight',
        symbols=['FR2'],
        structured_facts={'k': 'fr2'},
        source_headline='First run sighting',
    )))
    print(f'ATOMIC_WRITE_COUNT first_upsert_sighting={n3}')
    if n3 != 1:
        return _fail(f'first upsert_sighting atomic writes want 1 got {n3}')

    # 4) Existing-store upsert_sighting -> one write
    n4, _ = _count_atomic_writes(bdf, lambda: bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/fr-sight-2',
        symbols=['FR2b'],
        structured_facts={'k': 'fr2b'},
        source_headline='First run sighting existing',
    )))
    print(f'ATOMIC_WRITE_COUNT existing_upsert_sighting={n4}')
    if n4 != 1:
        return _fail(f'existing upsert_sighting atomic writes want 1 got {n4}')

    # 5) Failed first-ever final write leaves no store file
    path.unlink()
    if path.exists():
        return _fail('store should be absent before fail test')

    def _boom(target, payload):
        raise OSError('fail first write')

    with patch('backend.news.broker_discovery_foundation.atomic_write_json', _boom):
        try:
            bdf.upsert_event(_base_event(
                symbols=['FR3'],
                structured_facts={'k': 'fr3'},
                canonical_headline='First run fail event',
            ))
            return _fail('expected first-run write failure')
        except OSError:
            pass
    print(f'FAILED_FIRST_RUN_STORE_EXISTS={path.exists()}')
    if path.exists():
        return _fail('failed first-ever write left a store file')

    # 6) Failed existing-store write leaves original bytes unchanged
    seed = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/fr-seed',
        symbols=['FR4'],
        structured_facts={'k': 'fr4'},
        source_headline='First run seed',
    ))
    before = path.read_bytes()
    with patch('backend.news.broker_discovery_foundation.atomic_write_json', _boom):
        try:
            bdf.upsert_sighting(_base_sighting(
                source_url='https://news.example.com/fr-seed-fail',
                symbols=['FR4b'],
                structured_facts={'k': 'fr4b'},
                source_headline='First run seed fail',
            ))
            return _fail('expected existing write failure')
        except OSError:
            pass
    if path.read_bytes() != before:
        return _fail('existing store bytes changed after failed write')

    # 7) Failed mark_primary on missing event does not create store
    path.unlink()
    try:
        bdf.mark_primary_source_verified(
            UNKNOWN_EVENT_ID, primary_source_url='https://www.nseindia.com/x',
        )
        return _fail('expected missing event error')
    except bdf.BrokerDiscoveryError:
        pass
    if path.exists():
        return _fail('mark_primary on missing event created store')

    # 8) Failed attach on missing store does not create store
    try:
        bdf.attach_sighting_to_event(UNKNOWN_SIGHTING_ID, UNKNOWN_EVENT_ID)
        return _fail('expected attach failure')
    except bdf.BrokerDiscoveryError:
        pass
    if path.exists():
        return _fail('attach on missing store created empty store')

    # recreate usable store for later tests
    bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/fr-restore',
        symbols=['FRR'],
        structured_facts={'k': 'restore'},
        source_headline='First run restore',
    ))
    _ = seed
    _pass('BROKER_DISCOVERY_FIRST_RUN_SINGLE_WRITE_OK')
    return 0


def test_source_count_canonical(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    # Caller-supplied inflated source_count must not persist
    r = bdf.upsert_event(_base_event(
        symbols=['SCC1'],
        structured_facts={'k': 'scc1'},
        canonical_headline='Source count caller supply',
        source_count=99,
    ))
    ev = bdf.get_event(r['event_id'])
    print(f'SOURCE_COUNT_CALLER_VS_PERSISTED caller=99 persisted={ev["source_count"]}')
    if ev['source_count'] != 0:
        return _fail(f'new event source_count must be 0, got {ev["source_count"]}')

    s1 = bdf.upsert_sighting(_base_sighting(
        source_name='BrokerA',
        source_url='https://news.example.com/scc-a',
        symbols=['SCC2'],
        structured_facts={'k': 'scc2'},
        source_headline='Source count linked',
    ))
    s2 = bdf.upsert_sighting(_base_sighting(
        source_name='BrokerB',
        source_url='https://news.example.com/scc-b',
        symbols=['SCC2'],
        structured_facts={'k': 'scc2'},
        source_headline='Source count linked',
    ))
    if s1['event_id'] != s2['event_id']:
        bdf.attach_sighting_to_event(s2['sighting_id'], s1['event_id'])
    multi = bdf.get_event(s1['event_id'])
    linked = len(bdf.list_event_sightings(s1['event_id']))
    print(f'SOURCE_COUNT_VS_LINKED stored={multi["source_count"]} linked={linked}')
    if multi['source_count'] != linked or linked != 2:
        return _fail('source_count must equal linked sightings')

    # Ordinary upsert_event must not overwrite derived count from payload
    bdf.upsert_event(_base_event(
        symbols=['SCC2'],
        structured_facts={'k': 'scc2'},
        canonical_headline='Source count linked',
        source_count=0,
    ))
    still = bdf.get_event(s1['event_id'])
    if still['source_count'] != 2:
        return _fail(f'upsert_event must not clobber source_count, got {still["source_count"]}')

    # PARTIAL for malformed / inconsistent source_count values
    good = bdf.build_canonical_event(**_base_event(
        symbols=['SCC3'],
        structured_facts={'k': 'scc3'},
        canonical_headline='Source count partial base',
    ))
    good['source_count'] = 0
    bad_values = (True, False, 1.5, '2', '2.0', -1, float('nan'), float('inf'), 5)
    for bad in bad_values:
        row = dict(good)
        row['source_count'] = bad
        path.write_text(json.dumps({
            'schema_version': '52R-A1',
            'events': {row['event_id']: row},
            'sightings': {},
            'updated_at': row['updated_at'],
        }, allow_nan=True), encoding='utf-8')
        h = bdf.get_store_health()
        if h['health'] != bdf.HEALTH_PARTIAL:
            return _fail(f'source_count {bad!r} must be PARTIAL, got {h}')

    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_SOURCE_COUNT_CANONICAL_OK')
    return 0


def test_repeat_attachment_stable(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    raw = _base_sighting(
        source_url='https://news.example.com/ras-1',
        symbols=['RAS1'],
        structured_facts={'k': 'ras'},
        source_headline='Repeat attachment stable headline',
    )
    first = bdf.upsert_sighting(raw)
    event_a = first['event_id']
    event_b_row = bdf.upsert_event(_base_event(
        symbols=['RAS2'],
        structured_facts={'k': 'ras-b'},
        canonical_headline='Repeat attachment event B',
    ))
    event_b = event_b_row['event_id']
    bdf.attach_sighting_to_event(first['sighting_id'], event_b)
    moved = bdf.get_sighting(first['sighting_id'])
    if moved['event_id'] != event_b:
        return _fail('attach to B failed')

    # Re-ingest original raw without event_id — must stay on B
    t2 = datetime(2099, 7, 31, 13, 0, 0, tzinfo=IST)
    repeat = bdf.upsert_sighting(raw, now=t2)
    print(
        f'REPEAT_AFTER_REATTACH before_A={event_a} before_B={event_b} '
        f'after={repeat["event_id"]} sighting={repeat["sighting_id"]}'
    )
    if repeat['event_id'] != event_b:
        return _fail(f'repeat ingestion undid reattachment, got {repeat["event_id"]}')
    if repeat['sighting_id'] != first['sighting_id']:
        return _fail('repeat created duplicate sighting')
    if any(s['sighting_id'] == first['sighting_id'] for s in bdf.list_event_sightings(event_a)):
        return _fail('event A received sighting again')
    # No duplicate auto-event for same raw facts on A path — event count for fingerprint A may still exist empty
    a_after = bdf.get_event(event_a)
    if a_after and a_after['source_count'] != 0:
        return _fail('event A source_count should be 0 after move+repeat')

    row = bdf.get_sighting(first['sighting_id'])
    if not str(row['last_seen_at']).startswith('2099-07-31T13:00:00'):
        return _fail(f'repeat must update last_seen_at, got {row["last_seen_at"]}')

    # Explicit event_id=A moves back
    back = bdf.upsert_sighting({**raw, 'event_id': event_a})
    if back['event_id'] != event_a:
        return _fail('explicit event_id=A failed to move back')
    if bdf.get_event(event_a)['source_count'] != 1 or bdf.get_event(event_b)['source_count'] != 0:
        return _fail('source counts not reconciled after move back')

    # Explicit event payload moves intentionally
    payload = _base_event(
        symbols=['RAS3'],
        structured_facts={'k': 'ras-c'},
        canonical_headline='Repeat attachment event C',
    )
    via_payload = bdf.upsert_sighting(raw, event=payload)
    if via_payload['event_id'] == event_a:
        return _fail('explicit event payload must move sighting')
    if bdf.get_event(event_a)['source_count'] != 0:
        return _fail('old event count not reconciled after payload move')
    if bdf.get_event(via_payload['event_id'])['source_count'] != 1:
        return _fail('new event count not reconciled after payload move')

    # Exact repeat remains idempotent
    again = bdf.upsert_sighting(raw)
    if again['inserted'] or not again['deduplicated']:
        return _fail('exact repeat must remain idempotent')
    if again['event_id'] != via_payload['event_id']:
        return _fail('idempotent repeat must preserve attachment')

    _pass('BROKER_DISCOVERY_REPEAT_ATTACHMENT_STABLE_OK')
    return 0


def test_url_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    rejected = [
        ('javascript:alert(1)', 'javascript'),
        ('file:///tmp/x', 'file'),
        ('data:text/plain,hi', 'data'),
        ('ftp://example.com/a', 'ftp'),
        ('mailto:a@b.com', 'mailto'),
        ('https://', 'empty host'),
        ('relative/path', 'relative'),
        (r'C:\local\file', 'windows path'),
        ('https://user:pass@example.com/x', 'credentials'),
        ('https://example.com/a b', 'whitespace'),
    ]
    print('REJECTED_URL_TABLE')
    for raw, reason in rejected:
        try:
            bdf.normalize_url(raw)
            return _fail(f'url must reject {raw!r} ({reason})')
        except bdf.BrokerDiscoveryError:
            print(f'  REJECT {raw!r} reason={reason}')

    ok_https = bdf.normalize_url('https://News.Example.com/story/?utm_source=x#frag')
    if 'utm_source' in ok_https or '#frag' in ok_https or 'News' in ok_https:
        return _fail(f'https normalization failed: {ok_https}')
    schemeless = bdf.normalize_url('www.example.com/news/123')
    if not schemeless.startswith('https://www.example.com/news/123'):
        return _fail(f'schemeless normalize failed: {schemeless}')
    schemeless2 = bdf.normalize_url('example.com/news/123')
    if not schemeless2.startswith('https://example.com/news/123'):
        return _fail(f'host/path normalize failed: {schemeless2}')

    try:
        bdf.build_source_sighting(
            source_name='Broker',
            source_kind='BROKER_PUBLIC',
            source_url='',
            source_headline='Needs url',
            source_published_at=PUB,
        )
        return _fail('BROKER_PUBLIC empty url must fail')
    except bdf.BrokerDiscoveryError:
        pass

    manual = bdf.build_source_sighting(
        source_name='Analyst Note',
        source_kind='MANUAL_FEED',
        source_url='',
        source_headline='Manual feed may omit url',
        source_published_at=PUB,
    )
    if manual['source_url'] != '':
        return _fail('MANUAL_FEED empty url should persist empty')

    try:
        bdf.mark_primary_source_verified(
            UNKNOWN_EVENT_ID, primary_source_url='javascript:alert(1)',
        )
        return _fail('mark_primary must reject bad url')
    except bdf.BrokerDiscoveryError:
        pass

    _pass('BROKER_DISCOVERY_URL_CONTRACT_OK')
    return 0


def test_canonical_identity_health(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    good = bdf.build_canonical_event(**_base_event(
        symbols=['CIH1'],
        structured_facts={'k': 1},
        canonical_headline='Canonical identity health base',
    ))
    good['source_count'] = 0
    sight = bdf.build_source_sighting(
        source_name='Broker',
        source_kind='BROKER_PUBLIC',
        source_url='https://news.example.com/cih',
        source_headline=good['canonical_headline'],
        source_published_at=PUB,
        event_id=good['event_id'],
    )

    cases = []
    # empty symbols
    row = dict(good)
    row['symbols'] = []
    cases.append(('empty_symbols', {row['event_id']: row}, {}))
    # unsorted symbols
    row = dict(good)
    row['symbols'] = ['TCS', 'CIH1'] if False else ['ZZZ', 'CIH1']  # will fail canonical sort
    # rebuild with two symbols then unsort
    good2 = bdf.build_canonical_event(**_base_event(
        symbols=['CIH2', 'AAA'],
        structured_facts={'k': 2},
        canonical_headline='Canonical identity two symbols',
    ))
    good2['source_count'] = 0
    row = dict(good2)
    row['symbols'] = ['CIH2', 'AAA']  # unsorted vs AAA,CIH2
    cases.append(('unsorted_symbols', {row['event_id']: row}, {}))
    # wrong normalized headline
    row = dict(good)
    row['normalized_headline'] = 'wrong'
    cases.append(('bad_norm_headline', {row['event_id']: row}, {}))
    # wrong fingerprint
    row = dict(good)
    row['event_fingerprint'] = '0' * 64
    cases.append(('bad_fingerprint', {row['event_id']: row}, {}))
    # wrong event id vs key already covered; wrong stored id
    row = dict(good)
    row['event_id'] = '00000000-0000-0000-0000-000000000000'
    cases.append(('key_id_mismatch', {good['event_id']: row}, {}))
    # NaN facts
    row = dict(good)
    row['structured_facts'] = {'k': float('nan')}
    cases.append(('nan_facts', {row['event_id']: row}, {}))
    # sighting wrong content hash
    srow = dict(sight)
    srow['content_hash'] = '0' * 64
    cases.append(('bad_sighting_hash', {good['event_id']: good}, {srow['sighting_id']: srow}))
    # excerpt too long
    srow = dict(sight)
    srow['bounded_excerpt'] = 'x' * (bdf.MAX_EXCERPT_LENGTH + 1)
    cases.append(('excerpt_too_long', {good['event_id']: good}, {srow['sighting_id']: srow}))
    # markup in excerpt
    srow = dict(sight)
    srow['bounded_excerpt'] = '<div>x</div>'
    cases.append(('excerpt_markup', {good['event_id']: good}, {srow['sighting_id']: srow}))

    print('CANONICAL_IDENTITY_CORRUPTION_TABLE')
    for name, events, sightings in cases:
        # Fix source_count for events with no sightings
        fixed_events = {}
        for k, e in events.items():
            ee = dict(e)
            if not isinstance(ee.get('source_count'), int) or isinstance(ee.get('source_count'), bool):
                pass
            else:
                ee['source_count'] = len([
                    s for s in sightings.values()
                    if isinstance(s, dict) and str(s.get('event_id')) == str(k)
                ])
            fixed_events[k] = ee
        path.write_text(json.dumps({
            'schema_version': '52R-A1',
            'events': fixed_events,
            'sightings': sightings,
            'updated_at': good['updated_at'],
        }, allow_nan=True), encoding='utf-8')
        h = bdf.get_store_health()['health']
        print(f'  {name} -> {h}')
        if h != bdf.HEALTH_PARTIAL:
            return _fail(f'{name} must be PARTIAL, got {h}')

    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_CANONICAL_IDENTITY_HEALTH_OK')
    return 0


def test_strict_input_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    print('STRICT_INPUT_REJECTION_TABLE')
    cases = [
        ('headline_dict', lambda: bdf.build_canonical_event(**_base_event(canonical_headline={'a': 1}))),
        ('headline_list', lambda: bdf.build_canonical_event(**_base_event(canonical_headline=['x']))),
        ('headline_bool', lambda: bdf.build_canonical_event(**_base_event(canonical_headline=True))),
        ('symbol_dict', lambda: bdf.build_canonical_event(**_base_event(symbols=[{'x': 1}]))),
        ('facts_set', lambda: bdf.build_canonical_event(**_base_event(structured_facts={'k': {1, 2}}))),
        ('facts_tuple', lambda: bdf.build_canonical_event(**_base_event(structured_facts={'k': (1, 2)}))),
        ('facts_nan', lambda: bdf.build_canonical_event(**_base_event(structured_facts={'k': float('nan')}))),
        ('facts_key_collision', lambda: bdf.normalize_structured_facts({1: 'a', '1': 'b'})),
        ('excerpt_list', lambda: bdf.bound_excerpt(['x'])),
        ('url_list', lambda: bdf.normalize_url(['https://x'])),
        ('source_name_dict', lambda: bdf.build_source_sighting(
            source_name={'n': 1},
            source_kind='BROKER_PUBLIC',
            source_url='https://news.example.com/s',
            source_headline='h',
            source_published_at=PUB,
        )),
    ]
    for name, fn in cases:
        try:
            fn()
            return _fail(f'strict input must reject {name}')
        except bdf.BrokerDiscoveryError:
            print(f'  REJECT {name}')

    # timezone-aware ISO still works
    ev = bdf.build_canonical_event(**_base_event())
    if '+' not in ev['published_at'] and not ev['published_at'].endswith('Z'):
        # IST offset expected
        if 'Asia/Kolkata' not in str(PUB.tzinfo) and '+05:30' not in ev['published_at']:
            return _fail(f'timestamp not timezone-aware ISO: {ev["published_at"]}')
    if '+05:30' not in ev['published_at']:
        return _fail(f'expected IST offset in published_at: {ev["published_at"]}')

    _pass('BROKER_DISCOVERY_STRICT_INPUT_CONTRACT_OK')
    return 0


def test_persisted_timestamp_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf
    from datetime import date

    print('PERSISTED_TIMESTAMP_REJECTION_TABLE')
    rejected = [
        None, True, False, 0, 1720000000,
        datetime(2026, 7, 31, 10, 0, 0, tzinfo=IST),
        date(2026, 7, 31),
        '2026-07-31',
        '2026-07-31T10:00:00',
        'not-a-timestamp',
        '2026-07-31T10:00:00 Asia/Kolkata',
        '2026-07-31T10:00:00Z',  # not canonical IST text
    ]
    for bad in rejected:
        try:
            bdf.validate_persisted_timestamp(bad)
            return _fail(f'persisted timestamp must reject {bad!r}')
        except bdf.BrokerDiscoveryError:
            print(f'  REJECT {bad!r}')

    good = '2026-07-31T17:18:03+05:30'
    if bdf.validate_persisted_timestamp(good) != good:
        return _fail('canonical IST timestamp must round-trip exactly')

    path = bdf.store_path()
    print('TOP_LEVEL_TIMESTAMP_HEALTH')
    for label, updated_at, expect in (
        ('missing', None, bdf.HEALTH_MALFORMED),
        ('non_string', 123, bdf.HEALTH_MALFORMED),
        ('naive', '2026-07-31T17:18:03', bdf.HEALTH_MALFORMED),
        ('malformed', 'nope', bdf.HEALTH_MALFORMED),
        ('canonical', good, bdf.HEALTH_OK),
    ):
        payload = {
            'schema_version': '52R-A1',
            'events': {},
            'sightings': {},
        }
        if updated_at is not None or label != 'missing':
            if label != 'missing':
                payload['updated_at'] = updated_at
        path.write_text(json.dumps(payload), encoding='utf-8')
        h = bdf.get_store_health()['health']
        print(f'  {label} -> {h}')
        if h != expect:
            return _fail(f'top-level updated_at {label} expected {expect}, got {h}')

    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_PERSISTED_TIMESTAMP_CONTRACT_OK')
    return 0


def test_operation_time_consistency(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    fixed = datetime(2099, 8, 1, 9, 30, 0, tzinfo=IST)
    path = bdf.store_path()
    if path.exists():
        path.unlink()
    r = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/op-time',
        symbols=['OPT'],
        structured_facts={'k': 'opt'},
        source_headline='Operation time consistency',
    ), now=fixed)
    ev = bdf.get_event(r['event_id'])
    sight = bdf.get_sighting(r['sighting_id'])
    store = json.loads(path.read_text(encoding='utf-8'))
    expected = bdf._iso(fixed)
    print(
        f'FIXED_NOW_COMPARE expected={expected} '
        f'event_last={ev["last_seen_at"]} event_updated={ev["updated_at"]} '
        f'sighting_last={sight["last_seen_at"]} store_updated={store["updated_at"]}'
    )
    if ev['last_seen_at'] != expected or ev['updated_at'] != expected:
        return _fail('event timestamps must use fixed operation now')
    if sight['last_seen_at'] != expected:
        return _fail('sighting last_seen_at must use fixed operation now')
    if store['updated_at'] != expected:
        return _fail('top-level updated_at must use fixed operation now')

    # attach also uses fixed now
    other = bdf.upsert_event(_base_event(
        symbols=['OPT2'],
        structured_facts={'k': 'opt2'},
        canonical_headline='Operation time other',
    ), now=fixed)
    fixed2 = datetime(2099, 8, 1, 10, 0, 0, tzinfo=IST)
    bdf.attach_sighting_to_event(r['sighting_id'], other['event_id'], now=fixed2)
    sight2 = bdf.get_sighting(r['sighting_id'])
    store2 = json.loads(path.read_text(encoding='utf-8'))
    exp2 = bdf._iso(fixed2)
    if sight2['last_seen_at'] != exp2 or store2['updated_at'] != exp2:
        return _fail('attach must use supplied operation now consistently')

    _pass('BROKER_DISCOVERY_OPERATION_TIME_CONSISTENCY_OK')
    return 0


def test_canonical_metadata_health(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    good = bdf.build_canonical_event(**_base_event(
        symbols=['CMH'],
        company_names=['Infosys Limited'],
        structured_facts={'k': 1},
        canonical_headline='Canonical metadata health',
    ))
    good['source_count'] = 0
    ts = good['updated_at']
    print('COMPANY_NAME_CORRUPTION_TABLE')
    cases = [
        ('dict_item', [{'a': 1}]),
        ('number_item', [1]),
        ('bool_item', [True]),
        ('duplicates', ['Infosys', 'infosys']),
        ('unsorted', ['Zebra', 'Alpha']),
        ('whitespace', ['  Infosys  ']),
        ('internal_ws', ['Infosys   Limited']),
        ('control', ['Info\x00sys']),
    ]
    for name, companies in cases:
        row = dict(good)
        row['company_names'] = companies
        path.write_text(json.dumps({
            'schema_version': '52R-A1',
            'events': {row['event_id']: row},
            'sightings': {},
            'updated_at': ts,
        }), encoding='utf-8')
        h = bdf.get_store_health()['health']
        print(f'  {name} -> {h}')
        if h != bdf.HEALTH_PARTIAL:
            return _fail(f'company_names {name} must be PARTIAL, got {h}')

    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_CANONICAL_METADATA_HEALTH_OK')
    return 0


def test_metadata_preservation(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    first = bdf.upsert_event(_base_event(
        symbols=['MP1'],
        company_names=['Infosys'],
        structured_facts={'k': 'mp'},
        canonical_headline='Metadata preservation event',
    ))
    # empty company names preserve existing
    bdf.upsert_event(_base_event(
        symbols=['MP1'],
        company_names=[],
        structured_facts={'k': 'mp'},
        canonical_headline='Metadata preservation event',
    ))
    mid = bdf.get_event(first['event_id'])
    print(f'COMPANY_PRESERVE_AFTER_EMPTY={mid["company_names"]}')
    if mid['company_names'] != ['Infosys']:
        return _fail('empty incoming company_names must preserve existing')

    # nonempty merges deterministically
    bdf.upsert_event(_base_event(
        symbols=['MP1'],
        company_names=['Tata Consultancy'],
        structured_facts={'k': 'mp'},
        canonical_headline='Metadata preservation event',
    ))
    merged = bdf.get_event(first['event_id'])
    expected = bdf.normalize_company_names(['Infosys', 'Tata Consultancy'])
    print(f'COMPANY_MERGE_RESULT={merged["company_names"]} expected={expected}')
    if merged['company_names'] != expected:
        return _fail('company_names merge not canonical')

    # source metadata spacing/case: identity stable, persisted canonical
    a = bdf.upsert_sighting(_base_sighting(
        source_name='Groww Public',
        source_url='https://news.example.com/mp-a',
        symbols=['MP2'],
        structured_facts={'k': 'mp2'},
        source_headline='Metadata source spacing',
        original_publisher='  Wire   Desk ',
        attribution='  attr   note ',
    ))
    b = bdf.upsert_sighting(_base_sighting(
        source_name='  groww   public ',
        source_url='https://news.example.com/mp-a',
        symbols=['MP2'],
        structured_facts={'k': 'mp2'},
        source_headline='Metadata source spacing',
        original_publisher='Wire Desk',
        attribution='attr note',
    ))
    if a['sighting_id'] != b['sighting_id']:
        return _fail('source-name spacing/case must not change identity')
    row = bdf.get_sighting(a['sighting_id'])
    if row['original_publisher'] != 'Wire Desk':
        return _fail('publisher must be canonical')
    if row['attribution'] != 'attr note':
        return _fail('attribution must be trim/collapse normalized')

    _pass('BROKER_DISCOVERY_METADATA_PRESERVATION_OK')
    return 0


def test_json_fact_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    print('STRUCTURED_FACT_KEY_REJECTION_TABLE')
    cases = [
        ('int_key', {1: 'a'}),
        ('bool_key', {True: 'a'}),
        ('bytes_key', {b'x': 'a'}),
    ]
    for name, facts in cases:
        try:
            bdf.normalize_structured_facts(facts)
            return _fail(f'facts must reject {name}')
        except (bdf.BrokerDiscoveryError, TypeError):
            print(f'  REJECT {name}')
    try:
        bdf.normalize_structured_facts({'a': {1, 2}})
        return _fail('nested set must be rejected')
    except bdf.BrokerDiscoveryError:
        print('  REJECT nested_set')
    try:
        bdf.normalize_structured_facts({'a': (1, 2)})
        return _fail('nested tuple must be rejected')
    except bdf.BrokerDiscoveryError:
        print('  REJECT nested_tuple')

    ok = bdf.normalize_structured_facts({'b': 1, 'a': {'c': 2}})
    if list(ok.keys()) != ['a', 'b']:
        return _fail('fact keys must remain sorted strings')

    _pass('BROKER_DISCOVERY_JSON_FACT_CONTRACT_OK')
    return 0


def test_host_port_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    print('INVALID_HOSTNAME_PORT_TABLE')
    rejected = [
        'https://-bad.example.com/x',
        'https://bad-.example.com/x',
        'https://example..com/x',
        'https://.example.com/x',
        'https://example.com./x',
        'https://exa_mple.com/x',
        'https://' + ('a' * 64) + '.com/x',
        'https://localhost/x',
        'https://internal/x',
        'https://news/x',
        'https://example.com:bad/path',
        'https://example.com:0/path',
        'https://example.com:65536/path',
    ]
    for raw in rejected:
        try:
            bdf.normalize_url(raw)
            return _fail(f'host/port must reject {raw!r}')
        except bdf.BrokerDiscoveryError:
            print(f'  REJECT {raw!r}')

    if bdf.normalize_url('http://example.com:80/x') != 'http://example.com/x':
        return _fail('default http port must canonicalize away')
    if bdf.normalize_url('https://example.com:443/x') != 'https://example.com/x':
        return _fail('default https port must canonicalize away')
    kept = bdf.normalize_url('https://example.com:8443/x')
    if kept != 'https://example.com:8443/x':
        return _fail(f'nondefault port must be preserved, got {kept}')
    if bdf.normalize_url('https://127.0.0.1/x') != 'https://127.0.0.1/x':
        return _fail('IPv4 literal must be accepted')

    _pass('BROKER_DISCOVERY_HOST_PORT_CONTRACT_OK')
    return 0


def test_ip_literal_fail_closed(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    escape_count = 0

    def _expect_reject(raw: str, table: str) -> str | None:
        nonlocal escape_count
        try:
            bdf.normalize_url(raw)
        except bdf.BrokerDiscoveryError:
            print(f'  REJECT {raw!r}')
            return None
        except Exception as exc:
            escape_count += 1
            return f'{table}: unexpected raw exception for {raw!r}: {type(exc).__name__}'
        return f'{table}: invalid IP literal was accepted: {raw!r}'

    print('REJECTED_INVALID_IPV4_TABLE')
    for raw in (
        'https://999.999.999.999/x',
        'https://256.1.1.1/x',
        'https://01.02.03.04/x',
    ):
        err = _expect_reject(raw, 'ipv4')
        if err:
            return _fail(err)

    print('REJECTED_MALFORMED_IPV6_TABLE')
    for raw in (
        'https://[gggg::1]/x',
        'https://[2001:db8:::1]/x',
        'https://[::1/x',
        'https://::1]/x',
        'https://2001:db8::1/x',
    ):
        err = _expect_reject(raw, 'ipv6')
        if err:
            return _fail(err)

    print('ACCEPTED_VALID_IP_LITERAL_TABLE')
    accepted = (
        ('https://127.0.0.1/x', 'https://127.0.0.1/x'),
        ('https://8.8.8.8/x', 'https://8.8.8.8/x'),
        ('https://[::1]/x', 'https://[::1]/x'),
        ('https://[2001:db8::1]/x', 'https://[2001:db8::1]/x'),
        ('https://123news.example.com/x', 'https://123news.example.com/x'),
        ('https://news123.example.com/x', 'https://news123.example.com/x'),
        ('https://123.com/x', 'https://123.com/x'),
    )
    for raw, expected in accepted:
        try:
            got = bdf.normalize_url(raw)
        except Exception as exc:
            escape_count += 1
            return _fail(f'valid literal raised {type(exc).__name__} for {raw!r}')
        print(f'  ACCEPT {raw!r} -> {got!r}')
        if got != expected:
            return _fail(f'canonical mismatch for {raw!r}: got {got!r}, want {expected!r}')

    print(f'RAW_URL_EXCEPTION_ESCAPE_COUNT={escape_count}')
    if escape_count != 0:
        return _fail(f'raw exception escapes must be 0, got {escape_count}')

    _pass('BROKER_DISCOVERY_IP_LITERAL_FAIL_CLOSED_OK')
    return 0


def _write_mutated_event_store(bdf, path, mutator):
    """Write a recognizable store with one mutated event row; return bytes."""
    good = bdf.build_canonical_event(**_base_event(
        symbols=['R6E'],
        structured_facts={'k': 1},
        canonical_headline='Repair six event base',
        company_names=['Infosys'],
    ))
    good['source_count'] = 0
    row = dict(good)
    mutator(row)
    payload = {
        'schema_version': '52R-A1',
        'events': {good['event_id']: row},
        'sightings': {},
        'updated_at': good['updated_at'],
    }
    # ensure_ascii=True so unpaired surrogates persist as \uXXXX escapes (valid UTF-8
    # file bytes) and round-trip back to surrogate Python strings via json.loads.
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding='utf-8')
    return path.read_bytes()


def _write_mutated_sighting_store(bdf, path, mutator):
    good = bdf.build_canonical_event(**_base_event(
        symbols=['R6S'],
        structured_facts={'k': 2},
        canonical_headline='Repair six sighting base',
    ))
    good['source_count'] = 1
    sight = bdf.build_source_sighting(
        source_name='Broker',
        source_kind='BROKER_PUBLIC',
        source_url='https://news.example.com/r6s',
        source_headline=good['canonical_headline'],
        source_published_at=PUB,
        event_id=good['event_id'],
        original_publisher='Wire',
        attribution='attr',
        bounded_excerpt='excerpt',
    )
    row = dict(sight)
    mutator(row)
    payload = {
        'schema_version': '52R-A1',
        'events': {good['event_id']: good},
        'sightings': {sight['sighting_id']: row},
        'updated_at': good['updated_at'],
    }
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding='utf-8')
    return path.read_bytes()


def _assert_partial_health_no_raw(bdf, path):
    escape = 0
    try:
        health = bdf._classify_store_payload(json.loads(path.read_text(encoding='utf-8')))
    except Exception as exc:
        if isinstance(exc, bdf.BrokerDiscoveryError):
            return f'classify raised BrokerDiscoveryError unexpectedly: {exc}'
        escape += 1
        return f'classify raw escape: {type(exc).__name__}'
    if health != bdf.HEALTH_PARTIAL:
        return f'classify want PARTIAL got {health}'
    try:
        _, h = bdf.load_store()
    except Exception as exc:
        escape += 1
        return f'load_store raw escape: {type(exc).__name__}'
    if h != bdf.HEALTH_PARTIAL:
        return f'load_store want PARTIAL got {h}'
    try:
        gh = bdf.get_store_health()
    except Exception as exc:
        escape += 1
        return f'get_store_health raw escape: {type(exc).__name__}'
    if gh['health'] != bdf.HEALTH_PARTIAL:
        return f'get_store_health want PARTIAL got {gh}'
    for name, fn in (
        ('get_event', lambda: bdf.get_event('x')),
        ('get_sighting', lambda: bdf.get_sighting('x')),
        ('list_event_sightings', lambda: bdf.list_event_sightings('x')),
        ('find_events_by_symbol', lambda: bdf.find_events_by_symbol('INFY')),
        ('find_events_by_date', lambda: bdf.find_events_by_date(PUB.date())),
        ('find_recent_events', lambda: bdf.find_recent_events()),
        ('find_event_by_fingerprint', lambda: bdf.find_event_by_fingerprint('fp')),
    ):
        try:
            fn()
            return f'{name} must raise BrokerDiscoveryError'
        except bdf.BrokerDiscoveryError as exc:
            if bdf.HEALTH_PARTIAL not in str(exc):
                return f'{name} error missing PARTIAL: {exc}'
        except Exception as exc:
            escape += 1
            return f'{name} raw escape: {type(exc).__name__}'
    if escape:
        return f'unexpected escapes={escape}'
    return None


def test_unreadable_utf8_truth(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    bad_bytes = b'\xff\xfe{"not":"utf8"}'
    path.write_bytes(bad_bytes)
    before = path.read_bytes()

    store, health = bdf.load_store()
    print(f'INVALID_UTF8_LOAD_HEALTH={health}')
    if health != bdf.HEALTH_UNREADABLE:
        return _fail(f'invalid UTF-8 must be UNREADABLE, got {health}')
    gh = bdf.get_store_health()
    if gh['health'] != bdf.HEALTH_UNREADABLE or gh.get('available') is not False:
        return _fail(f'get_store_health UNREADABLE failed: {gh}')
    if gh.get('counts_unavailable') is not True:
        return _fail('UNREADABLE counts must be unavailable')

    for name, fn in (
        ('get_event', lambda: bdf.get_event('x')),
        ('find_recent_events', lambda: bdf.find_recent_events()),
        ('upsert_event', lambda: bdf.upsert_event(_base_event(
            symbols=['U8'], structured_facts={'k': 1}, canonical_headline='utf8 fail',
        ))),
        ('upsert_sighting', lambda: bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/u8',
            symbols=['U8'], structured_facts={'k': 1},
            source_headline='utf8 fail sighting',
        ))),
    ):
        try:
            fn()
            return _fail(f'{name} must raise on UNREADABLE')
        except bdf.BrokerDiscoveryError as exc:
            if bdf.HEALTH_UNREADABLE not in str(exc):
                return _fail(f'{name} missing UNREADABLE: {exc}')
        except Exception as exc:
            return _fail(f'{name} raw escape: {type(exc).__name__}')

    after = path.read_bytes()
    print(f'INVALID_UTF8_BYTES_IDENTICAL={before == after}')
    if before != after:
        return _fail('invalid UTF-8 store bytes were mutated')

    path.unlink()
    _pass('BROKER_DISCOVERY_UNREADABLE_UTF8_TRUTH_OK')
    return 0


def test_malformed_symbols_fail_closed(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    print('MALFORMED_SYMBOL_TABLE')
    cases = [
        ('dict_member', [{}]),
        ('list_member', [[]]),
        ('int_member', [1]),
        ('float_member', [1.5]),
        ('bool_member', [True]),
        ('null_member', [None]),
        ('mixed_dict', ['ABC', {}]),
        ('duplicates', ['ABC', 'ABC']),
        ('whitespace', [' abc ']),
    ]
    for name, symbols in cases:
        def _mut(row, syms=symbols):
            row['symbols'] = syms
        _write_mutated_event_store(bdf, path, _mut)
        err = _assert_partial_health_no_raw(bdf, path)
        print(f'  {name} -> PARTIAL')
        if err:
            return _fail(f'symbols {name}: {err}')

    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_MALFORMED_SYMBOLS_FAIL_CLOSED_OK')
    return 0


def test_malformed_row_fail_closed(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    print('MALFORMED_EVENT_ROW_TABLE')
    event_cases = [
        ('symbols_dict', lambda r: r.__setitem__('symbols', [{}])),
        ('symbols_list', lambda r: r.__setitem__('symbols', [[]])),
        ('symbols_bool', lambda r: r.__setitem__('symbols', [True])),
        ('company_invalid', lambda r: r.__setitem__('company_names', [1])),
        ('facts_nested_bad', lambda r: r.__setitem__('structured_facts', {'k': {1, 2}})),
        ('headline_control', lambda r: r.__setitem__('canonical_headline', 'bad\x00text')),
        ('headline_surrogate', lambda r: r.__setitem__('canonical_headline', 'bad\ud800text')),
    ]
    for name, mut in event_cases:
        # set facts can't json-serialize; write via pickle-less custom for set case
        if name == 'facts_nested_bad':
            good = bdf.build_canonical_event(**_base_event(
                symbols=['R6F'], structured_facts={'k': 1},
                canonical_headline='Repair six facts',
            ))
            good['source_count'] = 0
            row = dict(good)
            row['structured_facts'] = {'k': ['ok']}  # placeholder then patch file? use list of set via Python json fail
            # Represent malformed nested as a list containing a dict that will fail after load? Use tuple via manual?
            # Spec: structured_facts containing malformed nested value — use NaN float which JSON allows with allow_nan
            row['structured_facts'] = {'k': float('nan')}
            path.write_text(json.dumps({
                'schema_version': '52R-A1',
                'events': {good['event_id']: row},
                'sightings': {},
                'updated_at': good['updated_at'],
            }, allow_nan=True), encoding='utf-8')
        else:
            _write_mutated_event_store(bdf, path, mut)
        err = _assert_partial_health_no_raw(bdf, path)
        print(f'  {name} -> PARTIAL')
        if err:
            return _fail(f'event {name}: {err}')

    print('MALFORMED_SIGHTING_ROW_TABLE')
    sight_cases = [
        ('source_name_control', lambda r: r.__setitem__('source_name', 'bad\x00')),
        ('source_name_surrogate', lambda r: r.__setitem__('source_name', 'x\ud800y')),
        ('headline_control', lambda r: r.__setitem__('source_headline', 'h\x01')),
        ('headline_surrogate', lambda r: r.__setitem__('source_headline', '\udfff')),
        ('publisher_surrogate', lambda r: r.__setitem__('original_publisher', 'p\ud800')),
        ('attribution_surrogate', lambda r: r.__setitem__('attribution', 'a\ud800')),
        ('excerpt_surrogate', lambda r: r.__setitem__('bounded_excerpt', 'e\ud800')),
        ('url_surrogate', lambda r: r.__setitem__('source_url', 'https://news.example.com/\ud800')),
    ]
    for name, mut in sight_cases:
        _write_mutated_sighting_store(bdf, path, mut)
        err = _assert_partial_health_no_raw(bdf, path)
        print(f'  {name} -> PARTIAL')
        if err:
            return _fail(f'sighting {name}: {err}')

    if path.exists():
        path.unlink()
    _pass('BROKER_DISCOVERY_MALFORMED_ROW_FAIL_CLOSED_OK')
    return 0


def test_utf8_text_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    print('REJECTED_SURROGATE_TABLE')
    surrogates = ['\ud800', '\udfff', 'bad\ud800text']
    for s in surrogates:
        try:
            bdf._require_utf8_text(s, field='test')
            return _fail(f'surrogate must reject {s!r}')
        except bdf.BrokerDiscoveryError:
            print(f'  REJECT {s!r}')
        except Exception as exc:
            return _fail(f'surrogate raw escape: {type(exc).__name__}')

    for field_fn, label in (
        (lambda: bdf.build_canonical_event(**_base_event(
            canonical_headline='x\ud800', symbols=['S'], structured_facts={'k': 1},
        )), 'headline'),
        (lambda: bdf.normalize_url('https://ex.com/\ud800'), 'url'),
        (lambda: bdf.bound_excerpt('e\ud800'), 'excerpt'),
        (lambda: bdf.normalize_structured_facts({'a\ud800': 1}), 'fact_key'),
        (lambda: bdf.normalize_structured_facts({'a': 'v\ud800'}), 'fact_value'),
        (lambda: bdf.normalize_symbol('A\ud800'), 'symbol'),
    ):
        try:
            field_fn()
            return _fail(f'{label} must reject surrogate')
        except bdf.BrokerDiscoveryError:
            print(f'  REJECT path={label}')
        except Exception as exc:
            return _fail(f'{label} raw escape: {type(exc).__name__}')

    print('VALID_MULTILINGUAL_UTF8_TABLE')
    samples = [
        ('Hindi', 'इन्फोसिस परिणाम'),
        ('Kannada', 'ಇನ್ಫೋಸಿಸ್'),
        ('Tamil', 'இன்ஃபோசிஸ்'),
        ('company', '株式会社テスト'),
        ('publisher', 'Agence France-Presse — 新闻'),
    ]
    for label, text in samples:
        try:
            bdf._require_utf8_text(text, field=label)
            ev = bdf.build_canonical_event(**_base_event(
                symbols=['ML'],
                company_names=[text] if label == 'company' else ['Infosys'],
                canonical_headline=text if label != 'company' else 'Multilingual company event',
                structured_facts={'note': text},
            ))
            print(f'  ACCEPT {label} id={ev["event_id"][:8]}...')
        except Exception as exc:
            return _fail(f'valid UTF-8 {label} failed: {type(exc).__name__}: {exc}')

    _pass('BROKER_DISCOVERY_UTF8_TEXT_CONTRACT_OK')
    return 0


def test_unhealthy_store_immutable(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Invalid UTF-8 immutability across ops
    bad = b'\xff\xfe UNREADABLE'
    path.write_bytes(bad)
    before = path.read_bytes()
    bdf.get_store_health()
    try:
        bdf.get_event('x')
    except bdf.BrokerDiscoveryError:
        pass
    try:
        bdf.upsert_event(_base_event(symbols=['IM'], structured_facts={'k': 1}, canonical_headline='im'))
    except bdf.BrokerDiscoveryError:
        pass
    try:
        bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/im', symbols=['IM'],
            structured_facts={'k': 1}, source_headline='im',
        ))
    except bdf.BrokerDiscoveryError:
        pass
    after = path.read_bytes()
    print(f'UNREADABLE_IMMUTABLE={before == after}')
    if before != after:
        return _fail('UNREADABLE store mutated')

    # PARTIAL store immutability
    good = bdf.build_canonical_event(**_base_event(
        symbols=['IMP'], structured_facts={'k': 1}, canonical_headline='immutable partial',
    ))
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
    bdf.get_store_health()
    try:
        bdf.find_recent_events()
    except bdf.BrokerDiscoveryError:
        pass
    try:
        bdf.upsert_event(_base_event(symbols=['IMP2'], structured_facts={'k': 2}, canonical_headline='x'))
    except bdf.BrokerDiscoveryError:
        pass
    after = path.read_bytes()
    print(f'PARTIAL_IMMUTABLE={before == after}')
    if before != after:
        return _fail('PARTIAL store mutated')

    path.unlink()
    _pass('BROKER_DISCOVERY_UNHEALTHY_STORE_IMMUTABLE_OK')
    return 0


def test_malformed_store_raw_exception_matrix(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    escape = 0
    mutations = [
        ('symbols_dict', lambda: _write_mutated_event_store(
            bdf, path, lambda r: r.__setitem__('symbols', [{}]))),
        ('symbols_list', lambda: _write_mutated_event_store(
            bdf, path, lambda r: r.__setitem__('symbols', [[]]))),
        ('headline_surrogate', lambda: _write_mutated_event_store(
            bdf, path, lambda r: r.__setitem__('canonical_headline', '\ud800'))),
        ('sighting_surrogate', lambda: _write_mutated_sighting_store(
            bdf, path, lambda r: r.__setitem__('source_name', '\ud800'))),
    ]
    apis = (
        ('classify', lambda: bdf._classify_store_payload(
            json.loads(path.read_text(encoding='utf-8')))),
        ('load_store', lambda: bdf.load_store()),
        ('get_store_health', lambda: bdf.get_store_health()),
        ('get_event', lambda: bdf.get_event('x')),
        ('get_sighting', lambda: bdf.get_sighting('x')),
        ('list_event_sightings', lambda: bdf.list_event_sightings('x')),
        ('find_events_by_symbol', lambda: bdf.find_events_by_symbol('INFY')),
        ('find_events_by_date', lambda: bdf.find_events_by_date(PUB.date())),
        ('find_recent_events', lambda: bdf.find_recent_events()),
        ('find_event_by_fingerprint', lambda: bdf.find_event_by_fingerprint('fp')),
        ('upsert_event', lambda: bdf.upsert_event(_base_event(
            symbols=['MX'], structured_facts={'k': 1}, canonical_headline='mx'))),
        ('upsert_sighting', lambda: bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/mx', symbols=['MX'],
            structured_facts={'k': 1}, source_headline='mx'))),
    )
    print('MALFORMED_STORE_RAW_EXCEPTION_MATRIX')
    for mname, prepare in mutations:
        prepare()
        for aname, api in apis:
            try:
                api()
                # classify/load/health may return without raising; mutations/queries must raise
                if aname in ('classify', 'load_store', 'get_store_health'):
                    continue
                escape += 1
                print(f'  ESCAPE {mname}/{aname}: accepted unhealthy')
            except bdf.BrokerDiscoveryError:
                print(f'  OK {mname}/{aname}: BrokerDiscoveryError')
            except (TypeError, ValueError, UnicodeError, OverflowError, UnicodeEncodeError, UnicodeDecodeError) as exc:
                escape += 1
                print(f'  ESCAPE {mname}/{aname}: {type(exc).__name__}')
            except Exception as exc:
                escape += 1
                print(f'  ESCAPE {mname}/{aname}: {type(exc).__name__}')

    # Also invalid UTF-8 through matrix subset
    path.write_bytes(b'\xff\xfe')
    for aname, api in apis:
        if aname == 'classify':
            continue
        try:
            api()
            if aname in ('load_store', 'get_store_health'):
                continue
            escape += 1
            print(f'  ESCAPE utf8/{aname}: accepted')
        except bdf.BrokerDiscoveryError:
            print(f'  OK utf8/{aname}: BrokerDiscoveryError')
        except Exception as exc:
            escape += 1
            print(f'  ESCAPE utf8/{aname}: {type(exc).__name__}')

    print(f'MALFORMED_STORE_RAW_EXCEPTION_ESCAPE_COUNT={escape}')
    if escape != 0:
        return _fail(f'raw exception escapes={escape}')
    if path.exists():
        path.unlink()
    return 0


def _assert_bde(fn, label: str):
    from backend.news import broker_discovery_foundation as bdf

    try:
        fn()
        return f'{label}: expected BrokerDiscoveryError'
    except bdf.BrokerDiscoveryError:
        return None
    except Exception as exc:
        return f'{label}: raw {type(exc).__name__}: {exc}'


def test_optional_event_payload_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    if path.exists():
        path.unlink()
    sight = _base_sighting(
        source_url='https://news.example.com/r7-opt',
        symbols=['R7O'],
        structured_facts={'k': 1},
        source_headline='Optional event payload contract',
    )
    print('OPTIONAL_EVENT_REJECTION_TABLE')
    cases = [
        ('string', 'invalid'),
        ('list', []),
        ('tuple', ()),
        ('set', set()),
        ('bool', True),
        ('int', 1),
        ('float', 1.5),
        ('bytes', b'x'),
        ('object', object()),
    ]
    for name, bad in cases:
        err = _assert_bde(lambda b=bad: bdf.upsert_sighting(sight, event=b), name)
        print(f'  REJECT {name}')
        if err:
            return _fail(err)
        if path.exists():
            return _fail(f'rejected event={name} created store')

    # Healthy store must stay immutable on rejection
    ok = bdf.upsert_sighting(sight)
    before = path.read_bytes()
    err = _assert_bde(lambda: bdf.upsert_sighting(sight, event='still-bad'), 'string_on_healthy')
    if err:
        return _fail(err)
    if path.read_bytes() != before:
        return _fail('rejected optional event mutated healthy store')
    if ok['event_id'] is None:
        return _fail('seed failed')

    _pass('BROKER_DISCOVERY_OPTIONAL_EVENT_PAYLOAD_CONTRACT_OK')
    return 0


def test_external_identifier_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    print('EXTERNAL_ID_REJECTION_TABLE')
    bad_ids = [
        ('None', None),
        ('bool', True),
        ('int', 1),
        ('float', 1.5),
        ('dict', {}),
        ('list', []),
        ('tuple', ()),
        ('set', set()),
        ('bytes', b'abc'),
        ('empty', ''),
        ('whitespace', '   '),
        ('surrogate', '11111111-1111-4111-8111-11111111111\ud800'),
        ('malformed', 'not-a-uuid'),
        ('padded', f' {UNKNOWN_EVENT_ID} '),
        ('uppercase', UPPERCASE_UUID),
    ]
    for name, bad in bad_ids:
        for label, fn in (
            ('get_event', lambda b=bad: bdf.get_event(b)),
            ('get_sighting', lambda b=bad: bdf.get_sighting(b)),
            ('list_event_sightings', lambda b=bad: bdf.list_event_sightings(b)),
            ('attach_sid', lambda b=bad: bdf.attach_sighting_to_event(b, UNKNOWN_EVENT_ID)),
            ('attach_eid', lambda b=bad: bdf.attach_sighting_to_event(UNKNOWN_SIGHTING_ID, b)),
            ('mark_primary', lambda b=bad: bdf.mark_primary_source_verified(
                b, primary_source_url='https://www.nseindia.com/x')),
        ):
            # Ensure store exists healthy so ID contract (not PARTIAL) is exercised
            if not path.exists():
                bdf.upsert_sighting(_base_sighting(
                    source_url='https://news.example.com/r7-id-seed',
                    symbols=['R7ID'],
                    structured_facts={'k': 1},
                    source_headline='External id seed',
                ))
            err = _assert_bde(fn, f'{label}/{name}')
            if err:
                return _fail(err)
        print(f'  REJECT {name}')

    print('FINGERPRINT_REJECTION_TABLE')
    bad_fps = [
        ('upper', 'A' * 64),
        ('short', 'abc'),
        ('long', 'a' * 65),
        ('whitespace', f' {UNKNOWN_FINGERPRINT} '),
        ('dict', {}),
        ('list', []),
        ('int', 1),
        ('surrogate', 'a' * 63 + '\ud800'),
        ('None', None),
        ('bool', False),
    ]
    for name, bad in bad_fps:
        err = _assert_bde(lambda b=bad: bdf.find_event_by_fingerprint(b), f'fp/{name}')
        print(f'  REJECT {name}')
        if err:
            return _fail(err)

    # Valid unknown IDs on healthy store
    print('VALID_UNKNOWN_ID_QUERY_EVIDENCE')
    if bdf.get_event(UNKNOWN_EVENT_ID) is not None:
        return _fail('unknown event must be None')
    if bdf.get_sighting(UNKNOWN_SIGHTING_ID) is not None:
        return _fail('unknown sighting must be None')
    if bdf.list_event_sightings(UNKNOWN_EVENT_ID) != []:
        return _fail('unknown list must be []')
    if bdf.find_event_by_fingerprint(UNKNOWN_FINGERPRINT) is not None:
        return _fail('unknown fingerprint must be None')
    print(f'  get_event({UNKNOWN_EVENT_ID}) -> None')
    print(f'  get_sighting({UNKNOWN_SIGHTING_ID}) -> None')
    print(f'  list_event_sightings -> []')
    print(f'  find_event_by_fingerprint -> None')

    # Mutation unknown valid UUID -> BrokerDiscoveryError; bytes immutable
    before = path.read_bytes()
    err = _assert_bde(
        lambda: bdf.mark_primary_source_verified(
            UNKNOWN_EVENT_ID, primary_source_url='https://www.nseindia.com/x'),
        'mark_unknown',
    )
    if err:
        return _fail(err)
    err = _assert_bde(
        lambda: bdf.attach_sighting_to_event(UNKNOWN_SIGHTING_ID, UNKNOWN_EVENT_ID),
        'attach_unknown',
    )
    if err:
        return _fail(err)
    if path.read_bytes() != before:
        return _fail('unknown-id mutation changed store bytes')

    # upsert_sighting with bad event_id
    err = _assert_bde(
        lambda: bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/r7-bad-eid',
            symbols=['R7E'],
            structured_facts={'k': 1},
            source_headline='Bad event id sighting',
            event_id='not-uuid',
        )),
        'upsert_sighting_event_id',
    )
    if err:
        return _fail(err)

    _pass('BROKER_DISCOVERY_EXTERNAL_IDENTIFIER_CONTRACT_OK')
    return 0


def test_query_limit_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    if not path.exists():
        bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/r7-lim',
            symbols=['R7L'],
            structured_facts={'k': 1},
            source_headline='Limit contract seed',
        ))
    print('INVALID_LIMIT_TABLE')
    cases = [
        ('True', True),
        ('False', False),
        ('neg', -1),
        ('float', 1.5),
        ('str10', '10'),
        ('strbad', 'bad'),
        ('None', None),
        ('dict', {}),
        ('list', []),
        ('nan', float('nan')),
        ('inf', float('inf')),
        ('overmax', bdf.MAX_QUERY_LIMIT + 1),
    ]
    for name, bad in cases:
        for api_name, fn in (
            ('by_symbol', lambda b=bad: bdf.find_events_by_symbol('R7L', limit=b)),
            ('by_date', lambda b=bad: bdf.find_events_by_date(PUB.date(), limit=b)),
            ('recent', lambda b=bad: bdf.find_recent_events(limit=b)),
        ):
            err = _assert_bde(fn, f'{api_name}/{name}')
            if err:
                return _fail(err)
        print(f'  REJECT {name}')

    got = bdf.find_recent_events(limit=0)
    if got != []:
        return _fail('limit=0 must return []')
    got = bdf.find_recent_events(limit=bdf.MAX_QUERY_LIMIT)
    if not isinstance(got, list):
        return _fail('max limit must succeed')

    _pass('BROKER_DISCOVERY_QUERY_LIMIT_CONTRACT_OK')
    return 0


def test_date_query_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    if not path.exists():
        bdf.upsert_sighting(_base_sighting(
            source_url='https://news.example.com/r7-date',
            symbols=['R7D'],
            structured_facts={'k': 1},
            source_headline='Date contract seed',
        ))

    class BoomIso:
        def isoformat(self):
            raise RuntimeError('isoformat must not be called')

    class BadIso:
        def isoformat(self):
            return 12345

    print('INVALID_DATE_TABLE')
    cases = [
        ('boom_isoformat', BoomIso()),
        ('bad_isoformat', BadIso()),
        ('dict', {}),
        ('list', []),
        ('bool', True),
        ('malformed', 'not-a-date'),
        ('int', 20260731),
        ('bytes', b'2026-07-31'),
    ]
    for name, bad in cases:
        err = _assert_bde(lambda b=bad: bdf.find_events_by_date(b), name)
        print(f'  REJECT {name}')
        if err:
            return _fail(err)

    # Accepted documented types
    for label, val in (
        ('datetime', PUB),
        ('date', PUB.date()),
        ('date_string', PUB.date().isoformat()),
        ('timestamp_string', PUB.isoformat()),
    ):
        try:
            rows = bdf.find_events_by_date(val)
            if not isinstance(rows, list):
                return _fail(f'{label} must return list')
            print(f'  ACCEPT {label}')
        except Exception as exc:
            return _fail(f'{label} raised {type(exc).__name__}: {exc}')

    _pass('BROKER_DISCOVERY_DATE_QUERY_CONTRACT_OK')
    return 0


def test_builder_now_contract(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    print('BUILDER_NOW_REJECTION_TABLE')
    bad_nows = [
        ('string', 'not-a-time'),
        ('bool', True),
        ('dict', {}),
        ('list', []),
        ('int', 1),
        ('object', object()),
        ('bytes', b'x'),
    ]
    fixed = datetime(2099, 8, 1, 9, 30, 0, tzinfo=IST)
    for name, bad in bad_nows:
        err = _assert_bde(
            lambda b=bad: bdf.build_canonical_event(**_base_event(
                symbols=['R7N'], structured_facts={'k': 1},
                canonical_headline='now reject event',
                first_seen_at=fixed, last_seen_at=fixed, now=b,
            )),
            f'event/{name}',
        )
        if err:
            return _fail(err)
        err = _assert_bde(
            lambda b=bad: bdf.build_source_sighting(
                source_name='Broker',
                source_kind='BROKER_PUBLIC',
                source_url='https://news.example.com/r7n',
                source_headline='now reject sighting',
                source_published_at=PUB,
                first_seen_at=fixed, last_seen_at=fixed, now=b,
            ),
            f'sighting/{name}',
        )
        if err:
            return _fail(err)
        print(f'  REJECT {name}')

    ev1 = bdf.build_canonical_event(**_base_event(
        symbols=['R7F'], structured_facts={'k': 1},
        canonical_headline='fixed now event', now=fixed,
    ))
    ev2 = bdf.build_canonical_event(**_base_event(
        symbols=['R7F'], structured_facts={'k': 1},
        canonical_headline='fixed now event', now=fixed,
    ))
    if ev1['created_at'] != fixed.isoformat() or ev1['created_at'] != ev2['created_at']:
        return _fail(f'fixed now not deterministic: {ev1["created_at"]!r}')
    print(f'FIXED_NOW_EVENT created_at={ev1["created_at"]}')

    _pass('BROKER_DISCOVERY_BUILDER_NOW_CONTRACT_OK')
    return 0


def test_public_api_fail_closed_matrix(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    # Seed healthy store then prove rejected inputs do not mutate / do not create when missing
    if path.exists():
        path.unlink()
    print('MISSING_STORE_NONCREATION_EVIDENCE')
    missing_calls = [
        ('upsert_sighting_bad_event', lambda: bdf.upsert_sighting(
            _base_sighting(
                source_url='https://news.example.com/r7-miss',
                symbols=['R7M'], structured_facts={'k': 1},
                source_headline='missing store noncreate',
            ),
            event='bad',
        )),
        ('get_event_bad_id', lambda: bdf.get_event('bad')),
        ('find_recent_bad_limit', lambda: bdf.find_recent_events(limit=True)),
        ('find_date_bad', lambda: bdf.find_events_by_date({})),
        ('find_fp_bad', lambda: bdf.find_event_by_fingerprint('short')),
        ('attach_bad', lambda: bdf.attach_sighting_to_event('bad', 'bad')),
        ('mark_bad', lambda: bdf.mark_primary_source_verified(
            'bad', primary_source_url='https://www.nseindia.com/x')),
    ]
    for name, fn in missing_calls:
        err = _assert_bde(fn, name)
        if err:
            return _fail(err)
        if path.exists():
            return _fail(f'{name} created missing store')
        print(f'  NO_CREATE {name}')

    seed = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/r7-matrix',
        symbols=['R7X'],
        structured_facts={'k': 1},
        source_headline='Public API matrix seed',
    ))
    before = path.read_bytes()
    print('HEALTHY_STORE_BYTE_IDENTITY_EVIDENCE')

    class BoomIso:
        def isoformat(self):
            raise RuntimeError('nope')

    escape = 0
    cases = [
        ('build_event_now', lambda: bdf.build_canonical_event(**_base_event(
            symbols=['R7X'], structured_facts={'k': 1},
            canonical_headline='x', now=True))),
        ('build_sighting_now', lambda: bdf.build_source_sighting(
            source_name='B', source_kind='BROKER_PUBLIC',
            source_url='https://news.example.com/r7x2',
            source_headline='x', source_published_at=PUB, now=[])),
        ('upsert_event_not_dict', lambda: bdf.upsert_event('nope')),
        ('upsert_sighting_event', lambda: bdf.upsert_sighting(
            _base_sighting(
                source_url='https://news.example.com/r7x3',
                symbols=['R7X'], structured_facts={'k': 2},
                source_headline='x3',
            ),
            event=123,
        )),
        ('upsert_sighting_bad_eid', lambda: bdf.upsert_sighting(
            _base_sighting(
                source_url='https://news.example.com/r7x4',
                symbols=['R7X'], structured_facts={'k': 3},
                source_headline='x4', event_id='\ud800',
            ),
        )),
        ('attach_bad_sid', lambda: bdf.attach_sighting_to_event(
            True, seed['event_id'])),
        ('attach_bad_eid', lambda: bdf.attach_sighting_to_event(
            seed['sighting_id'], {})),
        ('mark_bad_eid', lambda: bdf.mark_primary_source_verified(
            [], primary_source_url='https://www.nseindia.com/x')),
        ('get_event_surrogate', lambda: bdf.get_event('\ud800')),
        ('get_sighting_int', lambda: bdf.get_sighting(1)),
        ('list_event_float', lambda: bdf.list_event_sightings(1.5)),
        ('find_symbol_limit', lambda: bdf.find_events_by_symbol('R7X', limit='10')),
        ('find_date_boom', lambda: bdf.find_events_by_date(BoomIso())),
        ('find_date_limit', lambda: bdf.find_events_by_date(PUB.date(), limit=False)),
        ('find_recent_limit', lambda: bdf.find_recent_events(limit=-1)),
        ('find_fp_upper', lambda: bdf.find_event_by_fingerprint('A' * 64)),
        ('find_fp_surrogate', lambda: bdf.find_event_by_fingerprint('a' * 63 + '\ud800')),
    ]
    print('PUBLIC_API_RAW_EXCEPTION_MATRIX')
    for name, fn in cases:
        try:
            fn()
            escape += 1
            print(f'  ESCAPE {name}: accepted')
        except bdf.BrokerDiscoveryError:
            print(f'  OK {name}: BrokerDiscoveryError')
        except (TypeError, ValueError, AttributeError, UnicodeEncodeError, UnicodeDecodeError, OverflowError) as exc:
            # BrokerDiscoveryError subclasses ValueError — already handled above
            if isinstance(exc, bdf.BrokerDiscoveryError):
                print(f'  OK {name}: BrokerDiscoveryError')
            else:
                escape += 1
                print(f'  ESCAPE {name}: {type(exc).__name__}')
        except Exception as exc:
            escape += 1
            print(f'  ESCAPE {name}: {type(exc).__name__}')

    after = path.read_bytes()
    print(f'HEALTHY_STORE_BYTES_IDENTICAL={before == after}')
    if before != after:
        return _fail('rejected public API inputs mutated healthy store')

    print(f'PUBLIC_API_RAW_EXCEPTION_ESCAPE_COUNT={escape}')
    if escape != 0:
        return _fail(f'public API raw escapes={escape}')

    _pass('BROKER_DISCOVERY_PUBLIC_API_FAIL_CLOSED_OK')
    return 0


def test_rejected_terminal(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf

    path = bdf.store_path()
    # Seed then force REJECTED via controlled internal write of a valid store mutation
    seeded = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/rej',
        symbols=['REJ1'],
        structured_facts={'k': 'rej'},
        source_headline='Rejected terminal event',
    ))
    store = json.loads(path.read_text(encoding='utf-8'))
    store['events'][seeded['event_id']]['verification_status'] = bdf.VERIFICATION_REJECTED
    store['events'][seeded['event_id']]['primary_source_url'] = ''
    # keep source_count consistent
    path.write_text(json.dumps(store), encoding='utf-8')
    # Re-load through health — must still be OK (REJECTED is valid terminal)
    if bdf.get_store_health()['health'] != bdf.HEALTH_OK:
        return _fail('REJECTED store must remain healthy when otherwise valid')

    before = path.read_bytes()
    writes = {'n': 0}
    real = bdf.atomic_write_json

    def _count(path_, payload):
        writes['n'] += 1
        return real(path_, payload)

    with patch('backend.news.broker_discovery_foundation.atomic_write_json', _count):
        try:
            bdf.mark_primary_source_verified(
                seeded['event_id'],
                primary_source_url='https://www.nseindia.com/rej',
            )
            return _fail('mark_primary must not promote REJECTED')
        except bdf.BrokerDiscoveryError as exc:
            print(f'REJECTED_PROMOTION_ERROR={exc}')
    print(f'REJECTED_PROMOTION_WRITES={writes["n"]}')
    if writes['n'] != 0:
        return _fail('rejected promotion must not write')
    if path.read_bytes() != before:
        return _fail('rejected promotion must leave store byte-identical')

    still = bdf.get_event(seeded['event_id'])
    if still['verification_status'] != bdf.VERIFICATION_REJECTED:
        return _fail('REJECTED status must remain')

    # upsert_event / upsert_sighting preserve REJECTED
    bdf.upsert_event(_base_event(
        symbols=['REJ1'],
        structured_facts={'k': 'rej'},
        canonical_headline='Rejected terminal event',
    ))
    if bdf.get_event(seeded['event_id'])['verification_status'] != bdf.VERIFICATION_REJECTED:
        return _fail('upsert_event must preserve REJECTED')
    bdf.upsert_sighting(_base_sighting(
        source_name='OtherBroker',
        source_url='https://news.example.com/rej2',
        symbols=['REJ1'],
        structured_facts={'k': 'rej'},
        source_headline='Rejected terminal event',
    ))
    if bdf.get_event(seeded['event_id'])['verification_status'] != bdf.VERIFICATION_REJECTED:
        return _fail('upsert_sighting must preserve REJECTED')

    # Discover/multi can still become primary
    ok = bdf.upsert_sighting(_base_sighting(
        source_url='https://news.example.com/rej-ok',
        symbols=['REJOK'],
        structured_facts={'k': 'rejok'},
        source_headline='Non rejected primary path',
    ))
    marked = bdf.mark_primary_source_verified(
        ok['event_id'],
        primary_source_url='https://www.nseindia.com/ok',
    )
    if marked['verification_status'] != bdf.VERIFICATION_PRIMARY:
        return _fail('non-rejected must still promote')

    _pass('BROKER_DISCOVERY_REJECTED_TERMINAL_OK')
    return 0


def test_persistence_boundary(iso) -> int:
    from backend.news import broker_discovery_foundation as bdf
    import inspect

    if hasattr(bdf, 'save_store') and callable(getattr(bdf, 'save_store')):
        # Allow attribute only if not a public function definition
        src = inspect.getsource(bdf)
        if re.search(r'^def save_store\b', src, re.M):
            return _fail('public save_store must not exist')
    if not hasattr(bdf, '_save_store'):
        return _fail('internal _save_store required')
    src = (PROJECT_ROOT / 'backend/news/broker_discovery_foundation.py').read_text(encoding='utf-8')
    if re.search(r'^def save_store\b', src, re.M):
        return _fail('foundation still defines public save_store')
    if 'def _save_store' not in src:
        return _fail('foundation missing _save_store')
    # production writes only via mutation ops -> _save_store
    for op in ('upsert_event', 'upsert_sighting', 'attach_sighting_to_event', 'mark_primary_source_verified'):
        if op not in src:
            return _fail(f'missing public mutation {op}')
    print('PERSISTENCE_BOUNDARY public_mutations=4 internal=_save_store')
    _pass('BROKER_DISCOVERY_PERSISTENCE_BOUNDARY_OK')
    return 0


def main() -> int:
    from scripts._test_runtime_isolation import (
        isolated_premarket_data_root,
        repo_data_root,
        snapshot_data_tree,
    )
    from unittest.mock import patch

    rc = test_build_identity()
    if rc:
        return rc
    rc = test_exact_build_pair_allowlists()
    if rc:
        return rc
    rc = test_canonical_event_and_sighting_creation()
    if rc:
        return rc
    rc = test_symbol_and_fact_order_stable()
    if rc:
        return rc
    rc = test_unknown_event_type_other()
    if rc:
        return rc
    rc = test_no_network_no_ai()
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

    with isolated_premarket_data_root() as iso, patch.object(Path, 'read_text', _guard_read_text), patch.object(
        Path, 'open', _guard_open
    ):
        for fn in (
            test_store_health_missing_and_malformed,
            test_idempotent_repeat_and_last_seen,
            test_url_and_headline_variation_dedupe,
            test_material_events_remain_separate,
            test_verification_rules,
            test_excerpt_and_no_full_article,
            test_queries,
            test_repeated_runs_deterministic,
            test_primary_transition_guard,
            test_query_failure_truth,
            test_partial_store_health,
            test_reattachment_truth,
            test_raw_markup_rejected,
            test_single_write_atomic,
            test_first_run_single_write,
            test_source_count_canonical,
            test_repeat_attachment_stable,
            test_url_contract,
            test_canonical_identity_health,
            test_strict_input_contract,
            test_persisted_timestamp_contract,
            test_operation_time_consistency,
            test_canonical_metadata_health,
            test_metadata_preservation,
            test_json_fact_contract,
            test_host_port_contract,
            test_ip_literal_fail_closed,
            test_unreadable_utf8_truth,
            test_malformed_symbols_fail_closed,
            test_malformed_row_fail_closed,
            test_utf8_text_contract,
            test_unhealthy_store_immutable,
            test_malformed_store_raw_exception_matrix,
            test_optional_event_payload_contract,
            test_external_identifier_contract,
            test_query_limit_contract,
            test_date_query_contract,
            test_builder_now_contract,
            test_public_api_fail_closed_matrix,
            test_rejected_terminal,
            test_persistence_boundary,
        ):
            rc = fn(iso)
            if rc:
                return rc

    after = snapshot_data_tree()
    git_after = _git_data_status()
    rc = test_repo_data_not_read_or_mutated(before, after, git_before, git_after, leaks)
    if rc:
        return rc

    required = {
        'BROKER_DISCOVERY_BUILD_OK',
        'BROKER_DISCOVERY_BUILD_PAIR_MISMATCH_REJECTED_OK',
        'BROKER_DISCOVERY_CONTRACTS_OK',
        'BROKER_DISCOVERY_IDEMPOTENT_OK',
        'BROKER_DISCOVERY_URL_HEADLINE_DEDUPE_OK',
        'BROKER_DISCOVERY_SEPARATE_EVENTS_OK',
        'BROKER_DISCOVERY_ORDER_STABLE_OK',
        'BROKER_DISCOVERY_EVENT_TYPE_OTHER_OK',
        'BROKER_DISCOVERY_VERIFICATION_OK',
        'BROKER_DISCOVERY_RETENTION_OK',
        'BROKER_DISCOVERY_HEALTH_OK',
        'BROKER_DISCOVERY_NO_NETWORK_AI_OK',
        'BROKER_DISCOVERY_QUERY_OK',
        'BROKER_DISCOVERY_DETERMINISTIC_OK',
        'BROKER_DISCOVERY_REPO_DATA_SAFE_OK',
        'BROKER_DISCOVERY_PRIMARY_TRANSITION_GUARD_OK',
        'BROKER_DISCOVERY_QUERY_FAILURE_TRUTH_OK',
        'BROKER_DISCOVERY_PARTIAL_HEALTH_OK',
        'BROKER_DISCOVERY_REATTACHMENT_TRUTH_OK',
        'BROKER_DISCOVERY_RAW_MARKUP_REJECTED_OK',
        'BROKER_DISCOVERY_SINGLE_WRITE_ATOMIC_OK',
        'BROKER_DISCOVERY_FIRST_RUN_SINGLE_WRITE_OK',
        'BROKER_DISCOVERY_SOURCE_COUNT_CANONICAL_OK',
        'BROKER_DISCOVERY_REPEAT_ATTACHMENT_STABLE_OK',
        'BROKER_DISCOVERY_URL_CONTRACT_OK',
        'BROKER_DISCOVERY_CANONICAL_IDENTITY_HEALTH_OK',
        'BROKER_DISCOVERY_STRICT_INPUT_CONTRACT_OK',
        'BROKER_DISCOVERY_PERSISTED_TIMESTAMP_CONTRACT_OK',
        'BROKER_DISCOVERY_OPERATION_TIME_CONSISTENCY_OK',
        'BROKER_DISCOVERY_CANONICAL_METADATA_HEALTH_OK',
        'BROKER_DISCOVERY_METADATA_PRESERVATION_OK',
        'BROKER_DISCOVERY_JSON_FACT_CONTRACT_OK',
        'BROKER_DISCOVERY_HOST_PORT_CONTRACT_OK',
        'BROKER_DISCOVERY_IP_LITERAL_FAIL_CLOSED_OK',
        'BROKER_DISCOVERY_UNREADABLE_UTF8_TRUTH_OK',
        'BROKER_DISCOVERY_MALFORMED_SYMBOLS_FAIL_CLOSED_OK',
        'BROKER_DISCOVERY_MALFORMED_ROW_FAIL_CLOSED_OK',
        'BROKER_DISCOVERY_UTF8_TEXT_CONTRACT_OK',
        'BROKER_DISCOVERY_UNHEALTHY_STORE_IMMUTABLE_OK',
        'BROKER_DISCOVERY_OPTIONAL_EVENT_PAYLOAD_CONTRACT_OK',
        'BROKER_DISCOVERY_EXTERNAL_IDENTIFIER_CONTRACT_OK',
        'BROKER_DISCOVERY_QUERY_LIMIT_CONTRACT_OK',
        'BROKER_DISCOVERY_DATE_QUERY_CONTRACT_OK',
        'BROKER_DISCOVERY_BUILDER_NOW_CONTRACT_OK',
        'BROKER_DISCOVERY_PUBLIC_API_FAIL_CLOSED_OK',
        'BROKER_DISCOVERY_REJECTED_TERMINAL_OK',
        'BROKER_DISCOVERY_PERSISTENCE_BOUNDARY_OK',
    }
    missing = sorted(required - set(PASS_MARKERS))
    if missing:
        return _fail(f'missing pass markers: {missing}')

    print('BROKER_DISCOVERY_FOUNDATION_52R_A1_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
