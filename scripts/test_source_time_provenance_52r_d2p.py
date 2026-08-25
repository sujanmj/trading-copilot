#!/usr/bin/env python3
"""AstraEdge 52R-D2P — source timestamp provenance focused tests (isolated)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
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
PUB2 = datetime(2099, 7, 31, 16, 45, 0, tzinfo=IST)
PASS_MARKERS: list[str] = []

PROTECTED = (
    PROJECT_ROOT / 'backend' / 'news' / 'broker_discovery_foundation.py',
    PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_store.py',
    PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_classifier.py',
    PROJECT_ROOT / 'backend' / 'news' / 'primary_source_verifier.py',
    PROJECT_ROOT / 'backend' / 'news' / 'automatic_primary_verification.py',
    PROJECT_ROOT / 'backend' / 'news' / 'news_pipeline_reliability.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'market_freshness_guard.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'opening_session_freshness.py',
    PROJECT_ROOT / 'backend' / 'orchestration' / 'alert_freshness_gate.py',
    PROJECT_ROOT / 'backend' / 'runtime' / 'snapshot_freshness_monitor.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py',
)
MODULE_PATH = PROJECT_ROOT / 'backend' / 'news' / 'source_time_provenance.py'
ADAPTER_PATH = PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py'
REGISTRY_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py'

LOCK_HOLD_SCRIPT = r'''
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path('.').resolve()))
from backend.news.source_time_provenance import _ProvenanceLock, provenance_lock_path

lock = _ProvenanceLock(provenance_lock_path())
ok = lock.try_acquire()
print('LOCK_HOLD ' + ('1' if ok else '0'), flush=True)
if not ok:
    raise SystemExit(4)
time.sleep(8)
lock.release()
'''


def _fail(msg: str) -> int:
    print(f'SOURCE_TIME_PROVENANCE_52R_D2P_FAIL: {msg}', file=sys.stderr)
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


def _iso(dt: datetime) -> str:
    from backend.news.broker_discovery_foundation import validate_persisted_timestamp

    return validate_persisted_timestamp(dt.astimezone(IST).isoformat(), field='ts')


@contextmanager
def _isolated():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sidecar = root / 'news_source_time_provenance.json'
        lock = root / 'news_source_time_provenance.lock'
        rss_lock = root / 'rss_discovery_ingest.lock'

        def _temp_data_path(relative: str) -> Path:
            rel = str(relative or '').replace('\\', '/').lstrip('/')
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            return path

        with patch.dict(
            os.environ,
            {
                'NEWS_SOURCE_TIME_PROVENANCE_PATH': str(sidecar),
                'NEWS_SOURCE_TIME_PROVENANCE_LOCK_PATH': str(lock),
                'RSS_DISCOVERY_LOCK_PATH': str(rss_lock),
            },
            clear=False,
        ), patch(
            'backend.news.broker_discovery_foundation.get_data_path',
            side_effect=_temp_data_path,
        ), patch(
            'backend.news.rss_discovery_adapter.get_data_path',
            side_effect=_temp_data_path,
        ), patch(
            'backend.collectors.news_provider_registry.get_data_path',
            side_effect=_temp_data_path,
        ):
            yield {
                'root': root,
                'sidecar': sidecar,
                'lock': lock,
                'store': root / 'broker_news_discovery_store.json',
            }


def _article(**extra):
    row = {
        'provider_id': 'et_markets',
        'source_id': 'et_markets',
        'source_name': 'ET Markets',
        'url': 'https://economictimes.example.com/d2p-infosys',
        'title': 'Infosys reports other event',
        'published_at': _iso(PUB),
        'source_time_basis': 'PUBLISHED_PARSED',
        'description': 'Bounded excerpt for Infosys.',
        'symbols': ['INFY'],
    }
    row.update(extra)
    return row


def _sid_from_article(article: dict) -> tuple[str, str]:
    from backend.news.broker_discovery_foundation import build_source_sighting
    from backend.news.rss_discovery_adapter import article_to_sighting_payload

    payload = article_to_sighting_payload(article)
    if payload is None:
        raise AssertionError('article ineligible')
    built = build_source_sighting(
        source_name=payload['source_name'],
        source_kind=payload['source_kind'],
        source_url=payload['source_url'],
        source_headline=payload['source_headline'],
        source_published_at=payload['source_published_at'],
        original_publisher=payload.get('original_publisher'),
        bounded_excerpt=payload.get('bounded_excerpt'),
    )
    return str(built['sighting_id']), str(built['source_published_at'])


def test_build() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) != ('52R-D2P', 'AstraEdge 52R-D2P'):
        return _fail(f'expected 52R-D2P pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}')
    _pass('T0_BUILD_PAIR_OK')
    return 0


def test_t1_t2_health(ctx: dict) -> int:
    from backend.news.source_time_provenance import (
        HEALTH_MISSING,
        HEALTH_OK,
        get_source_time_provenance_health,
        load_source_time_provenance,
        lookup_source_time_provenance,
        record_source_time_provenance,
    )

    payload, health = load_source_time_provenance()
    if payload is not None or health != HEALTH_MISSING:
        return _fail(f'T1 expected MISSING, got {health}')
    if ctx['sidecar'].exists():
        return _fail('T1 must not fabricate sidecar on read')
    fake = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    looked = lookup_source_time_provenance(fake)
    if looked.get('provenance') != 'SOURCE_TIME_AMBIGUOUS':
        return _fail('T1 missing sidecar must be AMBIGUOUS')
    _pass('T1')

    sid, value = _sid_from_article(_article())
    rec = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=value,
        source_time_basis='PUBLISHED_PARSED',
    )
    if rec.get('status') != 'INSERTED':
        return _fail(f'T2 insert failed {rec}')
    ctx['sidecar'].write_text(
        json.dumps(
            {
                'schema_version': '52R-D2P',
                'updated_at': value,
                'entries': {},
            },
            indent=2,
            sort_keys=True,
        )
        + '\n',
        encoding='utf-8',
    )
    payload, health = load_source_time_provenance()
    info = get_source_time_provenance_health()
    if health != HEALTH_OK or info.get('health') != HEALTH_OK:
        return _fail(f'T2 empty valid sidecar not OK: {health}')
    if payload.get('entries') != {}:
        return _fail('T2 entries not empty')
    _pass('T2')
    return 0


def test_t3_t13_schema(ctx: dict) -> int:
    from backend.news.source_time_provenance import (
        HEALTH_MALFORMED,
        HEALTH_UNREADABLE,
        load_source_time_provenance,
        record_source_time_provenance,
    )

    sid, value = _sid_from_article(_article(url='https://economictimes.example.com/schema'))
    ctx['sidecar'].write_text('{', encoding='utf-8')
    _payload, health = load_source_time_provenance()
    if health not in (HEALTH_UNREADABLE, HEALTH_MALFORMED):
        return _fail(f'T3 expected unreadable/malformed got {health}')
    _pass('T3')
    cases = [
        ('T4', json.dumps({'schema_version': '52R-D1', 'updated_at': value, 'entries': {}}), HEALTH_MALFORMED),
        ('T5', json.dumps({'schema_version': '52R-D2P', 'entries': {}}), HEALTH_MALFORMED),
        (
            'T6',
            json.dumps({'schema_version': '52R-D2P', 'updated_at': value, 'entries': {}, 'extra': 1}),
            HEALTH_MALFORMED,
        ),
    ]
    for label, blob, expected in cases:
        ctx['sidecar'].write_text(blob, encoding='utf-8')
        _payload, health = load_source_time_provenance()
        if expected == HEALTH_UNREADABLE:
            if health not in (HEALTH_UNREADABLE, HEALTH_MALFORMED):
                return _fail(f'{label} expected unreadable/malformed got {health}')
        elif health != expected:
            return _fail(f'{label} expected {expected} got {health}')
        _pass(label if label.startswith('T') else label)

    ctx['sidecar'].unlink(missing_ok=True)
    bad = record_source_time_provenance(
        sighting_id='not-a-uuid',
        source_time_value=value,
        source_time_basis='PUBLISHED_PARSED',
    )
    if bad.get('status') != 'FAILED':
        return _fail(f'T7 bad UUID wrote {bad}')
    _pass('T7')

    rec = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=value,
        source_time_basis='PUBLISHED_PARSED',
    )
    if rec.get('status') != 'INSERTED':
        return _fail(f'T8 setup insert failed {rec}')
    data = json.loads(ctx['sidecar'].read_text(encoding='utf-8'))
    entry = next(iter(data['entries'].values()))
    wrong_key = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    data['entries'] = {wrong_key: entry}
    ctx['sidecar'].write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    _payload, health = load_source_time_provenance()
    if health != HEALTH_MALFORMED:
        return _fail(f'T8 key mismatch health {health}')
    _pass('T8')

    ctx['sidecar'].unlink(missing_ok=True)
    for label, kwargs in (
        ('T9', {'source_time_provenance': 'SOURCE_TIME_VERIFIED'}),
        ('T10', {'source_time_basis': 'PUBLICATION'}),
        ('T11', {'timezone_assumption': 'IST'}),
        ('T12', {'source_time_value': '2099-07-31T10:15:00'}),
        ('T13', {'source_time_value': value.replace('+05:30', 'Z') if '+05:30' in value else '2099-07-31T04:45:00+00:00'}),
    ):
        rec = record_source_time_provenance(
            sighting_id=sid,
            source_time_value=kwargs.get('source_time_value', value),
            source_time_basis=kwargs.get('source_time_basis', 'PUBLISHED_PARSED'),
            timezone_assumption=kwargs.get('timezone_assumption', 'UTC'),
            source_time_provenance=kwargs.get('source_time_provenance', 'SOURCE_TIME_PRESENT'),
        )
        if rec.get('status') != 'FAILED':
            return _fail(f'{label} should FAIL, got {rec}')
        if ctx['sidecar'].exists():
            return _fail(f'{label} mutated sidecar')
        _pass(label)
    return 0


def test_t14_t22_write_once(ctx: dict) -> int:
    from backend.news.source_time_provenance import (
        load_source_time_provenance,
        lookup_source_time_provenance,
        record_source_time_provenance,
    )

    ctx['sidecar'].unlink(missing_ok=True)
    art = _article(url='https://economictimes.example.com/write-once')
    sid, value = _sid_from_article(art)
    first = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=value,
        source_time_basis='PUBLISHED_PARSED',
    )
    if first.get('status') != 'INSERTED':
        return _fail(f'T14 {first}')
    looked = lookup_source_time_provenance(sid)
    if looked.get('entry', {}).get('source_time_value') != value:
        return _fail('T14 binding mismatch')
    if looked.get('entry', {}).get('source_time_basis') != 'PUBLISHED_PARSED':
        return _fail('T14 basis')
    reloaded, health = load_source_time_provenance()
    if health != 'OK' or not reloaded or sid not in reloaded.get('entries', {}):
        return _fail('T15 reload after write failed')
    _pass('T14')
    _pass('T15')

    recorded = json.loads(ctx['sidecar'].read_text(encoding='utf-8'))
    entry_before = recorded['entries'][sid]
    bytes_before = ctx['sidecar'].read_bytes()
    second = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=value,
        source_time_basis='PUBLISHED_PARSED',
    )
    if second.get('status') != 'IDEMPOTENT':
        return _fail(f'T16 {second}')
    if ctx['sidecar'].read_bytes() != bytes_before:
        return _fail('T17 sidecar bytes changed on idempotent write')
    after = json.loads(ctx['sidecar'].read_text(encoding='utf-8'))
    if after['entries'][sid]['recorded_at'] != entry_before['recorded_at']:
        return _fail('T16 recorded_at mutated')
    if after['updated_at'] != recorded['updated_at']:
        return _fail('T17 top-level updated_at mutated')
    _pass('T16')
    _pass('T17')

    conflict_basis = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=value,
        source_time_basis='UPDATED_PARSED',
    )
    if conflict_basis.get('status') != 'CONFLICT':
        return _fail(f'T18 {conflict_basis}')
    _pass('T18')

    other = _iso(PUB2)
    conflict_ts = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=other,
        source_time_basis='PUBLISHED_PARSED',
    )
    if conflict_ts.get('status') != 'CONFLICT':
        return _fail(f'T19 {conflict_ts}')
    if ctx['sidecar'].read_bytes() != bytes_before:
        return _fail('T20 conflict mutated sidecar')
    _pass('T19')
    _pass('T20')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONPATH'] = str(PROJECT_ROOT) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.Popen(
        [sys.executable, '-u', '-c', LOCK_HOLD_SCRIPT],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    held = False
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        held = 'LOCK_HOLD 1' in (line or '')
        if not held:
            return _fail(f'T21 lock child did not acquire: {line!r}')
        before = ctx['sidecar'].read_bytes()
        contended = record_source_time_provenance(
            sighting_id=sid,
            source_time_value=value,
            source_time_basis='PUBLISHED_PARSED',
        )
        if contended.get('status') != 'LOCK_CONTENDED':
            return _fail(f'T21 expected LOCK_CONTENDED got {contended}')
        if ctx['sidecar'].read_bytes() != before:
            return _fail('T21 lock contention mutated sidecar')
        _pass('T21')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()

    ctx['sidecar'].write_text('{not-json', encoding='utf-8')
    before = ctx['sidecar'].read_bytes()
    unhealthy = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=value,
        source_time_basis='PUBLISHED_PARSED',
    )
    if unhealthy.get('status') != 'STORE_UNHEALTHY':
        return _fail(f'T22 {unhealthy}')
    if ctx['sidecar'].read_bytes() != before:
        return _fail('T22 corrupt store mutated')
    _pass('T22')
    ctx['sidecar'].unlink(missing_ok=True)
    return 0


def test_t23_t27_registry(ctx: dict) -> int:
    from backend.collectors.news_provider_registry import fetch_provider_rss
    from backend.news.rss_discovery_adapter import ingest_registry_articles
    from backend.news.source_time_provenance import lookup_source_time_provenance

    provider = {
        'source_id': 'et_markets',
        'source_name': 'ET Markets',
        'source_type': 'rss',
        'enabled': True,
        'verification_tier': 3,
        'feeds': [('https://example.invalid/rss', 'markets')],
    }

    class _Resp:
        status_code = 200
        content = b'<rss></rss>'

    class _Sess:
        def get(self, *args, **kwargs):
            return _Resp()

    missing = SimpleNamespace(entries=[
        SimpleNamespace(title='Infosys missing date', link='https://economictimes.example.com/miss', summary='x', published_parsed=None, updated_parsed=None),
    ])
    for entry in missing.entries:
        entry.get = lambda k, d=None, e=entry: getattr(e, k, d)

    with patch('backend.collectors.news_provider_registry.feedparser.parse', return_value=missing):
        articles, _status = fetch_provider_rss(provider, session=_Sess())
    if not articles:
        return _fail('T23 expected feed-display article without source time')
    row = articles[0]
    if 'published_at' in row or 'published' in row:
        return _fail('T23 now-fallback still present on published_at/published')
    if 'ingested_at' not in row:
        return _fail('T23 missing ingested_at display clock')
    if row.get('source_time_basis'):
        return _fail('T23 must not invent basis')
    stats = ingest_registry_articles(articles)
    if int(stats.get('skipped_missing_timestamp') or 0) < 1:
        return _fail(f'T23 A2 must skip missing timestamp, got {stats}')
    if ctx['store'].exists():
        return _fail('T23 created A1 store')
    _pass('T23')

    malformed = SimpleNamespace(entries=[
        SimpleNamespace(title='Infosys bad date', link='https://economictimes.example.com/bad', summary='x', published_parsed=('x',), updated_parsed=('y',)),
    ])
    for entry in malformed.entries:
        entry.get = lambda k, d=None, e=entry: getattr(e, k, d)
    with patch('backend.collectors.news_provider_registry.feedparser.parse', return_value=malformed):
        articles, _status = fetch_provider_rss(provider, session=_Sess())
    if any(a.get('published_at') or a.get('source_time_basis') for a in articles):
        return _fail('T24 malformed became provenance')
    ingest_registry_articles(articles)
    _pass('T24')

    nse = {
        'source_id': 'nse_rss',
        'source_name': 'NSE',
        'source_type': 'official_listing',
        'enabled': True,
        'verification_tier': 1,
        'fallback_collector': 'nse_announcements',
        'feeds': [('https://example.invalid/nse', 'nse')],
    }
    empty = SimpleNamespace(entries=[])
    nse_path = ctx['root'] / 'nse_announcements.json'
    nse_path.write_text(
        json.dumps({'high_impact': [{'symbol': 'INFY', 'subject': 'Board meeting', 'description': 'x'}]}),
        encoding='utf-8',
    )
    with patch('backend.collectors.news_provider_registry.feedparser.parse', return_value=empty):
        articles, _status = fetch_provider_rss(nse, session=_Sess())
    if not articles:
        return _fail('T25 expected NSE cache display rows')
    if any(a.get('published_at') or a.get('published') or a.get('source_time_basis') for a in articles):
        return _fail('T25 NSE cache became source publication')
    ingest_registry_articles(articles)
    if ctx['store'].exists():
        return _fail('T25 NSE cache created A1')
    _pass('T25')

    published = SimpleNamespace(entries=[
        SimpleNamespace(
            title='Infosys published parsed',
            link='https://economictimes.example.com/pub',
            summary='x',
            published_parsed=(2099, 7, 31, 4, 45, 0),
            updated_parsed=(2099, 7, 31, 10, 0, 0),
        ),
    ])
    for entry in published.entries:
        entry.get = lambda k, d=None, e=entry: getattr(e, k, d)
    with patch('backend.collectors.news_provider_registry.feedparser.parse', return_value=published):
        articles, _status = fetch_provider_rss(provider, session=_Sess())
    if articles[0].get('source_time_basis') != 'PUBLISHED_PARSED':
        return _fail(f'T26 basis {articles[0].get("source_time_basis")}')
    _pass('T26')

    updated = SimpleNamespace(entries=[
        SimpleNamespace(
            title='Infosys updated parsed',
            link='https://economictimes.example.com/upd',
            summary='x',
            published_parsed=None,
            updated_parsed=(2099, 7, 31, 4, 45, 0),
        ),
    ])
    for entry in updated.entries:
        entry.get = lambda k, d=None, e=entry: getattr(e, k, d)
    with patch('backend.collectors.news_provider_registry.feedparser.parse', return_value=updated):
        articles, _status = fetch_provider_rss(provider, session=_Sess())
    if articles[0].get('source_time_basis') != 'UPDATED_PARSED':
        return _fail(f'T27 basis {articles[0].get("source_time_basis")}')
    if articles[0].get('published_at') is None:
        return _fail('T27 missing source timestamp')
    _pass('T27')
    return 0


def test_t28_t37_adapter(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import (
        get_event,
        get_sighting,
        upsert_sighting,
    )
    from backend.news.rss_discovery_adapter import ingest_registry_articles
    from backend.news.source_time_provenance import lookup_source_time_provenance

    ctx['sidecar'].unlink(missing_ok=True)
    ctx['store'].unlink(missing_ok=True)
    art = _article(url='https://economictimes.example.com/native-1')
    stats = ingest_registry_articles([art])
    if int(stats.get('inserted') or 0) != 1:
        return _fail(f'T28 insert {stats}')
    if int(stats.get('provenance_inserted') or 0) != 1:
        return _fail(f'T28 sidecar not inserted first {stats}')
    sid, value = _sid_from_article(art)
    looked = lookup_source_time_provenance(sid)
    row = get_sighting(sid)
    if looked.get('entry', {}).get('source_time_value') != row.get('source_published_at'):
        return _fail('T28 exact binding failed')
    _pass('T28')

    ctx['sidecar'].unlink(missing_ok=True)
    ctx['store'].unlink(missing_ok=True)
    with patch(
        'backend.news.rss_discovery_adapter.record_source_time_provenance',
        return_value={'ok': False, 'status': 'FAILED'},
    ):
        blocked = ingest_registry_articles([_article(url='https://economictimes.example.com/blocked')])
    if int(blocked.get('inserted') or 0) != 0:
        return _fail(f'T29 A1 inserted despite provenance failure {blocked}')
    if ctx['store'].exists():
        return _fail('T29 A1 store created')
    _pass('T29')

    ctx['sidecar'].unlink(missing_ok=True)
    ctx['store'].unlink(missing_ok=True)
    orphan = _article(url='https://economictimes.example.com/orphan')
    sid, value = _sid_from_article(orphan)
    from backend.news.source_time_provenance import record_source_time_provenance

    rec = record_source_time_provenance(
        sighting_id=sid,
        source_time_value=value,
        source_time_basis='PUBLISHED_PARSED',
    )
    if rec.get('status') != 'INSERTED':
        return _fail(f'T30 sidecar setup {rec}')
    if ctx['store'].exists():
        return _fail('T30 A1 existed before retry')
    retry = ingest_registry_articles([orphan])
    if int(retry.get('inserted') or 0) != 1:
        return _fail(f'T30 orphan exact retry must insert A1 {retry}')
    if int(retry.get('provenance_idempotent') or 0) != 1:
        return _fail(f'T30 expected idempotent sidecar {retry}')
    _pass('T30')

    ctx['store'].unlink(missing_ok=True)
    mismatch = dict(orphan)
    mismatch['published_at'] = _iso(PUB2)
    denied = ingest_registry_articles([mismatch])
    if int(denied.get('inserted') or 0) != 0:
        return _fail(f'T31 orphan mismatch inserted A1 {denied}')
    if ctx['store'].exists():
        return _fail('T31 A1 created on mismatch')
    _pass('T31')

    ctx['sidecar'].unlink(missing_ok=True)
    ctx['store'].unlink(missing_ok=True)
    hist = _article(url='https://economictimes.example.com/historical')
    from backend.news.rss_discovery_adapter import article_to_sighting_payload

    payload = article_to_sighting_payload(hist)
    seeded = upsert_sighting(payload)
    sid = seeded['sighting_id']
    if lookup_source_time_provenance(sid).get('provenance') != 'SOURCE_TIME_AMBIGUOUS':
        return _fail('T32 pre-D2P fixture not AMBIGUOUS')
    again = ingest_registry_articles([hist])
    if lookup_source_time_provenance(sid).get('lookup') == 'SOURCE_TIME_PRESENT' or lookup_source_time_provenance(sid).get('entry'):
        return _fail('T32 late provenance row created')
    if int(again.get('deduplicated') or 0) != 1:
        return _fail(f'T32 historical last_seen path {again}')
    _pass('T32')

    ctx['sidecar'].unlink(missing_ok=True)
    ctx['store'].unlink(missing_ok=True)
    a = _article(url='https://economictimes.example.com/sameday', published_at=_iso(PUB))
    payload_a = article_to_sighting_payload(a)
    first = upsert_sighting(payload_a)
    b = _article(url='https://economictimes.example.com/sameday', published_at=_iso(PUB2))
    payload_b = article_to_sighting_payload(b)
    second = upsert_sighting(payload_b)
    if first['sighting_id'] != second['sighting_id']:
        return _fail('T33 foundation same-id expected')
    row = get_sighting(first['sighting_id'])
    if row.get('source_published_at') == _iso(PUB) and _iso(PUB2) != _iso(PUB):
        if row.get('source_published_at') != second['sighting']['source_published_at']:
            return _fail('T33 foundation did not replace timestamp')
    if row.get('source_published_at') != _iso(PUB2) and row.get('source_published_at') != second['sighting']['source_published_at']:
        return _fail(f'T33 expected replaced timestamp, got {row.get("source_published_at")}')
    _pass('T33A_FOUNDATION_REPLACE_OK')

    ctx['sidecar'].unlink(missing_ok=True)
    ctx['store'].unlink(missing_ok=True)
    native = _article(url='https://economictimes.example.com/bound', published_at=_iso(PUB))
    ingest_registry_articles([native])
    sid, bound = _sid_from_article(native)
    drifted = _article(url='https://economictimes.example.com/bound', published_at=_iso(PUB2))
    ingest_registry_articles([drifted])
    row = get_sighting(sid)
    if row.get('source_published_at') != bound:
        return _fail(f'T33 D2P adapter allowed replacement {row.get("source_published_at")}')
    looked = lookup_source_time_provenance(sid)
    if looked.get('entry', {}).get('source_time_value') != bound:
        return _fail('T33 sidecar binding rewritten')
    _pass('T33')

    conflict_basis = _article(
        url='https://economictimes.example.com/bound',
        published_at=_iso(PUB),
        source_time_basis='UPDATED_PARSED',
    )
    ingest_registry_articles([conflict_basis])
    if lookup_source_time_provenance(sid).get('entry', {}).get('source_time_basis') != 'PUBLISHED_PARSED':
        return _fail('T34 basis overwritten')
    _pass('T34')

    before_seen = get_sighting(sid)['last_seen_at']
    ingest_registry_articles([native])
    after = get_sighting(sid)
    if after['source_published_at'] != bound:
        return _fail('T35 bound timestamp changed')
    if after['last_seen_at'] == '':
        return _fail('T35 last_seen missing')
    if before_seen and after['last_seen_at'] < before_seen:
        return _fail('T35 last_seen moved backwards')
    _pass('T35')

    ctx['sidecar'].unlink(missing_ok=True)
    ctx['store'].unlink(missing_ok=True)
    mismatch_art = _article(url='https://economictimes.example.com/mismatch', published_at=_iso(PUB))
    ingest_registry_articles([mismatch_art])
    sid_m, bound_m = _sid_from_article(mismatch_art)
    upsert_sighting(article_to_sighting_payload(_article(
        url='https://economictimes.example.com/mismatch',
        published_at=_iso(PUB2),
    )))
    drifted_row = get_sighting(sid_m)
    ingest_registry_articles([_article(url='https://economictimes.example.com/mismatch', published_at=_iso(PUB))])
    after_row = get_sighting(sid_m)
    if after_row.get('source_published_at') != drifted_row.get('source_published_at'):
        return _fail('T36 observation repaired or widened mismatch')
    if lookup_source_time_provenance(sid_m).get('entry', {}).get('source_time_value') != bound_m:
        return _fail('T36 sidecar rewritten')
    _pass('T36')

    ctx['sidecar'].write_text('{', encoding='utf-8')
    ctx['store'].unlink(missing_ok=True)
    unhealthy = ingest_registry_articles([_article(url='https://economictimes.example.com/unhealthy-new')])
    if int(unhealthy.get('inserted') or 0) != 0:
        return _fail(f'T37 new A1 insert on unhealthy sidecar {unhealthy}')
    _pass('T37')
    ctx['sidecar'].unlink(missing_ok=True)

    ctx['sidecar'].unlink(missing_ok=True)
    try:
        seeded = upsert_sighting(article_to_sighting_payload(_article(url='https://economictimes.example.com/primary')))
        before_status = get_event(seeded['event_id'])['verification_status']
        ingest_registry_articles([_article(url='https://economictimes.example.com/primary')])
        after_status = get_event(seeded['event_id'])['verification_status']
        if after_status != before_status:
            return _fail(f'T38 verification changed {before_status} -> {after_status}')
    except Exception as exc:
        return _fail(f'T38 {type(exc).__name__}: {exc}')
    _pass('T38')
    return 0


def test_t39_t45_regressions(ctx: dict, before_digests: dict[str, str], before_data: str) -> int:
    from backend.news.broker_discovery_foundation import SCHEMA_VERSION

    if SCHEMA_VERSION != '52R-A1':
        return _fail(f'T39 A1 schema {SCHEMA_VERSION}')
    src = (PROJECT_ROOT / 'backend/news/broker_discovery_foundation.py').read_text(encoding='utf-8')
    if 'def compute_event_fingerprint' not in src or 'event_date_bucket(published_at)' not in src:
        return _fail('T39 fingerprint formula missing')
    if 'def compute_sighting_fingerprint' not in src:
        return _fail('T39 sighting fingerprint missing')
    _pass('T39')

    c1a = (PROJECT_ROOT / 'backend/news/verified_intelligence_store.py').read_text(encoding='utf-8')
    if 'def compute_record_fingerprint' not in c1a or 'INTELLIGENCE_SCHEMA_VERSION' not in c1a:
        return _fail('T40 C1A hash helpers missing')
    _pass('T40')

    c1b = (PROJECT_ROOT / 'backend/news/verified_intelligence_classifier.py').read_text(encoding='utf-8')
    if "DERIVATION_VERSION = '52R-C1B'" not in c1b:
        return _fail('T41 C1B derivation changed')
    _pass('T41')

    d1 = (PROJECT_ROOT / 'backend/news/news_pipeline_reliability.py').read_text(encoding='utf-8')
    if "SCHEMA_VERSION = '52R-D1'" not in d1:
        return _fail('T42 D1 schema changed')
    tracker = (PROJECT_ROOT / 'backend/collectors/live_news_tracker.py').read_text(encoding='utf-8')
    if 'ingest_discovery=True' not in tracker or 'record_news_pipeline_attempt' not in tracker:
        return _fail('T42 tracker control-flow B missing')
    _pass('T42')

    for path in (MODULE_PATH, ADAPTER_PATH):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        for bad in ('requests', 'httpx', 'openai', 'anthropic', 'groq'):
            if bad in imported:
                return _fail(f'T43/T44 {path.name} imports {bad}')
    _pass('T43')
    _pass('T44')

    for path in PROTECTED:
        if _digest(path) != before_digests[str(path)]:
            return _fail(f'protected mutated during tests: {path}')
    if _git_data_status() != before_data:
        return _fail('data/ dirty after tests')
    _pass('T45')
    return 0


def test_zero_network_module() -> int:
    src = MODULE_PATH.read_text(encoding='utf-8')
    for needle in ('requests', 'httpx', 'feedparser', 'openai', 'anthropic', 'groq'):
        if needle in src:
            return _fail(f'provenance module mentions {needle}')
    if 'age_seconds' in src or 'freshness_state' in src:
        return _fail('D2P module must not compute age/freshness')
    _pass('T_MODULE_NO_AGE_OK')
    return 0


def main() -> int:
    before_data = _git_data_status()
    before_digests = {str(path): _digest(path) for path in PROTECTED}
    rc = test_build()
    if rc:
        return rc
    rc = test_zero_network_module()
    if rc:
        return rc
    with _isolated() as ctx:
        for fn in (
            test_t1_t2_health,
            test_t3_t13_schema,
            test_t14_t22_write_once,
            test_t23_t27_registry,
            test_t28_t37_adapter,
        ):
            code = fn(ctx)
            if code:
                return code
        rc = test_t39_t45_regressions(ctx, before_digests, before_data)
        if rc:
            return rc
    required = [
        'T0_BUILD_PAIR_OK', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11', 'T12', 'T13',
        'T14', 'T15', 'T16', 'T17', 'T18', 'T19', 'T20', 'T21', 'T22',
        'T23', 'T24', 'T25', 'T26', 'T27',
        'T28', 'T29', 'T30', 'T31', 'T32', 'T33', 'T34', 'T35', 'T36', 'T37', 'T38',
        'T39', 'T40', 'T41', 'T42', 'T43', 'T44', 'T45',
        'T_MODULE_NO_AGE_OK',
    ]
    missing = [m for m in required if m not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers {missing}')
    print('SOURCE_TIME_PROVENANCE_52R_D2P_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
