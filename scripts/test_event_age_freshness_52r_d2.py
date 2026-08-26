#!/usr/bin/env python3
"""AstraEdge 52R-D2 — read-time event freshness projection focused tests (isolated)."""

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
SRC = datetime(2099, 7, 31, 10, 15, 0, tzinfo=IST)
FIRST = datetime(2099, 7, 31, 10, 16, 0, tzinfo=IST)
NOW = datetime(2099, 7, 31, 10, 20, 0, tzinfo=IST)
PASS_MARKERS: list[str] = []

MODULE_PATH = PROJECT_ROOT / 'backend' / 'news' / 'event_freshness_projection.py'
A1_PATH = PROJECT_ROOT / 'backend' / 'news' / 'broker_discovery_foundation.py'
D2P_PATH = PROJECT_ROOT / 'backend' / 'news' / 'source_time_provenance.py'
C1A_PATH = PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_store.py'
C1B_PATH = PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_classifier.py'
D1_PATH = PROJECT_ROOT / 'backend' / 'news' / 'news_pipeline_reliability.py'
PROTECTED_TRADING = (
    PROJECT_ROOT / 'backend' / 'trading' / 'market_freshness_guard.py',
    PROJECT_ROOT / 'backend' / 'trading' / 'opening_session_freshness.py',
    PROJECT_ROOT / 'backend' / 'orchestration' / 'alert_freshness_gate.py',
    PROJECT_ROOT / 'backend' / 'runtime' / 'snapshot_freshness_monitor.py',
)
PROTECTED_INGEST = (
    PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py',
    PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py',
    PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py',
)


def _fail(msg: str) -> int:
    print(f'EVENT_AGE_FRESHNESS_52R_D2_FAIL: {msg}', file=sys.stderr)
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
        c1a = root / 'verified_news_intelligence_store.json'
        d1 = root / 'news_pipeline_reliability.json'

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
            },
            clear=False,
        ), patch(
            'backend.news.broker_discovery_foundation.get_data_path',
            side_effect=_temp_data_path,
        ):
            yield {
                'root': root,
                'sidecar': sidecar,
                'lock': lock,
                'store': root / 'broker_news_discovery_store.json',
                'c1a': c1a,
                'd1': d1,
            }


def _sighting(
    *,
    url: str,
    published: datetime = SRC,
    first_seen: datetime = FIRST,
    headline: str = 'Infosys reports other event',
    event_id: str = '',
):
    from backend.news.broker_discovery_foundation import (
        SOURCE_KIND_NEWS_PUBLISHER,
        build_source_sighting,
    )

    return build_source_sighting(
        source_name='ET Markets',
        source_kind=SOURCE_KIND_NEWS_PUBLISHER,
        source_url=url,
        source_headline=headline,
        source_published_at=published,
        original_publisher='ET Markets',
        bounded_excerpt='Bounded excerpt for Infosys.',
        event_id=event_id,
        first_seen_at=first_seen,
        last_seen_at=first_seen,
        now=first_seen,
    )


def _event(*, published: datetime = SRC, first_seen: datetime = FIRST, headline: str = 'Infosys reports other event'):
    from backend.news.broker_discovery_foundation import build_canonical_event

    return build_canonical_event(
        event_type='OTHER',
        symbols=['INFY'],
        canonical_headline=headline,
        published_at=published,
        first_seen_at=first_seen,
        last_seen_at=first_seen,
        now=first_seen,
    )


def _bind(sighting: dict, *, basis: str = 'PUBLISHED_PARSED'):
    from backend.news.source_time_provenance import record_source_time_provenance

    rec = record_source_time_provenance(
        sighting_id=sighting['sighting_id'],
        source_time_value=sighting['source_published_at'],
        source_time_basis=basis,
        now=FIRST,
    )
    if rec.get('status') != 'INSERTED':
        raise AssertionError(f'bind failed {rec}')
    return rec


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
    return imported


