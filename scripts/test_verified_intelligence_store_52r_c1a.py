#!/usr/bin/env python3
"""AstraEdge 52R-C1A — verified intelligence store foundation (isolated, dormant)."""

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
PASS_MARKERS: list[str] = []

MODULE_PATH = PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_store.py'
TRACKER_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py'
SCHEDULER_PATH = PROJECT_ROOT / 'backend' / 'master_scheduler.py'
FOUNDATION_PATH = PROJECT_ROOT / 'backend' / 'news' / 'broker_discovery_foundation.py'

EVENT_ID = '6f2c8d1a-52a1-4a01-9b7e-0c1d2e3f4a5b'
EVENT_FP = 'a' * 64
PRIMARY_URL = 'https://nsearchives.nseindia.com/corporate/INFY_ANNOUNCEMENT_1.pdf'
HEADLINE = 'Infosys Limited — Board Meeting Intimation'
UPDATED = datetime(2099, 7, 31, 10, 15, 0, tzinfo=IST)
DERIVED = datetime(2099, 8, 1, 9, 0, 0, tzinfo=IST)

FORBIDDEN_IMPORTS = frozenset({
    'requests', 'httpx', 'aiohttp', 'feedparser', 'selenium', 'playwright',
    'openai', 'anthropic', 'groq',
})
DISCOVERY_MUTATION = (
    'upsert_sighting',
    'mark_primary_source_verified',
    'run_automatic_primary_verification',
    'verify_linked_primary_sighting',
    'attach_sighting_to_event',
)


def _fail(msg: str) -> int:
    print(f'VERIFIED_INTELLIGENCE_STORE_52R_C1A_FAIL: {msg}', file=sys.stderr)
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


def _snapshot_data() -> dict[str, tuple[int, int]]:
    from scripts._test_runtime_isolation import snapshot_data_tree

    return snapshot_data_tree()


def _base_payload(**extra):
    row = {
        'source_event_id': EVENT_ID,
        'source_event_fingerprint': EVENT_FP,
        'source_canonical_headline': HEADLINE,
        'source_verification_status': 'PRIMARY_SOURCE_VERIFIED',
        'source_primary_url': PRIMARY_URL,
        'source_event_updated_at': UPDATED,
        'classification': 'BOARD_MEETING_INTIMATION',
        'classification_provenance': 'PARSED_CANONICAL_HEADLINE',
        'facts': {},
        'fact_provenance': [],
    }
    row.update(extra)
    return row


@contextmanager
def _isolated():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td) / 'data'
        temp_root.mkdir(parents=True, exist_ok=True)
        lock_path = Path(td) / 'verified_news_intelligence_store.lock'

        def _temp_data_path(relative: str) -> Path:
            rel = str(relative or '').replace('\\', '/').lstrip('/')
            path = temp_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            return path

        with patch.dict(os.environ, {'VERIFIED_INTELLIGENCE_LOCK_PATH': str(lock_path)}, clear=False), patch(
            'backend.news.verified_intelligence_store.get_data_path',
            side_effect=_temp_data_path,
        ):
            yield {
                'temp_root': temp_root,
                'lock_path': lock_path,
                'store_path': temp_root / 'verified_news_intelligence_store.json',
            }


