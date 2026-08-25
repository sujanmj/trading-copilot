#!/usr/bin/env python3
"""AstraEdge 52R-C1B — deterministic verified intelligence classifier (isolated)."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import uuid
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
PASS_MARKERS: list[str] = []

MODULE_PATH = PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_classifier.py'
STORE_PATH = PROJECT_ROOT / 'backend' / 'news' / 'verified_intelligence_store.py'
TRACKER_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'live_news_tracker.py'
B1_PATH = PROJECT_ROOT / 'backend' / 'news' / 'primary_source_verifier.py'
B2_PATH = PROJECT_ROOT / 'backend' / 'news' / 'automatic_primary_verification.py'
A2_PATH = PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py'
PREMARKET_PATH = PROJECT_ROOT / 'backend' / 'telegram' / 'premarket_scheduler.py'
SCHEDULER_PATHS = (
    PROJECT_ROOT / 'backend' / 'orchestration' / 'master_scheduler.py',
    PROJECT_ROOT / 'backend' / 'master_scheduler.py',
)

PRIMARY_URL = 'https://nsearchives.nseindia.com/corporate/INFY_ANNOUNCEMENT_1.pdf'
UPDATED = datetime(2099, 7, 31, 10, 15, 0, tzinfo=IST)
FP_A = 'a' * 64
FP_B = 'b' * 64

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
    'upsert_event',
)
NETWORK_MODULES = (
    'requests', 'httpx', 'aiohttp', 'urllib.request', 'selenium', 'playwright', 'feedparser',
)
AI_NEEDLES = (
    'openai', 'anthropic', 'groq', 'ai_router', 'google.generativeai',
    'claude', 'gemini', 'llm',
)
TRADING_NEEDLES = (
    'stock_scanner', 'opening_rally_radar', 'trade_card_engine', 'tradecard',
    'market_freshness_guard', 'daily_learning_truth', 'candidate_outcome_learning',
)


def _fail(msg: str) -> int:
    print(f'VERIFIED_INTELLIGENCE_CLASSIFIER_52R_C1B_FAIL: {msg}', file=sys.stderr)
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


def _eid(n: int) -> str:
    return str(uuid.UUID(int=0x52C1B000000000000000000000000000 + n))


def _event(**extra: object) -> dict:
    row = {
        'event_id': _eid(1),
        'event_fingerprint': FP_A,
        'canonical_headline': 'Infosys Limited — Board Meeting Intimation',
        'verification_status': 'PRIMARY_SOURCE_VERIFIED',
        'primary_source_url': PRIMARY_URL,
        'updated_at': UPDATED.isoformat(),
        'last_seen_at': UPDATED.isoformat(),
    }
    row.update(extra)
    return row


@contextmanager
def _isolated():
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td) / 'data'
        temp_root.mkdir(parents=True, exist_ok=True)
        lock_path = Path(td) / 'verified_news_intelligence_store.lock'
        discovery_lock = Path(td) / 'rss_discovery_ingest.lock'

        def _temp_data_path(relative: str) -> Path:
            rel = str(relative or '').replace('\\', '/').lstrip('/')
            path = temp_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            return path

        with patch.dict(
            os.environ,
            {
                'VERIFIED_INTELLIGENCE_LOCK_PATH': str(lock_path),
                'RSS_DISCOVERY_LOCK_PATH': str(discovery_lock),
            },
            clear=False,
        ), patch(
            'backend.news.verified_intelligence_store.get_data_path',
            side_effect=_temp_data_path,
        ), patch(
            'backend.news.broker_discovery_foundation.get_data_path',
            side_effect=_temp_data_path,
        ):
            yield {
                'temp_root': temp_root,
                'lock_path': lock_path,
                'store_path': temp_root / 'verified_news_intelligence_store.json',
                'discovery_path': temp_root / 'broker_news_discovery_store.json',
            }


def _reset_sidecar(ctx: dict) -> None:
    store = ctx['store_path']
    if store.exists():
        store.unlink()
    lock = ctx['lock_path']
    if lock.exists():
        try:
            lock.unlink()
        except OSError:
            pass


def _run_with_events(events: list[dict], *, upsert_spy=None):
    from backend.news.verified_intelligence_classifier import (
        run_verified_intelligence_classification,
    )

    patches = [
        patch(
            'backend.news.verified_intelligence_classifier.find_recent_events',
            return_value=list(events),
        ),
    ]
    if upsert_spy is not None:
        from backend.news import verified_intelligence_store as vis

        original = vis.upsert_verified_intelligence_record

        def _wrapped(payload, **kwargs):
            upsert_spy.append(payload)
            return original(payload, **kwargs)

        patches.append(patch(
            'backend.news.verified_intelligence_classifier.upsert_verified_intelligence_record',
            side_effect=_wrapped,
        ))
    with patches[0]:
        if len(patches) == 1:
            return run_verified_intelligence_classification()
        with patches[1]:
            return run_verified_intelligence_classification()


def test_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    allowed = {('52R-C1B', 'AstraEdge 52R-C1B'), ('52R-D', 'AstraEdge 52R-D')}
    mismatches = (
        ('52R-C1B', 'AstraEdge 52R-C1A'),
        ('52R-C1A', 'AstraEdge 52R-C1B'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-B2', 'AstraEdge 52R-C1B'),
        ('52R-C1B', 'AstraEdge 52R-D'),
        ('52R-D', 'AstraEdge 52R-C1B'),
    )
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'expected exact pair 52R-C1B / AstraEdge 52R-C1B or successor '
            f'52R-D / AstraEdge 52R-D, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    print(f'BUILD_PAIR {BUILD_STAGE} / {TELEGRAM_BUILD}')
    _pass('C1B_BUILD_PAIR_OK')
    return 0


def test_unicode_separator_contract() -> int:
    from backend.news.verified_intelligence_classifier import HEADLINE_SEPARATOR

    if HEADLINE_SEPARATOR != ' \u2014 ':
        return _fail(f'HEADLINE_SEPARATOR must be space-emdash-space, got {HEADLINE_SEPARATOR!r}')
    if ord(HEADLINE_SEPARATOR.strip()) != 0x2014:
        return _fail(
            f'HEADLINE_SEPARATOR strip codepoint must be U+2014, got {ord(HEADLINE_SEPARATOR.strip()):#x}'
        )
    mojibake = '\u00e2\u20ac\u201d'
    for rel in (
        'backend/news/verified_intelligence_classifier.py',
        'scripts/test_verified_intelligence_classifier_52r_c1b.py',
        'scripts/validate_verified_intelligence_classifier_52r_c1b.py',
    ):
        text = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        if mojibake in text:
            return _fail(f'{rel} contains U+00E2 U+20AC U+201D mojibake')
    _pass('C1B_UNICODE_SEPARATOR_CONTRACT_OK')
    return 0


def test_headline_classification() -> int:
    from backend.news.verified_intelligence_classifier import (
        classify_verified_intelligence_headline,
    )

    board = classify_verified_intelligence_headline('Infosys Limited — Board Meeting Intimation')
    if board != {
        'classification': 'BOARD_MEETING_INTIMATION',
        'classification_provenance': 'PARSED_CANONICAL_HEADLINE',
    }:
        return _fail(f'board meeting mismatch: {board}')
    _pass('C1B_BOARD_MEETING_CLASSIFICATION_OK')

    investor = classify_verified_intelligence_headline('TCS — Investor Presentation')
    if investor != {
        'classification': 'INVESTOR_PRESENTATION',
        'classification_provenance': 'PARSED_CANONICAL_HEADLINE',
    }:
        return _fail(f'investor mismatch: {investor}')
    _pass('C1B_INVESTOR_PRESENTATION_CLASSIFICATION_OK')

    press = classify_verified_intelligence_headline('Infosys Limited — Press Release')
    if press != {
        'classification': 'PRESS_RELEASE',
        'classification_provenance': 'PARSED_CANONICAL_HEADLINE',
    }:
        return _fail(f'press mismatch: {press}')
    _pass('C1B_PRESS_RELEASE_CLASSIFICATION_OK')

    other_cases = {
        'Infosys Limited — Dividend': 'unmatched subject',
        'Board Meeting Intimation': 'no-separator',
        'Infosys Limited — ': 'empty-subject',
        'Infosys Limited — Board Meeting': 'Board Meeting',
        'Infosys Limited — Board Meeting Intimation.': 'trailing punctuation',
        'Infosys Limited — Investor Conference': 'Investor Conference',
        'Infosys Limited — Q2 Investor Presentation Deck': 'Q2 deck',
        'Infosys Limited — Press Release for Financial Results': 'press results',
        'Infosys Limited — Press Release.': 'press trailing punct',
        'Infosys Limited — Outcome of Board Meeting': 'outcome',
    }
    for headline, label in other_cases.items():
        got = classify_verified_intelligence_headline(headline)
        if got != {'classification': 'OTHER', 'classification_provenance': 'UNKNOWN'}:
            return _fail(f'{label} must be OTHER, got {got}')
    folded = classify_verified_intelligence_headline('Infosys Limited —   BOARD   meeting   INTIMATION')
    if folded['classification'] != 'BOARD_MEETING_INTIMATION':
        return _fail(f'case/whitespace must match, got {folded}')
    _pass('C1B_OTHER_FALLBACK_OK')
    _pass('C1B_NO_FUZZY_MATCHING_OK')
    _pass('C1B_PRECEDENCE_OK')
    return 0


def test_primary_only_and_contract(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import find_recent_verified_intelligence

    _reset_sidecar(ctx)
    skipped = [
        _event(verification_status='DISCOVERY_ONLY', event_id=_eid(2)),
        _event(verification_status='REJECTED', event_id=_eid(3)),
        _event(verification_status='', event_id=_eid(4)),
        _event(canonical_headline='', event_id=_eid(5)),
        _event(primary_source_url='', event_id=_eid(6)),
        _event(updated_at='', event_id=_eid(7)),
        _event(event_id='not-a-uuid', event_fingerprint=FP_A),
    ]
    primary = _event()
    stats = _run_with_events(skipped + [primary])
    if int(stats.get('inserted') or 0) != 1:
        return _fail(f'expected one PRIMARY insert, got {stats}')
    if int(stats.get('eligible_seen') or 0) != 1:
        return _fail(f'eligible_seen must be 1, got {stats}')
    rows = find_recent_verified_intelligence(limit=50)
    if len(rows) != 1:
        return _fail(f'expected one sidecar row, got {rows}')
    row = rows[0]
    if row.get('classification') != 'BOARD_MEETING_INTIMATION':
        return _fail(f'classification {row.get("classification")!r}')
    if row.get('classification_provenance') != 'PARSED_CANONICAL_HEADLINE':
        return _fail(f'provenance {row.get("classification_provenance")!r}')
    if row.get('facts') != {} or row.get('fact_provenance') != []:
        return _fail(f'facts contract broken: {row}')
    if row.get('fact_parser_version') != 'classification_only':
        return _fail(f'fact_parser_version {row.get("fact_parser_version")!r}')
    if row.get('derivation_version') != '52R-C1B':
        return _fail(f'derivation {row.get("derivation_version")!r}')
    if row.get('taxonomy_version') != '52R-C1A':
        return _fail(f'taxonomy {row.get("taxonomy_version")!r}')
    if row.get('schema_version') != '52R-C1A':
        return _fail(f'schema {row.get("schema_version")!r}')
    if not ctx['store_path'].is_file():
        return _fail('first successful write must create sidecar')
    _pass('C1B_PRIMARY_ONLY_OK')
    _pass('C1B_VERSION_CONTRACT_OK')
    _pass('C1B_FIRST_WRITE_CREATES_SIDECAR_OK')
    return 0


def test_other_write_provenance(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import find_recent_verified_intelligence

    _reset_sidecar(ctx)
    stats = _run_with_events([
        _event(canonical_headline='Infosys Limited — Dividend Announcement'),
    ])
    if int(stats.get('inserted') or 0) != 1:
        return _fail(f'OTHER insert failed: {stats}')
    row = find_recent_verified_intelligence(limit=1)[0]
    if row.get('classification') != 'OTHER' or row.get('classification_provenance') != 'UNKNOWN':
        return _fail(f'OTHER provenance failed: {row}')
    return 0


def test_missing_sidecar_stays_absent(ctx: dict) -> int:
    stats = _run_with_events([
        _event(verification_status='DISCOVERY_ONLY'),
    ])
    if ctx['store_path'].exists():
        return _fail('MISSING sidecar must remain absent without eligible writes')
    if stats.get('inserted'):
        return _fail(f'zero eligible must not insert: {stats}')
    if stats.get('store_health') != 'MISSING':
        return _fail(f'expected MISSING health, got {stats}')
    _pass('C1B_MISSING_STORE_ABSENT_OK')
    return 0


def test_precheck_idempotent_and_conflict(ctx: dict) -> int:
    from backend.news.verified_intelligence_store import (
        find_verified_intelligence_for_event,
        upsert_verified_intelligence_record,
    )

    _reset_sidecar(ctx)
    event = _event()
    first_spy: list = []
    first = _run_with_events([event], upsert_spy=first_spy)
    if int(first.get('inserted') or 0) != 1 or len(first_spy) != 1:
        return _fail(f'first insert fixture failed: {first} spy={len(first_spy)}')
    rows = find_verified_intelligence_for_event(event['event_id'])
    derived_at = rows[0]['derived_at']

    second_spy: list = []
    second = _run_with_events([event], upsert_spy=second_spy)
    if int(second.get('idempotent') or 0) != 1:
        return _fail(f'pre-check must count idempotent, got {second}')
    if second_spy:
        return _fail('exact pre-check skip must not call upsert')
    if int(second.get('attempted') or 0) != 0:
        return _fail(f'pre-check skip must not consume attempts, got {second}')
    after = find_verified_intelligence_for_event(event['event_id'])[0]
    if after.get('derived_at') != derived_at:
        return _fail('derived_at must be preserved')
    _pass('C1B_PRECHECK_IDEMPOTENT_SKIP_OK')
    _pass('C1B_DERIVED_AT_PRESERVED_OK')

    other_event = _event(
        event_id=_eid(20),
        canonical_headline='Infosys Limited — Board Meeting Intimation',
        event_fingerprint=FP_A,
    )
    seed = upsert_verified_intelligence_record({
        'source_event_id': other_event['event_id'],
        'source_event_fingerprint': FP_B,
        'source_canonical_headline': other_event['canonical_headline'],
        'source_verification_status': 'PRIMARY_SOURCE_VERIFIED',
        'source_primary_url': PRIMARY_URL,
        'source_event_updated_at': UPDATED,
        'classification': 'OTHER',
        'classification_provenance': 'UNKNOWN',
        'facts': {},
        'fact_provenance': [],
        'derivation_version': '52R-C1B',
        'taxonomy_version': '52R-C1A',
        'fact_parser_version': 'classification_only',
    })
    if not seed.get('inserted'):
        return _fail(f'conflict seed insert failed: {seed}')
    conflict_spy: list = []
    conflict = _run_with_events([other_event], upsert_spy=conflict_spy)
    if int(conflict.get('version_conflicts') or 0) != 1:
        return _fail(f'pre-check mismatch must surface version_conflict, got {conflict}')
    if not conflict_spy:
        return _fail('pre-check mismatch must still call upsert')
    _pass('C1B_PRECHECK_VERSION_CONFLICT_NOT_HIDDEN_OK')
    return 0


def test_bounds_and_backfill(ctx: dict) -> int:
    from backend.news.verified_intelligence_classifier import (
        EVENT_SCAN_LIMIT,
        MAX_CLASSIFICATION_ATTEMPTS,
        run_verified_intelligence_classification,
    )

    _reset_sidecar(ctx)
    if EVENT_SCAN_LIMIT != 50 or MAX_CLASSIFICATION_ATTEMPTS != 20:
        return _fail('bounds must remain scan 50 / attempts 20')

    limits: list[int] = []

    def _scan(limit=50):
        limits.append(limit)
        return [
            _event(event_id=_eid(100 + i), last_seen_at=UPDATED.isoformat())
            for i in range(60)
        ][:limit]

    with patch(
        'backend.news.verified_intelligence_classifier.find_recent_events',
        side_effect=_scan,
    ):
        stats = run_verified_intelligence_classification()
    if limits != [50]:
        return _fail(f'scan helper must be called with limit=50, got {limits}')
    if int(stats.get('scanned') or 0) > 50:
        return _fail(f'scanned exceeded 50: {stats}')
    _pass('C1B_BOUNDED_SCAN_OK')

    many = [_event(event_id=_eid(200 + i)) for i in range(25)]
    spy: list = []
    bounded = _run_with_events(many, upsert_spy=spy)
    if int(bounded.get('attempted') or 0) != 20:
        return _fail(f'attempt cap must be 20, got {bounded}')
    if len(spy) != 20:
        return _fail(f'upsert calls must be 20, got {len(spy)}')
    if not bounded.get('bounded'):
        return _fail(f'bounded flag must be True, got {bounded}')
    if int(bounded.get('inserted') or 0) != 20:
        return _fail(f'expected 20 inserts, got {bounded}')
    _pass('C1B_BOUNDED_ATTEMPTS_OK')

    preexisting = [_event(event_id=_eid(300 + i)) for i in range(3)]
    backfill = _run_with_events(preexisting)
    if int(backfill.get('inserted') or 0) != 3:
        return _fail(f'recent PRIMARY backfill failed: {backfill}')
    _pass('C1B_RECENT_BACKFILL_OK')
    return 0


def test_failure_containment(ctx: dict) -> int:
    from backend.news import verified_intelligence_store as vis

    _reset_sidecar(ctx)
    path = ctx['store_path']
    event = _event()

    path.write_text('{not json', encoding='utf-8')
    before = path.read_bytes()
    malformed = _run_with_events([event])
    if malformed.get('ok') is not False or malformed.get('store_health') != 'MALFORMED':
        return _fail(f'malformed must abort, got {malformed}')
    if path.read_bytes() != before:
        return _fail('malformed sidecar was overwritten')
    _pass('C1B_MALFORMED_STORE_IMMUTABLE_OK')

    path.write_text(
        json.dumps({
            'schema_version': '52R-C1A',
            'updated_at': '2099-08-01T09:00:00+05:30',
            'records': [{
                'intelligence_id': 'not-valid',
                'source_event_id': _eid(1),
                'source_event_fingerprint': FP_A,
                'source_canonical_headline': 'Infosys Limited — Board Meeting Intimation',
                'source_verification_status': 'PRIMARY_SOURCE_VERIFIED',
                'source_primary_url': PRIMARY_URL,
                'source_event_updated_at': '2099-07-31T10:15:00+05:30',
                'classification': 'OTHER',
                'facts': {},
                'classification_provenance': 'UNKNOWN',
                'fact_provenance': [],
                'derivation_version': '52R-C1B',
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
    partial = _run_with_events([event])
    if partial.get('ok') is not False or partial.get('store_health') != 'PARTIAL':
        return _fail(f'partial must abort, got {partial}')
    if path.read_bytes() != before:
        return _fail('partial sidecar was overwritten')
    _pass('C1B_PARTIAL_STORE_IMMUTABLE_OK')

    path.write_bytes(b'\xff\xfe\x00not-utf8')
    before = path.read_bytes()
    unreadable = _run_with_events([event])
    if unreadable.get('ok') is not False or unreadable.get('store_health') != 'UNREADABLE':
        return _fail(f'unreadable must abort, got {unreadable}')
    if path.read_bytes() != before:
        return _fail('unreadable sidecar was overwritten')
    _pass('C1B_UNREADABLE_STORE_IMMUTABLE_OK')

    if path.exists():
        path.unlink()
    lock = vis._IntelligenceLock(ctx['lock_path'])
    if not lock.try_acquire():
        return _fail('test lock acquire failed')
    try:
        existed = path.exists()
        before = path.read_bytes() if existed else b''
        contended = _run_with_events([
            _event(event_id=_eid(401)),
            _event(event_id=_eid(402)),
        ])
        if int(contended.get('lock_contended') or 0) != 1:
            return _fail(f'expected one lock_contended, got {contended}')
        if int(contended.get('attempted') or 0) != 1:
            return _fail(f'lock contention must stop further writes, got {contended}')
        after_exists = path.exists()
        after = path.read_bytes() if after_exists else b''
        if after_exists != existed or after != before:
            return _fail('lock contention mutated the store')
    finally:
        lock.release()
    _pass('C1B_LOCK_CONTENTION_CONTAINED_OK')
    return 0


def test_discovery_unchanged_and_imports() -> int:
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
    for needle in FORBIDDEN_IMPORTS | set(NETWORK_MODULES):
        if needle in imported:
            return _fail(f'classifier imports forbidden module {needle!r}')
    for bad in AI_NEEDLES:
        if bad in imported or bad in src.casefold():
            return _fail(f'classifier must not reference {bad}')
    for bad in TRADING_NEEDLES:
        if bad in imported or bad in src:
            return _fail(f'classifier must not reference trading {bad}')
    if 'rss_discovery_adapter' in src:
        return _fail('classifier must not import the A2 adapter')
    if 'primary_source_verifier' in src or 'verify_linked_primary_sighting' in src:
        return _fail('classifier must not call B1')
    for api in DISCOVERY_MUTATION:
        if api in src:
            return _fail(f'classifier must not mention discovery mutation API {api}')
    if 'discovery_lock_path' in src or '_BatchLock' in src:
        return _fail('classifier must not take the discovery write lock')
    _pass('C1B_ZERO_HTTP_CLASSIFIER')
    _pass('C1B_ZERO_AI_CANONICAL_CLASSIFICATION')
    _pass('C1B_NO_TRADING_BEHAVIOR_CHANGE')
    _pass('C1B_NO_NESTED_LOCKS_OK')
    _pass('C1B_NO_DISCOVERY_MUTATION_OK')
    return 0


def test_discovery_bytes_unchanged(ctx: dict) -> int:
    _reset_sidecar(ctx)
    discovery = ctx['discovery_path']
    payload = b'{"schema_version":"52R-A1","events":{},"sightings":{}}'
    discovery.write_bytes(payload)
    _run_with_events([_event()])
    if discovery.read_bytes() != payload:
        return _fail('discovery store bytes changed')
    _pass('C1B_DISCOVERY_STORE_UNCHANGED_OK')
    return 0


def test_production_caller() -> int:
    tracker = TRACKER_PATH.read_text(encoding='utf-8')
    ingest_idx = tracker.find('ingest_discovery=True')
    b2_idx = tracker.find('run_automatic_primary_verification')
    c1b_idx = tracker.find('run_verified_intelligence_classification')
    if ingest_idx < 0 or b2_idx < ingest_idx:
        return _fail('B2 must remain after ingest_discovery=True')
    if c1b_idx < 0 or c1b_idx < b2_idx:
        return _fail('C1B caller must be after B2 in run_live_news_tracker')
    if tracker.count('run_verified_intelligence_classification') != 2:
        return _fail('live_news_tracker must contain exactly one C1B import/call pair')
    if 'verified_intelligence_store' in tracker:
        return _fail('live_news_tracker must not import the C1A store directly')

    for path in (B1_PATH, B2_PATH, A2_PATH, PREMARKET_PATH):
        text = path.read_text(encoding='utf-8')
        if 'run_verified_intelligence_classification' in text:
            return _fail(f'{path.name} must not call C1B')
    for path in SCHEDULER_PATHS:
        if path.is_file() and 'run_verified_intelligence_classification' in path.read_text(encoding='utf-8'):
            return _fail(f'{path.name} must not call C1B as a separate job')

    from backend.collectors.live_news_tracker import run_live_news_tracker

    order: list[str] = []

    def _refresh(**_kwargs):
        order.append('refresh')
        return {
            'ok': True,
            'sources_checked': 0,
            'items_found': 0,
            'new_items': 0,
            'error_count': 0,
            'errors': [],
        }

    def _b2():
        order.append('b2')
        raise RuntimeError('b2-isolated-boom')

    def _c1b():
        order.append('c1b')
        return {
            'ok': True,
            'eligible_seen': 0,
            'attempted': 0,
            'inserted': 0,
            'idempotent': 0,
            'skipped': 0,
            'version_conflicts': 0,
            'lock_contended': 0,
            'failed': 0,
            'bounded': False,
            'store_health': 'MISSING',
        }

    with tempfile.TemporaryDirectory() as td:
        sidecar = Path(td) / 'news_pipeline_reliability.json'
        lock = Path(td) / 'news_pipeline_reliability.lock'
        with patch('backend.collectors.live_news_tracker.run_unified_news_refresh', side_effect=_refresh), patch(
            'backend.news.automatic_primary_verification.run_automatic_primary_verification',
            side_effect=_b2,
        ), patch(
            'backend.news.verified_intelligence_classifier.run_verified_intelligence_classification',
            side_effect=_c1b,
        ), patch.dict(
            os.environ,
            {
                'NEWS_PIPELINE_RELIABILITY_PATH': str(sidecar),
                'NEWS_PIPELINE_RELIABILITY_LOCK_PATH': str(lock),
            },
            clear=False,
        ):
            result = run_live_news_tracker()
    if order != ['refresh', 'b2', 'c1b']:
        return _fail(f'call order must be refresh/B2/C1B, got {order}')
    if 'verified_intelligence' not in result:
        return _fail('tracker must attach verified_intelligence stats')
    if result.get('primary_verification', {}).get('error_type') != 'RuntimeError':
        return _fail('B2 isolated failure dict missing')
    _pass('C1B_AFTER_B2_CALLER_OK')
    _pass('C1B_B2_FAILURE_DOES_NOT_BLOCK_C1B_OK')
    return 0


def test_repo_data_safe(before_snapshot: dict[str, tuple[int, int]]) -> int:
    after = _snapshot_data()
    if after != before_snapshot:
        return _fail('repository data/ mutated during C1B tests')
    if _git_data_status():
        return _fail('git data/ is not clean')
    real_store = PROJECT_ROOT / 'data' / 'verified_news_intelligence_store.json'
    if real_store.exists():
        return _fail('real repository intelligence store was created')
    _pass('C1B_NO_REAL_REPO_DATA_ACCESS_OK')
    return 0


def main() -> int:
    before_snapshot = _snapshot_data()
    rc = test_build_identity()
    if rc:
        return rc
    rc = test_unicode_separator_contract()
    if rc:
        return rc
    rc = test_headline_classification()
    if rc:
        return rc
    rc = test_discovery_unchanged_and_imports()
    if rc:
        return rc
    rc = test_production_caller()
    if rc:
        return rc
    with _isolated() as ctx:
        for fn in (
            test_missing_sidecar_stays_absent,
            test_primary_only_and_contract,
            test_other_write_provenance,
            test_precheck_idempotent_and_conflict,
            test_bounds_and_backfill,
            test_failure_containment,
            test_discovery_bytes_unchanged,
        ):
            rc = fn(ctx)
            if rc:
                return rc
    rc = test_repo_data_safe(before_snapshot)
    if rc:
        return rc
    print('VERIFIED_INTELLIGENCE_CLASSIFIER_52R_C1B_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