def test_t1_build() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if (BUILD_STAGE, TELEGRAM_BUILD) not in {
        ('52R-D2', 'AstraEdge 52R-D2'),
        ('53A', 'AstraEdge 53A'),
        ('53A2', 'AstraEdge 53A2'),
        ('53B', 'AstraEdge 53B'),
        ('53C', 'AstraEdge 53C'),
        ('53D', 'AstraEdge 53D'),
    }:
        return _fail(
            f'expected 52R-D2 or successor 53A/53A2/53B/53C/53D pair, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    _pass('T1')
    return 0


def test_t2_t4_binding(ctx: dict) -> int:
    from backend.news.event_freshness_projection import (
        KIND_PUBLICATION,
        KIND_UPDATE,
        STATE_OK,
        project_sighting_freshness,
    )

    published = _sighting(url='https://economictimes.example.com/d2-pub')
    _bind(published, basis='PUBLISHED_PARSED')
    pub = project_sighting_freshness(published, now=NOW)
    if pub['source_time_state'] != STATE_OK:
        return _fail(f'T2 state {pub["source_time_state"]}')
    if pub['source_time_kind'] != KIND_PUBLICATION:
        return _fail('T2 kind must be PUBLICATION')
    if pub['publication_age_seconds'] != 300:
        return _fail(f'T2 expected 300s got {pub["publication_age_seconds"]}')
    if pub['source_update_age_seconds'] is not None:
        return _fail('T2 update age must be null')
    _pass('T2')

    updated = _sighting(url='https://economictimes.example.com/d2-upd', headline='Infosys update clock')
    _bind(updated, basis='UPDATED_PARSED')
    upd = project_sighting_freshness(updated, now=NOW)
    if upd['source_time_kind'] != KIND_UPDATE:
        return _fail('T3 kind must be UPDATE')
    if upd['source_update_age_seconds'] != 300:
        return _fail(f'T3 expected update 300s got {upd["source_update_age_seconds"]}')
    if upd['publication_age_seconds'] is not None:
        return _fail('T3/T4 publication age must be null for UPDATED_PARSED')
    _pass('T3')
    _pass('T4')
    return 0


def test_t5_t7_fail_closed(ctx: dict) -> int:
    from backend.news.event_freshness_projection import (
        STATE_AMBIGUOUS,
        STATE_BINDING_MISMATCH,
        project_sighting_freshness,
    )

    historical = _sighting(url='https://economictimes.example.com/d2-hist')
    if ctx['sidecar'].exists():
        ctx['sidecar'].unlink()
    missing = project_sighting_freshness(historical, now=NOW)
    if missing['source_time_state'] != STATE_AMBIGUOUS:
        return _fail(f'T5 expected AMBIGUOUS, got {missing["source_time_state"]}')
    if missing['publication_age_seconds'] is not None or missing['source_update_age_seconds'] is not None:
        return _fail('T5 source ages must be null')
    _pass('T5')
    if missing['source_published_at_canonical'] != historical['source_published_at']:
        return _fail('T6 parseable historical timestamp should still surface canonical text')
    if missing['publication_age_seconds'] is not None:
        return _fail('T6 parseable historical timestamp must not produce source age')
    _pass('T6')

    bound = _sighting(url='https://economictimes.example.com/d2-mismatch')
    _bind(bound, basis='PUBLISHED_PARSED')
    drifted = dict(bound)
    drifted['source_published_at'] = _iso(SRC + timedelta(minutes=5))
    mismatch = project_sighting_freshness(drifted, now=NOW)
    if mismatch['source_time_state'] != STATE_BINDING_MISMATCH:
        return _fail(f'T7 expected BINDING_MISMATCH got {mismatch["source_time_state"]}')
    if mismatch['publication_age_seconds'] is not None or mismatch['source_update_age_seconds'] is not None:
        return _fail('T7 source ages must be null')
    _pass('T7')

    present = _sighting(url='https://economictimes.example.com/d2-missing-entry')
    looked = project_sighting_freshness(present, now=NOW)
    if looked['source_time_state'] != STATE_AMBIGUOUS:
        return _fail('missing sidecar entry must stay AMBIGUOUS')
    if looked['publication_age_seconds'] is not None:
        return _fail('missing entry must not age')
    return 0


def test_t8_t10_sidecar_and_malformed(ctx: dict) -> int:
    from backend.news.event_freshness_projection import (
        STATE_AMBIGUOUS,
        STATE_BINDING_MISMATCH,
        STATE_MALFORMED,
        STATE_SIDECAR_UNHEALTHY,
        project_sighting_freshness,
    )

    row = _sighting(url='https://economictimes.example.com/d2-malformed-sidecar')
    ctx['sidecar'].write_text('{"schema_version": "52R-D2P"}', encoding='utf-8')
    malformed = project_sighting_freshness(row, now=NOW)
    if malformed['source_time_state'] != STATE_SIDECAR_UNHEALTHY:
        return _fail(f'T8 expected SIDECAR_UNHEALTHY got {malformed["source_time_state"]}')
    if malformed['publication_age_seconds'] is not None or malformed['source_update_age_seconds'] is not None:
        return _fail('T8 source ages must be null')
    _pass('T8')

    ctx['sidecar'].write_bytes(b'\xff\xfe not-utf8')
    unread = project_sighting_freshness(row, now=NOW)
    if unread['source_time_state'] != STATE_SIDECAR_UNHEALTHY:
        return _fail(f'T9 expected SIDECAR_UNHEALTHY got {unread["source_time_state"]}')
    if unread['publication_age_seconds'] is not None:
        return _fail('T9 source ages must be null')
    _pass('T9')

    if ctx['sidecar'].exists():
        ctx['sidecar'].unlink()
    bad_ts = dict(row)
    bad_ts['source_published_at'] = '2099-07-31T10:15:00Z'
    malformed_ts = project_sighting_freshness(bad_ts, now=NOW)
    if malformed_ts['publication_age_seconds'] is not None or malformed_ts['source_update_age_seconds'] is not None:
        return _fail('T10 malformed source timestamp must not age')
    if malformed_ts['source_time_state'] not in {STATE_AMBIGUOUS, STATE_MALFORMED, STATE_BINDING_MISMATCH}:
        return _fail(f'T10 unexpected state {malformed_ts["source_time_state"]}')
    _pass('T10')
    return 0


def test_t11_t16_future_and_discovery(ctx: dict) -> int:
    from backend.news.event_freshness_projection import (
        STATE_FUTURE,
        STATE_MALFORMED,
        STATE_MISSING,
        STATE_OK,
        project_sighting_freshness,
    )

    future_pub = _sighting(
        url='https://economictimes.example.com/d2-future-pub',
        published=NOW + timedelta(minutes=5),
        first_seen=FIRST,
    )
    _bind(future_pub, basis='PUBLISHED_PARSED')
    fut = project_sighting_freshness(future_pub, now=NOW)
    if fut['source_time_state'] != STATE_FUTURE:
        return _fail(f'T11 expected FUTURE got {fut["source_time_state"]}')
    if fut['publication_age_seconds'] in (0,):
        return _fail('T11 must not clamp future publication age to 0')
    if fut['publication_age_seconds'] is not None:
        return _fail('T11 future publication age must be null')
    _pass('T11')

    future_upd = _sighting(
        url='https://economictimes.example.com/d2-future-upd',
        published=NOW + timedelta(minutes=9),
        first_seen=FIRST,
        headline='Infosys future update',
    )
    _bind(future_upd, basis='UPDATED_PARSED')
    futu = project_sighting_freshness(future_upd, now=NOW)
    if futu['source_time_state'] != STATE_FUTURE:
        return _fail(f'T12 expected FUTURE got {futu["source_time_state"]}')
    if futu['source_update_age_seconds'] is not None:
        return _fail('T12 future update age must be null, not 0')
    _pass('T12')

    healthy = _sighting(url='https://economictimes.example.com/d2-discovery')
    _bind(healthy, basis='PUBLISHED_PARSED')
    disc = project_sighting_freshness(healthy, now=NOW)
    if disc['discovery_age_seconds'] != 240:
        return _fail(f'T13 expected discovery 240s got {disc["discovery_age_seconds"]}')
    if disc['discovery_time_state'] != STATE_OK:
        return _fail('T13 discovery state must be OK')
    _pass('T13')

    malformed_first = dict(healthy)
    malformed_first['first_seen_at'] = 'not-a-timestamp'
    bad_first = project_sighting_freshness(malformed_first, now=NOW)
    if bad_first['discovery_age_seconds'] is not None or bad_first['discovery_time_state'] != STATE_MALFORMED:
        return _fail('T14 malformed first_seen must null discovery age')
    _pass('T14')

    future_first = dict(healthy)
    future_first['first_seen_at'] = _iso(NOW + timedelta(seconds=30))
    fut_first = project_sighting_freshness(future_first, now=NOW)
    if fut_first['discovery_age_seconds'] is not None or fut_first['discovery_time_state'] != STATE_FUTURE:
        return _fail('T15 future first_seen must be FUTURE with null age')
    _pass('T15')

    if ctx['sidecar'].exists():
        ctx['sidecar'].unlink()
    independent = project_sighting_freshness(healthy, now=NOW)
    if independent['source_time_state'] != 'SOURCE_TIME_AMBIGUOUS':
        return _fail('T16 source provenance should fail closed')
    if independent['publication_age_seconds'] is not None:
        return _fail('T16 source age must stay null')
    if independent['discovery_age_seconds'] != 240:
        return _fail('T16 valid discovery age must survive source provenance failure')
    missing_first = dict(healthy)
    missing_first.pop('first_seen_at', None)
    missing_disc = project_sighting_freshness(missing_first, now=NOW)
    if missing_disc['discovery_time_state'] != STATE_MISSING:
        return _fail('missing first_seen_at must be MISSING')
    _pass('T16')
    return 0


def test_t17_t19_arithmetic(ctx: dict) -> int:
    from backend.news.event_freshness_projection import project_sighting_freshness

    row = _sighting(url='https://economictimes.example.com/d2-boundary')
    _bind(row, basis='PUBLISHED_PARSED')
    exact = NOW
    proj = project_sighting_freshness(row, now=exact)
    if proj['publication_age_seconds'] != 300:
        return _fail(f'T17 expected exact 300 got {proj["publication_age_seconds"]}')
    boundary = SRC + timedelta(seconds=10)
    ten = project_sighting_freshness(row, now=boundary)
    if ten['publication_age_seconds'] != 10:
        return _fail(f'T17 second-boundary expected 10 got {ten["publication_age_seconds"]}')
    _pass('T17')

    first = project_sighting_freshness(row, now=NOW)
    second = project_sighting_freshness(row, now=NOW)
    if first != second:
        return _fail('T18 injected now must be deterministic')
    _pass('T18')

    later = project_sighting_freshness(row, now=NOW + timedelta(seconds=7))
    if later['publication_age_seconds'] != 307:
        return _fail('T19 second now must change projection only')
    if later['sighting_id'] != first['sighting_id']:
        return _fail('T19 identity must stay stable')
    if later['now'] == first['now']:
        return _fail('T19 now field must change')
    _pass('T19')
    return 0


def test_t20_t23_immutability(ctx: dict) -> int:
    from backend.news.event_freshness_projection import project_event_freshness, project_sighting_freshness

    event = _event()
    row = _sighting(
        url='https://economictimes.example.com/d2-immutable',
        event_id=event['event_id'],
    )
    ctx['store'].write_text(
        '{"schema_version":"52R-A1","events":{},"sightings":{},"updated_at":"'
        + _iso(FIRST)
        + '"}\n',
        encoding='utf-8',
    )
    _bind(row, basis='PUBLISHED_PARSED')
    a1_before = ctx['store'].read_bytes() if ctx['store'].exists() else b''
    d2p_before = ctx['sidecar'].read_bytes()
    ctx['c1a'].write_text('{"schema_version":"52R-C1A","records":{}}\n', encoding='utf-8')
    ctx['d1'].write_text('{"schema_version":"52R-D1","last_success_at":"x"}\n', encoding='utf-8')
    c1a_before = ctx['c1a'].read_bytes()
    d1_before = ctx['d1'].read_bytes()

    project_sighting_freshness(row, now=NOW)
    project_event_freshness(event, linked_sightings=[row], now=NOW)

    if ctx['store'].read_bytes() != a1_before:
        return _fail('T20 A1 bytes changed')
    _pass('T20')
    if ctx['sidecar'].read_bytes() != d2p_before:
        return _fail('T21 D2P sidecar bytes changed')
    _pass('T21')
    if ctx['c1a'].read_bytes() != c1a_before:
        return _fail('T22 C1A bytes changed')
    _pass('T22')
    if ctx['d1'].read_bytes() != d1_before:
        return _fail('T23 D1 bytes changed')
    _pass('T23')
    return 0


def test_t24_t35_events(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY
    from backend.news.event_freshness_projection import (
        AGGREGATE_ALL_AMBIGUOUS,
        AGGREGATE_ALL_PRESENT,
        AGGREGATE_MIXED,
        AGGREGATE_NO_SIGHTINGS,
        project_event_freshness,
        project_sighting_freshness,
    )

    event = _event()
    empty = project_event_freshness(event, linked_sightings=[], now=NOW)
    if empty['event_source_time_aggregate'] != AGGREGATE_NO_SIGHTINGS:
        return _fail(f'T24 expected NO_SIGHTINGS got {empty["event_source_time_aggregate"]}')
    if empty['publication_age_seconds'] is not None or empty['source_update_age_seconds'] is not None:
        return _fail('T24 event source ages must be null')
    _pass('T24')

    hist_a = _sighting(
        url='https://economictimes.example.com/d2-e-hist-a',
        event_id=event['event_id'],
    )
    hist_b = _sighting(
        url='https://economictimes.example.com/d2-e-hist-b',
        headline='Infosys other headline',
        event_id=event['event_id'],
    )
    if ctx['sidecar'].exists():
        ctx['sidecar'].unlink()
    all_amb = project_event_freshness(event, linked_sightings=[hist_a, hist_b], now=NOW)
    if all_amb['event_source_time_aggregate'] != AGGREGATE_ALL_AMBIGUOUS:
        return _fail(f'T25 expected ALL_AMBIGUOUS got {all_amb["event_source_time_aggregate"]}')
    _pass('T25')

    present_a = _sighting(
        url='https://economictimes.example.com/d2-e-pres-a',
        event_id=event['event_id'],
    )
    present_b = _sighting(
        url='https://economictimes.example.com/d2-e-pres-b',
        headline='Infosys present b',
        event_id=event['event_id'],
    )
    _bind(present_a, basis='PUBLISHED_PARSED')
    _bind(present_b, basis='PUBLISHED_PARSED')
    all_present = project_event_freshness(event, linked_sightings=[present_a, present_b], now=NOW)
    if all_present['event_source_time_aggregate'] != AGGREGATE_ALL_PRESENT:
        return _fail(f'T26 expected ALL_PRESENT got {all_present["event_source_time_aggregate"]}')
    if all_present['publication_age_seconds'] is not None:
        return _fail('T26 ALL_PRESENT must not age the event')
    _pass('T26')

    mixed = project_event_freshness(event, linked_sightings=[present_a, hist_a], now=NOW)
    if mixed['event_source_time_aggregate'] != AGGREGATE_MIXED:
        return _fail(f'T27 expected MIXED got {mixed["event_source_time_aggregate"]}')
    _pass('T27')

    upd = _sighting(
        url='https://economictimes.example.com/d2-e-upd',
        headline='Infosys mixed kind',
        event_id=event['event_id'],
    )
    _bind(upd, basis='UPDATED_PARSED')
    mixed_kind = project_event_freshness(event, linked_sightings=[present_a, upd], now=NOW)
    if mixed_kind['event_source_time_aggregate'] != AGGREGATE_MIXED:
        return _fail(f'T28 expected MIXED kinds got {mixed_kind["event_source_time_aggregate"]}')
    _pass('T28')

    mismatch_row = dict(present_b)
    mismatch_row['source_published_at'] = _iso(SRC + timedelta(minutes=1))
    mismatch_event = project_event_freshness(event, linked_sightings=[present_a, mismatch_row], now=NOW)
    if mismatch_event['event_source_time_aggregate'] != AGGREGATE_MIXED:
        return _fail(f'T29 expected fail-closed MIXED got {mismatch_event["event_source_time_aggregate"]}')
    if mismatch_event['publication_age_seconds'] is not None:
        return _fail('T29 event publication age must stay null')
    _pass('T29')

    aged_event = dict(event)
    aged_event['published_at'] = _iso(SRC - timedelta(days=3))
    no_event_age = project_event_freshness(aged_event, linked_sightings=[present_a], now=NOW)
    if no_event_age['publication_age_seconds'] is not None:
        return _fail('T30 must not age event.published_at')
    _pass('T30')

    primary_event = dict(event)
    primary_event['verification_status'] = VERIFICATION_PRIMARY
    primary_event['primary_source_url'] = present_a['source_url']
    if ctx['sidecar'].exists():
        ctx['sidecar'].unlink()
    primary_amb = project_event_freshness(primary_event, linked_sightings=[hist_a], now=NOW)
    if primary_event['verification_status'] != VERIFICATION_PRIMARY:
        return _fail('T31 PRIMARY must remain PRIMARY')
    if primary_amb['publication_age_seconds'] is not None:
        return _fail('T31 PRIMARY + ambiguous must not invent publication age')
    _pass('T31')

    _bind(present_a, basis='PUBLISHED_PARSED')
    primary_present = project_event_freshness(primary_event, linked_sightings=[present_a], now=NOW)
    if primary_event['verification_status'] != VERIFICATION_PRIMARY:
        return _fail('T32 PRIMARY must remain PRIMARY')
    if primary_present['publication_age_seconds'] is not None:
        return _fail('T32 PRIMARY must not become the event clock')
    _pass('T32')

    if 'PRIMARY' in json.dumps(primary_present.get('event_source_time_aggregate')):
        return _fail('T33 aggregate must not select PRIMARY as time source')
    sighting_ids = {row['sighting_id'] for row in primary_present['sighting_projections']}
    if present_a['sighting_id'] not in sighting_ids:
        return _fail('T33 must project supplied sightings, not PRIMARY url')
    _pass('T33')

    with_d1 = dict(event)
    with_d1['last_success_at'] = _iso(NOW - timedelta(minutes=1))
    d1_proj = project_event_freshness(with_d1, linked_sightings=[present_a], now=NOW)
    if d1_proj['publication_age_seconds'] is not None:
        return _fail('T34 D1 last_success_at must be irrelevant')
    _pass('T34')

    blob = json.dumps(d1_proj)
    for token in ('CURRENT', 'STALE', 'FRESH', 'OLD', 'EXPIRED'):
        if f'"{token}"' in blob or f': {token}' in blob:
            if token in str(d1_proj.get('event_source_time_aggregate')):
                return _fail(f'T35 event state token {token} produced')
            # Ignore substrings inside ISO timestamps; require exact JSON string tokens.
            if f'"{token}"' in blob:
                return _fail(f'T35 event state token {token} produced')
    for token in ('CURRENT', 'STALE', 'FRESH', 'OLD', 'EXPIRED'):
        if d1_proj.get('event_source_time_aggregate') == token:
            return _fail(f'T35 aggregate is {token}')
    _pass('T35')
    return 0


def test_t36_t45_contract() -> int:
    src = MODULE_PATH.read_text(encoding='utf-8')
    imported = _imported_names(src)
    if 'source_age_seconds' in src:
        return _fail('T36 generic source_age_seconds contract exists')
    if '_verified_linked_sighting' not in src:
        return _fail('T36 missing verified event/sighting linkage helper')
    if 'sighting_event_id != event_id' not in src:
        return _fail('T36 missing exact sighting.event_id == event.event_id check')
    if 'health if health != HEALTH_OK else HEALTH_MALFORMED' in src:
        return _fail('T36 must not synthesize SIDECAR_UNHEALTHY from malformed sighting_id')
    _pass('T36')

    for mod in ('requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser'):
        if mod in imported:
            return _fail(f'T37 network import {mod}')
        if f'import {mod}' in src or f'from {mod}' in src:
            return _fail(f'T37 network line {mod}')
    _pass('T37')

    for needle in ('openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai'):
        if needle in src:
            return _fail(f'T38 AI needle {needle}')
    _pass('T38')

    for needle in (
        'atomic_write',
        'record_source_time_provenance',
        'upsert_sighting',
        'upsert_event',
        '_atomic_save',
        'open(',
        'write_text',
        'write_bytes',
    ):
        if needle in src:
            return _fail(f'T39 write path {needle}')
    _pass('T39')

    for needle in ('list_event_sightings', 'get_sighting', 'get_event', 'load_store', 'find_events_by_symbol'):
        if needle in src:
            return _fail(f'T40 store scan {needle}')
    _pass('T40')

    from backend.news.broker_discovery_foundation import SCHEMA_VERSION as A1_SCHEMA
    from backend.news.source_time_provenance import SCHEMA_VERSION as D2P_SCHEMA
    from backend.news.verified_intelligence_store import INTELLIGENCE_SCHEMA_VERSION
    from backend.news.verified_intelligence_classifier import DERIVATION_VERSION

    if A1_SCHEMA != '52R-A1':
        return _fail(f'T41 A1 schema {A1_SCHEMA}')
    _pass('T41')
    if D2P_SCHEMA != '52R-D2P':
        return _fail(f'T42 D2P schema {D2P_SCHEMA}')
    _pass('T42')
    if INTELLIGENCE_SCHEMA_VERSION != '52R-C1A' or DERIVATION_VERSION != '52R-C1B':
        return _fail('T43 C1A/C1B versions changed')
    _pass('T43')

    for path in PROTECTED_TRADING + PROTECTED_INGEST:
        proc = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD', '--', str(path.relative_to(PROJECT_ROOT)).replace('\\', '/')],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if (proc.stdout or '').strip():
            return _fail(f'T44 protected file changed: {path.name}')
    _pass('T44')

    if _git_data_status():
        return _fail('T45 data/ is not clean')
    _pass('T45')
    return 0


def test_t46_t55_repair(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY
    from backend.news.event_freshness_projection import (
        AGGREGATE_ALL_PRESENT,
        AGGREGATE_NO_SIGHTINGS,
        STATE_MALFORMED,
        STATE_SIDECAR_UNHEALTHY,
        project_event_freshness,
        project_sighting_freshness,
    )
    from backend.news.source_time_provenance import SOURCE_TIME_AMBIGUOUS, SOURCE_TIME_PRESENT

    anchor = _sighting(url='https://economictimes.example.com/d2-repair-anchor')
    _bind(anchor, basis='PUBLISHED_PARSED')

    missing_id = dict(anchor)
    missing_id.pop('sighting_id', None)
    missing_proj = project_sighting_freshness(missing_id, now=NOW)
    if missing_proj['source_time_state'] != STATE_MALFORMED:
        return _fail(f'T46 expected MALFORMED got {missing_proj["source_time_state"]}')
    if missing_proj['source_time_state'] == STATE_SIDECAR_UNHEALTHY:
        return _fail('T46 healthy sidecar + missing sighting_id must not be SIDECAR_UNHEALTHY')
    if missing_proj['source_time_provenance'] in {SOURCE_TIME_PRESENT, SOURCE_TIME_AMBIGUOUS}:
        return _fail('T46 malformed identity must not report PRESENT or AMBIGUOUS provenance')
    if missing_proj['publication_age_seconds'] is not None or missing_proj['source_update_age_seconds'] is not None:
        return _fail('T46 source ages must be null')
    _pass('T46')

    invalid_id = dict(anchor)
    invalid_id['sighting_id'] = 'not-a-uuid'
    invalid_proj = project_sighting_freshness(invalid_id, now=NOW)
    if invalid_proj['source_time_state'] != STATE_MALFORMED:
        return _fail(f'T47 expected MALFORMED got {invalid_proj["source_time_state"]}')
    if invalid_proj['source_time_state'] == STATE_SIDECAR_UNHEALTHY:
        return _fail('T47 invalid sighting_id must not be SIDECAR_UNHEALTHY')
    if invalid_proj['source_time_provenance'] in {SOURCE_TIME_PRESENT, SOURCE_TIME_AMBIGUOUS}:
        return _fail('T47 invalid identity must not report PRESENT or AMBIGUOUS provenance')
    if invalid_proj['publication_age_seconds'] is not None or invalid_proj['source_update_age_seconds'] is not None:
        return _fail('T47 source ages must be null')
    _pass('T47')

    if ctx['sidecar'].exists():
        ctx['sidecar'].unlink()
    missing_sidecar = project_sighting_freshness(invalid_id, now=NOW)
    if missing_sidecar['source_time_state'] != STATE_MALFORMED:
        return _fail(f'T48 expected MALFORMED got {missing_sidecar["source_time_state"]}')
    if missing_sidecar['source_time_state'] == SOURCE_TIME_AMBIGUOUS or missing_sidecar['source_time_provenance'] == SOURCE_TIME_AMBIGUOUS:
        return _fail('T48 missing sidecar + invalid sighting_id must be MALFORMED, not AMBIGUOUS')
    _pass('T48')

    valid = _sighting(url='https://economictimes.example.com/d2-repair-valid-id')
    ctx['sidecar'].write_text('{"schema_version": "52R-D2P"}', encoding='utf-8')
    malformed_sidecar = project_sighting_freshness(valid, now=NOW)
    if malformed_sidecar['source_time_state'] != STATE_SIDECAR_UNHEALTHY:
        return _fail(f'T49 expected SIDECAR_UNHEALTHY got {malformed_sidecar["source_time_state"]}')
    if malformed_sidecar['publication_age_seconds'] is not None or malformed_sidecar['source_update_age_seconds'] is not None:
        return _fail('T49 sidecar-unhealthy source ages must be null')
    _pass('T49')

    if ctx['sidecar'].exists():
        ctx['sidecar'].unlink()
    discovery_row = dict(anchor)
    discovery_row['sighting_id'] = 'not-a-uuid'
    discovery_row['first_seen_at'] = _iso(FIRST)
    disc = project_sighting_freshness(discovery_row, now=NOW)
    if disc['source_time_state'] != STATE_MALFORMED:
        return _fail(f'T50 expected source MALFORMED got {disc["source_time_state"]}')
    if disc['discovery_age_seconds'] != 240:
        return _fail(f'T50 expected discovery 240s got {disc["discovery_age_seconds"]}')
    if disc['publication_age_seconds'] is not None or disc['source_update_age_seconds'] is not None:
        return _fail('T50 source ages must stay null')
    _pass('T50')

    event_e1 = _event(headline='Infosys reports other event')
    event_e2 = _event(headline='Wipro reports unrelated event')
    foreign = _sighting(
        url='https://economictimes.example.com/d2-link-e2',
        headline='Wipro reports unrelated event',
        event_id=event_e2['event_id'],
    )
    _bind(foreign, basis='PUBLISHED_PARSED')
    e2_only = project_event_freshness(event_e1, linked_sightings=[foreign], now=NOW)
    if e2_only['event_source_time_aggregate'] != AGGREGATE_NO_SIGHTINGS:
        return _fail(f'T51 expected NO_SIGHTINGS got {e2_only["event_source_time_aggregate"]}')
    if e2_only['linked_sighting_count'] != 0 or e2_only['projected_sighting_count'] != 0:
        return _fail('T51 E2 sighting must be excluded from E1 counts')
    if e2_only['sighting_projections']:
        return _fail('T51 E2 sighting must not be projected onto E1')
    if e2_only['publication_age_seconds'] is not None:
        return _fail('T51 excluded foreign sighting must not age the event')
    _pass('T51')

    empty_eid = _sighting(
        url='https://economictimes.example.com/d2-link-empty-eid',
        event_id='',
    )
    missing_eid = dict(empty_eid)
    missing_eid.pop('event_id', None)
    empty_proj = project_event_freshness(event_e1, linked_sightings=[empty_eid, missing_eid], now=NOW)
    if empty_proj['event_source_time_aggregate'] != AGGREGATE_NO_SIGHTINGS:
        return _fail(f'T52 expected NO_SIGHTINGS got {empty_proj["event_source_time_aggregate"]}')
    if empty_proj['linked_sighting_count'] != 0 or empty_proj['projected_sighting_count'] != 0:
        return _fail('T52 missing/empty event_id sightings must be excluded')
    _pass('T52')

    linked = _sighting(
        url='https://economictimes.example.com/d2-link-e1',
        event_id=event_e1['event_id'],
    )
    _bind(linked, basis='PUBLISHED_PARSED')
    mixed_link = project_event_freshness(event_e1, linked_sightings=[linked, foreign], now=NOW)
    if mixed_link['event_source_time_aggregate'] != AGGREGATE_ALL_PRESENT:
        return _fail(f'T53 expected ALL_PRESENT from verified E1 only, got {mixed_link["event_source_time_aggregate"]}')
    if mixed_link['linked_sighting_count'] != 1 or mixed_link['projected_sighting_count'] != 1:
        return _fail('T53 linked/projected counts must include only the verified E1 sighting')
    projected_ids = [row['sighting_id'] for row in mixed_link['sighting_projections']]
    if projected_ids != [linked['sighting_id']]:
        return _fail('T53 only the E1-linked sighting may influence the aggregate')
    _pass('T53')

    unrelated_only = project_event_freshness(event_e1, linked_sightings=[foreign], now=NOW)
    if unrelated_only['event_source_time_aggregate'] != AGGREGATE_NO_SIGHTINGS:
        return _fail(f'T54 expected NO_SIGHTINGS got {unrelated_only["event_source_time_aggregate"]}')
    if unrelated_only['linked_sighting_count'] != 0 or unrelated_only['projected_sighting_count'] != 0:
        return _fail('T54 only-unrelated supply must yield zero verified links')
    _pass('T54')

    primary_event = dict(event_e1)
    primary_event['verification_status'] = VERIFICATION_PRIMARY
    primary_event['primary_source_url'] = foreign['source_url']
    primary_unrelated = project_event_freshness(primary_event, linked_sightings=[foreign], now=NOW)
    if primary_event['verification_status'] != VERIFICATION_PRIMARY:
        return _fail('T55 PRIMARY status must remain untouched')
    if primary_unrelated['event_source_time_aggregate'] != AGGREGATE_NO_SIGHTINGS:
        return _fail('T55 unrelated PRIMARY sighting must not become the event clock')
    if primary_unrelated['linked_sighting_count'] != 0:
        return _fail('T55 unrelated PRIMARY sighting is not an event link')
    if primary_unrelated['publication_age_seconds'] is not None or primary_unrelated['source_update_age_seconds'] is not None:
        return _fail('T55 unrelated PRIMARY sighting must not age the event')
    if primary_unrelated['sighting_projections']:
        return _fail('T55 unrelated PRIMARY sighting must not enter sighting_projections')
    _pass('T55')
    return 0


def main() -> int:
    data_before = _git_data_status()
    if data_before:
        return _fail('repository data/ is not clean before tests')

    rc = test_t1_build()
    if rc:
        return rc
    with _isolated() as ctx:
        for fn in (
            test_t2_t4_binding,
            test_t5_t7_fail_closed,
            test_t8_t10_sidecar_and_malformed,
            test_t11_t16_future_and_discovery,
            test_t17_t19_arithmetic,
            test_t20_t23_immutability,
            test_t24_t35_events,
            test_t46_t55_repair,
        ):
            rc = fn(ctx)
            if rc:
                return rc
    rc = test_t36_t45_contract()
    if rc:
        return rc
    if _git_data_status():
        return _fail('repository data/ mutated')
    required = [f'T{i}' for i in range(1, 56)]
    missing = [m for m in required if m not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers {missing}')
    print('EVENT_AGE_FRESHNESS_52R_D2_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