def test_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    allowed = {('52R-C1A', 'AstraEdge 52R-C1A'), ('52R-C1B', 'AstraEdge 52R-C1B'), ('52R-D', 'AstraEdge 52R-D'), ('52R-D2P', 'AstraEdge 52R-D2P'), ('52R-D2', 'AstraEdge 52R-D2'), ('53A', 'AstraEdge 53A')}
    mismatches = (
        ('52R-C1A', 'AstraEdge 52R-B2'),
        ('52R-B2', 'AstraEdge 52R-C1A'),
        ('52R-C1A', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-C1A'),
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
    )
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'expected exact pair 52R-C1A / AstraEdge 52R-C1A or successor '
            f'52R-C1B / AstraEdge 52R-C1B or 52R-D / AstraEdge 52R-D, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    print(f'BUILD_PAIR {BUILD_STAGE} / {TELEGRAM_BUILD}')
    _pass('C1A_BUILD_PAIR_OK')
    return 0


def test_health_missing_and_empty(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import (
        HEALTH_MISSING,
        HEALTH_OK,
        get_verified_intelligence_store_health,
        find_recent_verified_intelligence,
        find_verified_intelligence_for_event,
    )

    health = get_verified_intelligence_store_health()
    if health.get('health') != HEALTH_MISSING:
        return _fail(f'expected MISSING, got {health}')
    if health.get('record_count') != 0 or health.get('available') is not True:
        return _fail(f'MISSING must be healthy-empty: {health}')
    if find_recent_verified_intelligence() != []:
        return _fail('missing store queries must return []')
    if find_verified_intelligence_for_event(EVENT_ID) != []:
        return _fail('missing store event query must return []')
    _pass('C1A_MISSING_STORE_HEALTH_OK')

    ctx['store_path'].write_text(
        json.dumps({
            'schema_version': '52R-C1A',
            'updated_at': '2099-08-01T09:00:00+05:30',
            'records': [],
        }, indent=2)
        + '\n',
        encoding='utf-8',
    )
    health_ok = get_verified_intelligence_store_health()
    if health_ok.get('health') != HEALTH_OK or health_ok.get('record_count') != 0:
        return _fail(f'valid empty store must be OK: {health_ok}')
    _pass('C1A_VALID_EMPTY_STORE_OK')
    return 0


def test_insert_and_determinism(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import (
        build_verified_intelligence_record,
        compute_intelligence_id,
        compute_record_fingerprint,
        compute_source_input_hash,
        find_verified_intelligence_for_event,
        upsert_verified_intelligence_record,
    )

    a = build_verified_intelligence_record(**_base_payload(), now=DERIVED)
    b = build_verified_intelligence_record(**_base_payload(), now=DERIVED)
    if a != b:
        return _fail('paired builders must be byte-identical for the same inputs')
    _pass('C1A_BUILD_PAIR_EXACT_OK')

    first = upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
    if not first.get('ok') or not first.get('inserted'):
        return _fail(f'first PRIMARY insert failed: {first}')
    rec = first['record']
    if rec['facts'] != {} or rec['fact_provenance'] != []:
        return _fail('C1A insert must remain classification-only')
    _pass('C1A_FIRST_PRIMARY_INSERT_OK')

    expected_id = compute_intelligence_id(
        source_event_id=EVENT_ID,
        derivation_version='52R-C1A',
        taxonomy_version='52R-C1A',
    )
    if rec['intelligence_id'] != expected_id:
        return _fail('intelligence_id is not deterministic from logical key')
    _pass('C1A_DETERMINISTIC_INTELLIGENCE_ID_OK')

    expected_input = compute_source_input_hash(
        source_event_id=EVENT_ID,
        source_event_fingerprint=EVENT_FP,
        source_canonical_headline=HEADLINE,
        source_verification_status='PRIMARY_SOURCE_VERIFIED',
        source_primary_url=rec['source_primary_url'],
    )
    if rec['source_input_hash'] != expected_input:
        return _fail('source_input_hash mismatch')
    _pass('C1A_DETERMINISTIC_SOURCE_INPUT_HASH_OK')

    expected_fp = compute_record_fingerprint(
        source_event_id=EVENT_ID,
        derivation_version='52R-C1A',
        taxonomy_version='52R-C1A',
        source_input_hash=expected_input,
        classification='BOARD_MEETING_INTIMATION',
        facts={},
        classification_provenance='PARSED_CANONICAL_HEADLINE',
        fact_provenance=[],
        fact_parser_version='classification_only',
    )
    if rec['record_fingerprint'] != expected_fp:
        return _fail('record_fingerprint mismatch')
    _pass('C1A_DETERMINISTIC_RECORD_FINGERPRINT_OK')

    later = DERIVED + timedelta(hours=3)
    second = upsert_verified_intelligence_record(_base_payload(), now=later)
    if not second.get('ok') or not second.get('idempotent') or second.get('inserted'):
        return _fail(f'repeat upsert must be idempotent: {second}')
    if second['record']['derived_at'] != rec['derived_at']:
        return _fail('idempotent upsert must preserve derived_at')
    rows = find_verified_intelligence_for_event(EVENT_ID)
    if len(rows) != 1:
        return _fail(f'idempotent upsert created duplicates: {len(rows)}')
    _pass('C1A_IDEMPOTENT_UPSERT_OK')
    _pass('C1A_DERIVED_AT_PRESERVED_OK')
    return 0


def test_version_conflicts_and_new_versions(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import upsert_verified_intelligence_record

    seeded = upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
    if not seeded.get('ok'):
        return _fail(f'seed failed: {seeded}')

    changed_input = upsert_verified_intelligence_record(
        _base_payload(source_canonical_headline='Infosys Limited — Press Release'),
        now=DERIVED,
    )
    if changed_input.get('ok') or changed_input.get('reason') != 'version_conflict':
        return _fail(f'changed source input must version_conflict: {changed_input}')
    _pass('C1A_VERSION_CONFLICT_SOURCE_INPUT_OK')

    changed_class = upsert_verified_intelligence_record(
        _base_payload(classification='PRESS_RELEASE'),
        now=DERIVED,
    )
    if changed_class.get('ok') or changed_class.get('reason') != 'version_conflict':
        return _fail(f'changed classification must version_conflict: {changed_class}')
    _pass('C1A_VERSION_CONFLICT_CLASSIFICATION_OK')

    new_derivation = upsert_verified_intelligence_record(
        _base_payload(derivation_version='52R-C1A.1'),
        now=DERIVED,
    )
    if not new_derivation.get('ok') or not new_derivation.get('inserted'):
        return _fail(f'new derivation version must insert: {new_derivation}')
    if new_derivation['intelligence_id'] == seeded['intelligence_id']:
        return _fail('new derivation version must not reuse intelligence_id')
    _pass('C1A_NEW_DERIVATION_VERSION_ROW_OK')

    new_taxonomy = upsert_verified_intelligence_record(
        _base_payload(taxonomy_version='52R-C1A.taxonomy2'),
        now=DERIVED,
    )
    if not new_taxonomy.get('ok') or not new_taxonomy.get('inserted'):
        return _fail(f'new taxonomy version must insert: {new_taxonomy}')
    if new_taxonomy['intelligence_id'] in {seeded['intelligence_id'], new_derivation['intelligence_id']}:
        return _fail('new taxonomy version must not reuse prior intelligence_id')
    _pass('C1A_NEW_TAXONOMY_VERSION_ROW_OK')
    return 0


def test_input_rejections() -> int:
    from backend.news.verified_intelligence_store import (
        VerifiedIntelligenceError,
        build_verified_intelligence_record,
    )

    cases = [
        ('non-PRIMARY', _base_payload(source_verification_status='DISCOVERY_ONLY'), 'C1A_NON_PRIMARY_REJECTED_OK'),
        ('missing url', _base_payload(source_primary_url=''), 'C1A_MISSING_PRIMARY_URL_REJECTED_OK'),
        ('bad uuid', _base_payload(source_event_id='not-a-uuid'), 'C1A_MALFORMED_EVENT_UUID_REJECTED_OK'),
        ('bad fingerprint', _base_payload(source_event_fingerprint='deadbeef'), 'C1A_MALFORMED_SOURCE_FINGERPRINT_REJECTED_OK'),
        ('unknown class', _base_payload(classification='DIVIDEND'), 'C1A_UNKNOWN_CLASSIFICATION_REJECTED_OK'),
        ('invalid provenance', _base_payload(classification_provenance='AI_INFERRED'), 'C1A_INVALID_PROVENANCE_REJECTED_OK'),
        ('facts nonempty', _base_payload(facts={'amount': 1}), 'C1A_FACTS_NONEMPTY_REJECTED_OK'),
        ('fact provenance nonempty', _base_payload(fact_provenance=['x']), 'C1A_FACT_PROVENANCE_NONEMPTY_REJECTED_OK'),
    ]
    for label, payload, marker in cases:
        try:
            build_verified_intelligence_record(**payload, now=DERIVED)
        except VerifiedIntelligenceError:
            _pass(marker)
            continue
        return _fail(f'{label} must be rejected')
    try:
        build_verified_intelligence_record(
            **_base_payload(source_canonical_headline='<p>Board Meeting</p>'),
            now=DERIVED,
        )
    except VerifiedIntelligenceError:
        _pass('C1A_RAW_MARKUP_FORBIDDEN_OK')
    else:
        return _fail('markup headline must be rejected')
    try:
        build_verified_intelligence_record(
            **_base_payload(source_canonical_headline=HEADLINE, article_body='secret'),
            now=DERIVED,
        )
    except TypeError:
        _pass('C1A_ARTICLE_BODY_FORBIDDEN_OK')
    except VerifiedIntelligenceError:
        _pass('C1A_ARTICLE_BODY_FORBIDDEN_OK')
    else:
        return _fail('article_body must not be accepted as a builder field')
    return 0


def test_unhealthy_immutable(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import (
        HEALTH_MALFORMED,
        HEALTH_PARTIAL,
        HEALTH_UNREADABLE,
        VerifiedIntelligenceError,
        get_verified_intelligence_store_health,
        upsert_verified_intelligence_record,
    )

    path = ctx['store_path']
    path.write_text('{not json', encoding='utf-8')
    before = path.read_bytes()
    health = get_verified_intelligence_store_health()
    if health.get('health') != HEALTH_MALFORMED:
        return _fail(f'expected MALFORMED, got {health}')
    try:
        upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
        return _fail('malformed store must fail closed')
    except VerifiedIntelligenceError:
        pass
    if path.read_bytes() != before:
        return _fail('malformed store was mutated')
    _pass('C1A_MALFORMED_STORE_IMMUTABLE_OK')

    path.write_text(
        json.dumps({
            'schema_version': '52R-C1A',
            'updated_at': '2099-08-01T09:00:00+05:30',
            'records': [{
                'intelligence_id': 'not-valid',
                'source_event_id': EVENT_ID,
                'source_event_fingerprint': EVENT_FP,
                'source_canonical_headline': HEADLINE,
                'source_verification_status': 'PRIMARY_SOURCE_VERIFIED',
                'source_primary_url': PRIMARY_URL,
                'source_event_updated_at': '2099-07-31T10:15:00+05:30',
                'classification': 'OTHER',
                'facts': {},
                'classification_provenance': 'UNKNOWN',
                'fact_provenance': [],
                'derivation_version': '52R-C1A',
                'taxonomy_version': '52R-C1A',
                'fact_parser_version': 'classification_only',
                'source_input_hash': 'b' * 64,
                'record_fingerprint': 'c' * 64,
                'derived_at': '2099-08-01T09:00:00+05:30',
                'schema_version': '52R-C1A',
            }],
        }),
        encoding='utf-8',
    )
    before = path.read_bytes()
    health = get_verified_intelligence_store_health()
    if health.get('health') != HEALTH_PARTIAL:
        return _fail(f'expected PARTIAL, got {health}')
    try:
        upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
        return _fail('partial store must fail closed')
    except VerifiedIntelligenceError:
        pass
    if path.read_bytes() != before:
        return _fail('partial store was mutated')
    _pass('C1A_PARTIAL_STORE_IMMUTABLE_OK')

    path.write_bytes(b'\xff\xfe\x00not-utf8')
    before = path.read_bytes()
    health = get_verified_intelligence_store_health()
    if health.get('health') != HEALTH_UNREADABLE:
        return _fail(f'expected UNREADABLE, got {health}')
    try:
        upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
        return _fail('unreadable store must fail closed')
    except VerifiedIntelligenceError:
        pass
    if path.read_bytes() != before:
        return _fail('unreadable store was mutated')
    _pass('C1A_UNREADABLE_STORE_IMMUTABLE_OK')
    return 0


def test_lock_contention_zero_mutation(ctx: dict) -> int:
    from backend.news import verified_intelligence_store as vis

    lock = vis._IntelligenceLock(ctx['lock_path'])
    if not lock.try_acquire():
        return _fail('test lock acquire failed')
    try:
        existed = ctx['store_path'].exists()
        before = ctx['store_path'].read_bytes() if existed else b''
        result = vis.upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
        if not result.get('lock_contended') or result.get('ok'):
            return _fail(f'expected lock_contended, got {result}')
        after_exists = ctx['store_path'].exists()
        after = ctx['store_path'].read_bytes() if after_exists else b''
        if after_exists != existed or after != before:
            return _fail('lock contention mutated the store')
    finally:
        lock.release()
    _pass('C1A_LOCK_CONTENTION_ZERO_MUTATION_OK')
    return 0


def test_atomic_single_write(ctx: dict) -> int:
    from backend.news import verified_intelligence_store as vis

    writes: list[int] = []
    original = vis._atomic_save

    def _spy(path, payload):
        writes.append(1)
        return original(path, payload)

    with patch('backend.news.verified_intelligence_store._atomic_save', side_effect=_spy):
        first = vis.upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
        second = vis.upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
    if not first.get('inserted') or not second.get('idempotent'):
        return _fail(f'write-count fixture failed: {first} {second}')
    if len(writes) != 1:
        return _fail(f'expected one atomic write, got {len(writes)}')
    _pass('C1A_ATOMIC_SINGLE_WRITE_OK')
    return 0


def test_query_order_utf8_and_identity_metadata(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import (
        build_verified_intelligence_record,
        find_recent_verified_intelligence,
        find_verified_intelligence_for_event,
        upsert_verified_intelligence_record,
    )

    unicode_headline = 'Infosys Limited — Board Meeting Intimation café'
    first = upsert_verified_intelligence_record(
        _base_payload(source_canonical_headline=unicode_headline),
        now=DERIVED,
    )
    other_event = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    second = upsert_verified_intelligence_record(
        _base_payload(
            source_event_id=other_event,
            classification='OTHER',
            classification_provenance='UNKNOWN',
        ),
        now=DERIVED + timedelta(minutes=5),
    )
    if not first.get('ok') or not second.get('ok'):
        return _fail('seed for query tests failed')
    loaded = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    if 'café' not in json.dumps(loaded, ensure_ascii=False):
        return _fail('UTF-8 headline did not round-trip')
    _pass('C1A_UTF8_ROUND_TRIP_OK')

    recent = find_recent_verified_intelligence(limit=1)
    if len(recent) != 1 or recent[0]['source_event_id'] != other_event:
        return _fail(f'recent query order/limit failed: {recent}')
    for_event = find_verified_intelligence_for_event(EVENT_ID)
    if len(for_event) != 1 or 'café' not in for_event[0]['source_canonical_headline']:
        return _fail('event query failed to isolate UTF-8 record')
    _pass('C1A_QUERY_ORDER_LIMIT_OK')

    a = build_verified_intelligence_record(**_base_payload(), now=DERIVED)
    b = build_verified_intelligence_record(
        **_base_payload(source_event_updated_at=UPDATED + timedelta(hours=6)),
        now=DERIVED,
    )
    if a['source_input_hash'] != b['source_input_hash'] or a['intelligence_id'] != b['intelligence_id']:
        return _fail('source_event_updated_at must not change logical identity or input hash')
    if a['record_fingerprint'] != b['record_fingerprint']:
        return _fail('source_event_updated_at must not change record_fingerprint')
    _pass('C1A_UPDATED_AT_NOT_IDENTITY_OK')

    extra = _base_payload()
    extra['publisher_corroboration_count'] = 99
    extra['new_publisher_sighting'] = True
    c = build_verified_intelligence_record(
        source_event_id=extra['source_event_id'],
        source_event_fingerprint=extra['source_event_fingerprint'],
        source_canonical_headline=extra['source_canonical_headline'],
        source_verification_status=extra['source_verification_status'],
        source_primary_url=extra['source_primary_url'],
        classification=extra['classification'],
        classification_provenance=extra['classification_provenance'],
        source_event_updated_at=extra['source_event_updated_at'],
        now=DERIVED,
    )
    if c['intelligence_id'] != a['intelligence_id'] or c['source_input_hash'] != a['source_input_hash']:
        return _fail('publisher corroboration must not participate in C1A identity')
    if 'publisher_corroboration_count' in c or 'new_publisher_sighting' in c:
        return _fail('C1A record must not persist publisher corroboration metadata')
    _pass('C1A_NO_PUBLISHER_CORROBORATION_IDENTITY_OK')
    return 0


def test_corruption_detected(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import (
        HEALTH_PARTIAL,
        get_verified_intelligence_store_health,
        upsert_verified_intelligence_record,
    )

    seeded = upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
    if not seeded.get('ok'):
        return _fail('corruption fixture seed failed')
    payload = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    payload['records'][0]['record_fingerprint'] = 'd' * 64
    ctx['store_path'].write_text(json.dumps(payload), encoding='utf-8')
    health = get_verified_intelligence_store_health()
    if health.get('health') != HEALTH_PARTIAL:
        return _fail(f'fingerprint corruption must be PARTIAL, got {health}')
    _pass('C1A_FINGERPRINT_CORRUPTION_DETECTED_OK')
    payload['records'][0]['intelligence_id'] = '00000000-0000-4000-8000-000000000000'
    payload['records'][0]['record_fingerprint'] = seeded['record']['record_fingerprint']
    ctx['store_path'].write_text(json.dumps(payload), encoding='utf-8')
    health = get_verified_intelligence_store_health()
    if health.get('health') != HEALTH_PARTIAL:
        return _fail(f'id corruption must be PARTIAL, got {health}')
    _pass('C1A_RECORD_ID_CORRUPTION_DETECTED_OK')
    return 0


def test_safety_boundaries() -> int:
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
            for alias in node.names:
                imported.add(alias.name)
    for needle in FORBIDDEN_IMPORTS:
        if needle in imported:
            return _fail(f'C1A imports forbidden module {needle!r}')
    for bad in ('openai', 'anthropic', 'google.generativeai', 'stock_scanner', 'opening_rally_radar', 'ai_router'):
        if bad in imported or bad in src:
            return _fail(f'C1A must not reference {bad}')
    _pass('C1A_NO_NETWORK_AI_TRADING_IMPORTS_OK')

    for api in DISCOVERY_MUTATION:
        if api in src:
            return _fail(f'C1A must not mention discovery mutation API {api}')
    if 'upsert_sighting' in imported or 'mark_primary_source_verified' in imported:
        return _fail('C1A imported a discovery mutation API')
    _pass('C1A_NO_DISCOVERY_MUTATION_API_OK')

    caller_hits = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        rel = str(path.relative_to(PROJECT_ROOT)).replace('\\', '/')
        if rel == 'backend/news/verified_intelligence_store.py':
            continue
        text = path.read_text(encoding='utf-8')
        if 'upsert_verified_intelligence_record' in text or 'verified_intelligence_store' in text:
            caller_hits.append(rel)
    from backend.config.build_info import BUILD_STAGE as _stage
    authorized = set()
    if _stage in {'52R-C1B', '52R-D', '52R-D2P', '52R-D2', '53A'}:
        authorized = {'backend/news/verified_intelligence_classifier.py'}
    unexpected_callers = [hit for hit in caller_hits if hit not in authorized]
    if unexpected_callers:
        return _fail(f'production C1A callers exist: {unexpected_callers}')
    if _stage == '52R-C1A' and caller_hits:
        return _fail(f'production C1A callers exist: {caller_hits}')
    if _stage in {'52R-C1B', '52R-D', '52R-D2P', '52R-D2', '53A'} and set(caller_hits) != authorized:
        return _fail(f'C1B must be the only authorized C1A store consumer, got {caller_hits}')
    if 'verified_intelligence_store' in TRACKER_PATH.read_text(encoding='utf-8'):
        return _fail('live_news_tracker must not import C1A')
    if SCHEDULER_PATH.is_file() and 'verified_intelligence_store' in SCHEDULER_PATH.read_text(encoding='utf-8'):
        return _fail('master_scheduler must not import C1A')
    _pass('C1A_NO_PRODUCTION_CALLER_OK')
    _pass('C1A_DORMANT_PRODUCTION_OK')
    return 0


def test_repo_data_safe(before_snapshot: dict[str, tuple[int, int]]) -> int:
    after = _snapshot_data()
    if after != before_snapshot:
        return _fail('repository data/ mutated during C1A tests')
    if _git_data_status():
        return _fail('git data/ is not clean')
    real_store = PROJECT_ROOT / 'data' / 'verified_news_intelligence_store.json'
    if real_store.exists():
        return _fail('real repository intelligence store was created')
    _pass('C1A_NO_REAL_REPO_DATA_ACCESS_OK')
    return 0


def test_upsert_strict_input_schema(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import (
        VerifiedIntelligenceError,
        upsert_verified_intelligence_record,
    )

    store = ctx['store_path']
    lock = ctx['lock_path']
    if store.exists() or lock.exists():
        return _fail('strict-input fixture must start with no store or lock')

    forbidden = _base_payload(article_body='secret')
    try:
        upsert_verified_intelligence_record(forbidden, now=DERIVED)
        return _fail('article_body upsert payload must fail closed')
    except VerifiedIntelligenceError as exc:
        if 'article_body' not in str(exc):
            return _fail(f'article_body error must name the field, got {exc}')
    _pass('C1A_UPSERT_FORBIDDEN_FIELD_REJECTED_OK')

    unknown = _base_payload(unexpected_field='x')
    try:
        upsert_verified_intelligence_record(unknown, now=DERIVED)
        return _fail('unexpected_field upsert payload must fail closed')
    except VerifiedIntelligenceError as exc:
        if 'unexpected_field' not in str(exc):
            return _fail(f'unknown-field error must name the field, got {exc}')
    _pass('C1A_UPSERT_UNKNOWN_FIELD_REJECTED_OK')

    generated = _base_payload(intelligence_id='00000000-0000-4000-8000-000000000000')
    try:
        upsert_verified_intelligence_record(generated, now=DERIVED)
        return _fail('generated intelligence_id upsert payload must fail closed')
    except VerifiedIntelligenceError as exc:
        if 'intelligence_id' not in str(exc):
            return _fail(f'output-field error must name intelligence_id, got {exc}')
    fingerprint_payload = _base_payload(record_fingerprint='d' * 64)
    try:
        upsert_verified_intelligence_record(fingerprint_payload, now=DERIVED)
        return _fail('generated record_fingerprint upsert payload must fail closed')
    except VerifiedIntelligenceError as exc:
        if 'record_fingerprint' not in str(exc):
            return _fail(f'output-field error must name record_fingerprint, got {exc}')
    _pass('C1A_UPSERT_OUTPUT_FIELD_REJECTED_OK')

    if store.exists() or lock.exists():
        return _fail('rejected extra-field upsert created store or lock')

    seeded = upsert_verified_intelligence_record(_base_payload(), now=DERIVED)
    if not seeded.get('ok') or not store.is_file():
        return _fail(f'strict-input healthy seed failed: {seeded}')
    before_store = store.read_bytes()
    before_lock = lock.read_bytes() if lock.exists() else None
    try:
        upsert_verified_intelligence_record(
            _base_payload(publisher_corroboration_count=2),
            now=DERIVED,
        )
        return _fail('publisher corroboration upsert payload must fail closed')
    except VerifiedIntelligenceError:
        pass
    if store.read_bytes() != before_store:
        return _fail('extra-field upsert mutated an existing healthy store')
    after_lock = lock.read_bytes() if lock.exists() else None
    if after_lock != before_lock:
        return _fail('extra-field upsert mutated the lock file')
    _pass('C1A_UPSERT_EXTRA_FIELD_ZERO_MUTATION_OK')
    return 0


def main() -> int:
    before_snapshot = _snapshot_data()
    data_before = _git_data_status()
    if data_before:
        return _fail(f'repository data/ is not clean before tests: {data_before}')

    rc = test_build_identity()
    if rc:
        return rc
    rc = test_input_rejections()
    if rc:
        return rc
    rc = test_safety_boundaries()
    if rc:
        return rc

    with _isolated() as ctx:
        rc = test_health_missing_and_empty(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_insert_and_determinism(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_version_conflicts_and_new_versions(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_unhealthy_immutable(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_lock_contention_zero_mutation(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_upsert_strict_input_schema(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_atomic_single_write(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_query_order_utf8_and_identity_metadata(ctx)
        if rc:
            return rc
    with _isolated() as ctx:
        rc = test_corruption_detected(ctx)
        if rc:
            return rc

    rc = test_repo_data_safe(before_snapshot)
    if rc:
        return rc

    print('VERIFIED_INTELLIGENCE_STORE_52R_C1A_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
