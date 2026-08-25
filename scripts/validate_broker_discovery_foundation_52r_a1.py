#!/usr/bin/env python3
"""Validator — AstraEdge 52R-A1 broker news discovery foundation (read-only)."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

WATCHED_PATHS = (
    PROJECT_ROOT / 'backend' / 'config' / 'build_info.py',
    PROJECT_ROOT / 'backend' / 'news' / 'broker_discovery_foundation.py',
    PROJECT_ROOT / 'backend' / 'news' / '__init__.py',
    PROJECT_ROOT / 'scripts' / 'test_broker_discovery_foundation_52r_a1.py',
    PROJECT_ROOT / 'scripts' / 'validate_broker_discovery_foundation_52r_a1.py',
)

REQUIRED_MARKERS = (
    'BROKER_DISCOVERY_FOUNDATION_52R_A1_PASS',
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
    'MALFORMED_STORE_RAW_EXCEPTION_ESCAPE_COUNT=0',
    'PUBLIC_API_RAW_EXCEPTION_ESCAPE_COUNT=0',
)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52R_A1_BROKER_DISCOVERY_FAIL: {msg}', file=sys.stderr)
    return 1


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return 'missing'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    before = {str(p): _file_digest(p) for p in WATCHED_PATHS}

    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    allowed = {
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
        ('52R-C1B', 'AstraEdge 52R-C1B'),
        ('52R-D', 'AstraEdge 52R-D'),
        ('52R-D2P', 'AstraEdge 52R-D2P'),
        ('52R-D2', 'AstraEdge 52R-D2'),
    }
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'build must be an exact 52R-A1, 52R-A2, 52R-B1, 52R-B2N, 52R-B2, 52R-C1A, 52R-C1B, or 52R-D pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )

    foundation = PROJECT_ROOT / 'backend/news/broker_discovery_foundation.py'
    if not foundation.is_file():
        return _fail('missing backend/news/broker_discovery_foundation.py')
    src = foundation.read_text(encoding='utf-8')
    for needle in (
        'event_id',
        'event_fingerprint',
        'sighting_id',
        'DISCOVERY_ONLY',
        'MULTI_SOURCE_CONFIRMED',
        'PRIMARY_SOURCE_VERIFIED',
        'upsert_event',
        'upsert_sighting',
        'attach_sighting_to_event',
        'mark_primary_source_verified',
        'get_store_health',
        'MAX_EXCERPT_LENGTH',
        'BROKER_PUBLIC',
        'normalize_url',
        'compute_event_fingerprint',
        'compute_sighting_fingerprint',
        '_upsert_event_in_store',
        'HEALTH_PARTIAL',
    ):
        if needle not in src:
            return _fail(f'foundation missing {needle!r}')
    if 'create_if_missing' in src:
        return _fail('load_store must not expose create_if_missing write path')
    if re.search(r'^def save_store\b', src, re.M):
        return _fail('public save_store must not exist')
    if 'def _save_store' not in src:
        return _fail('internal _save_store required')
    if 'validate_persisted_timestamp' not in src:
        return _fail('foundation missing validate_persisted_timestamp')
    sighting_body = src.split('def upsert_sighting', 1)[-1].split('def attach_sighting_to_event', 1)[0]
    if re.search(r'(?<!_)\bupsert_event\s*\(', sighting_body):
        return _fail('upsert_sighting must not call public upsert_event')

    for bad in (
        'import requests',
        'from requests',
        'urllib.request',
        'selenium',
        'playwright',
        'openai',
        'anthropic',
    ):
        if bad in src:
            return _fail(f'foundation must not include {bad!r}')

    validator_src = Path(__file__).read_text(encoding='utf-8')
    promote_needle = 'def ' + '_promote_build'
    write_needle = '.' + 'write_text('
    if promote_needle in validator_src or write_needle in validator_src:
        return _fail('52R-A1 validator must remain strictly read-only')

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.run(
        [sys.executable, '-u', str(PROJECT_ROOT / 'scripts/test_broker_discovery_foundation_52r_a1.py')],
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
        return _fail('focused 52R-A1 discovery test failed')
    missing = [m for m in REQUIRED_MARKERS if m not in out]
    if missing:
        return _fail(f'missing required markers: {missing}')

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

    print('ASTRAEDGE_PHASE_52R_A1_BROKER_DISCOVERY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
