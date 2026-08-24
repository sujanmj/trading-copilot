"""
AstraEdge 52R-C1A — verified news intelligence sidecar store.

Dormant persistence foundation. No production caller. No classifier.
Does not mutate the A1 discovery event schema or discovery store.
No network. No AI. No trading coupling.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.news.broker_discovery_foundation import (
    BrokerDiscoveryError,
    normalize_aware_datetime,
    normalize_url,
    require_event_fingerprint,
    require_external_id,
    require_query_limit,
    validate_persisted_timestamp,
)
from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')

INTELLIGENCE_SCHEMA_VERSION = '52R-C1A'
STORE_RELATIVE = 'verified_news_intelligence_store.json'
LOCK_RELATIVE = 'verified_news_intelligence_store.lock'
LOCK_ENV = 'VERIFIED_INTELLIGENCE_LOCK_PATH'

DEFAULT_DERIVATION_VERSION = '52R-C1A'
DEFAULT_TAXONOMY_VERSION = '52R-C1A'
DEFAULT_FACT_PARSER_VERSION = 'classification_only'

UPSERT_ALLOWED_INPUT_KEYS = frozenset({
    'source_event_id',
    'source_event_fingerprint',
    'source_canonical_headline',
    'source_verification_status',
    'source_primary_url',
    'source_event_updated_at',
    'classification',
    'classification_provenance',
    'facts',
    'fact_provenance',
    'derivation_version',
    'taxonomy_version',
    'fact_parser_version',
})

HEALTH_OK = 'OK'
HEALTH_MISSING = 'MISSING'
HEALTH_UNREADABLE = 'UNREADABLE'
HEALTH_MALFORMED = 'MALFORMED'
HEALTH_PARTIAL = 'PARTIAL'

PRIMARY_STATUS = 'PRIMARY_SOURCE_VERIFIED'

ALLOWED_CLASSIFICATIONS = frozenset({
    'BOARD_MEETING_INTIMATION',
    'INVESTOR_PRESENTATION',
    'PRESS_RELEASE',
    'OTHER',
})

ALLOWED_PROVENANCE = frozenset({
    'PARSED_CANONICAL_HEADLINE',
    'UNKNOWN',
    'SOURCE_METADATA_DIRECT',
    'PARSED_SOURCE_SUBJECT',
    'PARSED_BOUNDED_EXCERPT',
    'MISSING',
    'CONFLICT',
})

FORBIDDEN_PROVENANCE = frozenset({
    'AI_INFERRED', 'LLM', 'MODEL_GUESS', 'AI', 'GPT', 'CLAUDE', 'GEMINI', 'GROQ',
})

FORBIDDEN_RECORD_KEYS = frozenset({
    'article_body', 'full_article', 'html', 'raw_html',
    'cookies', 'auth_token', 'browser_state', 'session',
})

_RECORD_REQUIRED = (
    'intelligence_id',
    'source_event_id',
    'source_event_fingerprint',
    'source_canonical_headline',
    'source_verification_status',
    'source_primary_url',
    'source_event_updated_at',
    'classification',
    'facts',
    'classification_provenance',
    'fact_provenance',
    'derivation_version',
    'taxonomy_version',
    'fact_parser_version',
    'source_input_hash',
    'record_fingerprint',
    'derived_at',
    'schema_version',
)

_STORE_TOP_KEYS = frozenset({'schema_version', 'updated_at', 'records'})

_ID_NAMESPACE = uuid.UUID('c15a52c1-a000-4c1a-9e52-00000000c1a0')
_HASH_RE = re.compile(r'^[0-9a-f]{64}$')
_HTML_MARKUP_RE = re.compile(
    r'(?is)(?:<!DOCTYPE\s+html\b|</?\s*(?:html|script|style|div|p|span|a|br|table|tr|td|'
    r'th|body|head|meta|link|ul|ol|li|section|article|header|footer|nav|img|form|input|'
    r'button|h[1-6])\b[^>]*>|</?[A-Za-z][A-Za-z0-9]*\b[^>]*>)'
)
_WS_RE = re.compile(r'\s+')
_VERSION_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,62}$')
MAX_HEADLINE_LENGTH = 2000


class VerifiedIntelligenceError(ValueError):
    """Raised for invalid intelligence payloads or unhealthy store access."""


def _iso(dt: datetime) -> str:
    return dt.astimezone(IST).isoformat()


def _now_ist() -> datetime:
    return datetime.now(IST)


def _normalize_now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return _now_ist()
    try:
        return normalize_aware_datetime(now, field='now')
    except BrokerDiscoveryError as exc:
        raise VerifiedIntelligenceError(str(exc)) from exc


def _require_utf8_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise VerifiedIntelligenceError(f'{field} must be a string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise VerifiedIntelligenceError(f'{field} must be valid UTF-8 text') from exc
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise VerifiedIntelligenceError(f'{field} rejects control characters')
    return value


def _collapse_text(value: Any, *, field: str, allow_empty: bool = False) -> str:
    text = _require_utf8_text(value, field=field)
    text = _WS_RE.sub(' ', text.strip())
    if not text and not allow_empty:
        raise VerifiedIntelligenceError(f'{field} is required')
    return text


def _require_version(value: Any, *, field: str) -> str:
    text = _collapse_text(value, field=field)
    if not _VERSION_RE.fullmatch(text):
        raise VerifiedIntelligenceError(f'{field} is not a bounded version string')
    return text


def _require_classification(value: Any) -> str:
    token = _collapse_text(value, field='classification').upper().replace(' ', '_').replace('-', '_')
    if token in FORBIDDEN_PROVENANCE or token.startswith('AI_'):
        raise VerifiedIntelligenceError('classification rejects AI provenance tokens')
    if token not in ALLOWED_CLASSIFICATIONS:
        raise VerifiedIntelligenceError(f'unsupported classification: {value!r}')
    return token


def _require_provenance(value: Any, *, field: str = 'classification_provenance') -> str:
    token = _collapse_text(value, field=field).upper().replace(' ', '_').replace('-', '_')
    if token in FORBIDDEN_PROVENANCE or token.startswith('AI_'):
        raise VerifiedIntelligenceError(f'{field} rejects AI provenance')
    if token not in ALLOWED_PROVENANCE:
        raise VerifiedIntelligenceError(f'unsupported {field}: {value!r}')
    return token


def _require_headline(value: Any) -> str:
    text = _collapse_text(value, field='source_canonical_headline')
    if len(text) > MAX_HEADLINE_LENGTH:
        raise VerifiedIntelligenceError('source_canonical_headline exceeds bound')
    if _HTML_MARKUP_RE.search(text):
        raise VerifiedIntelligenceError('source_canonical_headline rejects markup')
    return text


def _require_primary_url(value: Any) -> str:
    try:
        url = normalize_url(value)
    except BrokerDiscoveryError as exc:
        raise VerifiedIntelligenceError(str(exc)) from exc
    if not url:
        raise VerifiedIntelligenceError('source_primary_url is required')
    return url


def _require_primary_status(value: Any) -> str:
    token = _collapse_text(value, field='source_verification_status').upper()
    if token != PRIMARY_STATUS:
        raise VerifiedIntelligenceError('source_verification_status must be PRIMARY_SOURCE_VERIFIED')
    return PRIMARY_STATUS


def _require_event_id(value: Any) -> str:
    try:
        return require_external_id(value, field='source_event_id')
    except BrokerDiscoveryError as exc:
        raise VerifiedIntelligenceError(str(exc)) from exc


def _require_event_fingerprint(value: Any) -> str:
    try:
        return require_event_fingerprint(value, field='source_event_fingerprint')
    except BrokerDiscoveryError as exc:
        raise VerifiedIntelligenceError(str(exc)) from exc


def _require_timestamp(value: Any, *, field: str) -> str:
    try:
        dt = normalize_aware_datetime(value, field=field)
        canonical = _iso(dt)
        validate_persisted_timestamp(canonical, field=field)
    except BrokerDiscoveryError as exc:
        raise VerifiedIntelligenceError(str(exc)) from exc
    return canonical


def _stable_hash(parts: list[str]) -> str:
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def compute_intelligence_id(
    *,
    source_event_id: str,
    derivation_version: str,
    taxonomy_version: str,
) -> str:
    key = f'c1a:{source_event_id}:{derivation_version}:{taxonomy_version}'
    return str(uuid.uuid5(_ID_NAMESPACE, key))


def compute_source_input_hash(
    *,
    source_event_id: str,
    source_event_fingerprint: str,
    source_canonical_headline: str,
    source_verification_status: str,
    source_primary_url: str,
) -> str:
    return _stable_hash([
        source_event_id,
        source_event_fingerprint,
        source_canonical_headline,
        source_verification_status,
        source_primary_url,
    ])


def compute_record_fingerprint(
    *,
    source_event_id: str,
    derivation_version: str,
    taxonomy_version: str,
    source_input_hash: str,
    classification: str,
    facts: dict[str, Any],
    classification_provenance: str,
    fact_provenance: list[Any],
    fact_parser_version: str,
) -> str:
    blob = _canonical_json({
        'source_event_id': source_event_id,
        'derivation_version': derivation_version,
        'taxonomy_version': taxonomy_version,
        'source_input_hash': source_input_hash,
        'classification': classification,
        'facts': facts,
        'classification_provenance': classification_provenance,
        'fact_provenance': fact_provenance,
        'fact_parser_version': fact_parser_version,
    })
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def store_path() -> Path:
    return get_data_path(STORE_RELATIVE)


def intelligence_lock_path() -> Path:
    override = os.environ.get(LOCK_ENV, '').strip()
    if override:
        return Path(override)
    return get_data_path(LOCK_RELATIVE)


class _IntelligenceLock:
    """C1A-only advisory lock. Never touches the discovery-store lock."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: Optional[int] = None
        self.stale_cleared = False

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        except OSError:
            return False
        try:
            if os.name == 'nt':
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.write(fd, b'\0')
                    os.fsync(fd)
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                os.close(fd)
            except OSError:
                pass
            return False
        self._fd = fd
        try:
            self._write_metadata()
        except OSError:
            self.release()
            return False
        return True

    def _write_metadata(self) -> None:
        if self._fd is None:
            raise OSError('intelligence lock is not held')
        payload = json.dumps({
            'pid': os.getpid(),
            'started_at': time.time(),
            'script': 'verified_intelligence_store',
        }, separators=(',', ':')).encode('utf-8')
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, payload)
        os.ftruncate(self._fd, len(payload))
        os.fsync(self._fd)

    def release(self) -> None:
        fd = self._fd
        self._fd = None
        if fd is None:
            return
        try:
            if os.name == 'nt':
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def _empty_store(*, now: Optional[datetime] = None) -> dict[str, Any]:
    return {
        'schema_version': INTELLIGENCE_SCHEMA_VERSION,
        'updated_at': _iso(now or _now_ist()),
        'records': [],
    }


def _reject_forbidden_fields(row: dict[str, Any]) -> Optional[str]:
    for key in FORBIDDEN_RECORD_KEYS:
        if key in row:
            return f'record retains forbidden key {key}'
    return None


def _validate_record(record: Any) -> Optional[str]:
    if not isinstance(record, dict):
        return 'record is not a dictionary'
    extra = set(record.keys()) - set(_RECORD_REQUIRED)
    if extra:
        return f'record has unknown fields: {sorted(extra)}'
    forbidden = _reject_forbidden_fields(record)
    if forbidden:
        return forbidden
    for field in _RECORD_REQUIRED:
        if field not in record:
            return f'record missing field {field}'
    if str(record.get('schema_version') or '') != INTELLIGENCE_SCHEMA_VERSION:
        return 'record schema_version invalid'
    facts = record.get('facts')
    if facts != {}:
        return 'C1A facts must be empty'
    provenance = record.get('fact_provenance')
    if provenance != []:
        return 'C1A fact_provenance must be empty'
    if not isinstance(facts, dict) or not isinstance(provenance, list):
        return 'facts/fact_provenance types invalid'
    try:
        eid = _require_event_id(record.get('source_event_id'))
        fp = _require_event_fingerprint(record.get('source_event_fingerprint'))
        headline = _require_headline(record.get('source_canonical_headline'))
        status = _require_primary_status(record.get('source_verification_status'))
        url = _require_primary_url(record.get('source_primary_url'))
        classification = _require_classification(record.get('classification'))
        class_prov = _require_provenance(record.get('classification_provenance'))
        derivation = _require_version(record.get('derivation_version'), field='derivation_version')
        taxonomy = _require_version(record.get('taxonomy_version'), field='taxonomy_version')
        parser = _require_version(record.get('fact_parser_version'), field='fact_parser_version')
        derived_at = str(record.get('derived_at') or '')
        validate_persisted_timestamp(derived_at, field='derived_at')
        updated_at = str(record.get('source_event_updated_at') or '')
        validate_persisted_timestamp(updated_at, field='source_event_updated_at')
    except (VerifiedIntelligenceError, BrokerDiscoveryError) as exc:
        return str(exc)
    expected_id = compute_intelligence_id(
        source_event_id=eid,
        derivation_version=derivation,
        taxonomy_version=taxonomy,
    )
    if record.get('intelligence_id') != expected_id:
        return 'intelligence_id incorrect'
    expected_input = compute_source_input_hash(
        source_event_id=eid,
        source_event_fingerprint=fp,
        source_canonical_headline=headline,
        source_verification_status=status,
        source_primary_url=url,
    )
    if record.get('source_input_hash') != expected_input or not _HASH_RE.fullmatch(str(record.get('source_input_hash') or '')):
        return 'source_input_hash incorrect'
    expected_fp = compute_record_fingerprint(
        source_event_id=eid,
        derivation_version=derivation,
        taxonomy_version=taxonomy,
        source_input_hash=expected_input,
        classification=classification,
        facts={},
        classification_provenance=class_prov,
        fact_provenance=[],
        fact_parser_version=parser,
    )
    if record.get('record_fingerprint') != expected_fp or not _HASH_RE.fullmatch(str(record.get('record_fingerprint') or '')):
        return 'record_fingerprint incorrect'
    return None


def _classify_store_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return HEALTH_MALFORMED
    if set(data.keys()) - _STORE_TOP_KEYS:
        return HEALTH_MALFORMED
    if 'schema_version' not in data or 'updated_at' not in data or 'records' not in data:
        return HEALTH_MALFORMED
    if data.get('schema_version') != INTELLIGENCE_SCHEMA_VERSION:
        return HEALTH_MALFORMED
    try:
        validate_persisted_timestamp(data.get('updated_at'), field='updated_at')
    except BrokerDiscoveryError:
        return HEALTH_MALFORMED
    records = data.get('records')
    if not isinstance(records, list):
        return HEALTH_MALFORMED
    seen: set[str] = set()
    for row in records:
        err = _validate_record(row)
        if err:
            return HEALTH_PARTIAL
        iid = str((row or {}).get('intelligence_id') or '')
        if not iid or iid in seen:
            return HEALTH_PARTIAL
        seen.add(iid)
    return HEALTH_OK


def load_store() -> tuple[dict[str, Any], str]:
    path = store_path()
    if not path.is_file():
        return _empty_store(), HEALTH_MISSING
    try:
        raw = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return _empty_store(), HEALTH_UNREADABLE
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _empty_store(), HEALTH_MALFORMED
    health = _classify_store_payload(data)
    if health == HEALTH_MALFORMED:
        return _empty_store(), HEALTH_MALFORMED
    if health == HEALTH_PARTIAL:
        return copy.deepcopy(data), HEALTH_PARTIAL
    return copy.deepcopy(data), HEALTH_OK


def _atomic_save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    encoded = text.encode('utf-8')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _save_store(store: dict[str, Any], *, now: datetime) -> None:
    payload = copy.deepcopy(store)
    payload['schema_version'] = INTELLIGENCE_SCHEMA_VERSION
    payload['updated_at'] = _iso(now)
    records = list(payload.get('records') or [])
    records.sort(key=lambda row: str(row.get('intelligence_id') or ''))
    payload['records'] = records
    health = _classify_store_payload(payload)
    if health != HEALTH_OK:
        raise VerifiedIntelligenceError(f'refusing to persist unhealthy intelligence store: {health}')
    _atomic_save(store_path(), payload)


def get_verified_intelligence_store_health() -> dict[str, Any]:
    path = store_path()
    exists = path.is_file()
    store, health = load_store()
    record_count = None
    available = False
    counts_unavailable = health in (HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL)
    if health == HEALTH_OK:
        available = True
        record_count = len(store.get('records') or [])
    elif health == HEALTH_MISSING:
        available = True
        record_count = 0
        counts_unavailable = False
    return {
        'health': health,
        'available': available,
        'exists': exists,
        'record_count': record_count,
        'counts_unavailable': counts_unavailable,
        'path': str(path),
    }


def build_verified_intelligence_record(
    *,
    source_event_id: Any,
    source_event_fingerprint: Any,
    source_canonical_headline: Any,
    source_verification_status: Any,
    source_primary_url: Any,
    classification: Any,
    classification_provenance: Any,
    source_event_updated_at: Any,
    facts: Any = None,
    fact_provenance: Any = None,
    derivation_version: Any = DEFAULT_DERIVATION_VERSION,
    taxonomy_version: Any = DEFAULT_TAXONOMY_VERSION,
    fact_parser_version: Any = DEFAULT_FACT_PARSER_VERSION,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    if facts is None:
        facts = {}
    if fact_provenance is None:
        fact_provenance = []
    if facts != {}:
        raise VerifiedIntelligenceError('C1A facts must be empty')
    if fact_provenance != []:
        raise VerifiedIntelligenceError('C1A fact_provenance must be empty')
    eid = _require_event_id(source_event_id)
    fp = _require_event_fingerprint(source_event_fingerprint)
    headline = _require_headline(source_canonical_headline)
    status = _require_primary_status(source_verification_status)
    url = _require_primary_url(source_primary_url)
    klass = _require_classification(classification)
    class_prov = _require_provenance(classification_provenance)
    derivation = _require_version(derivation_version, field='derivation_version')
    taxonomy = _require_version(taxonomy_version, field='taxonomy_version')
    parser = _require_version(fact_parser_version, field='fact_parser_version')
    updated_at = _require_timestamp(source_event_updated_at, field='source_event_updated_at')
    now_dt = _normalize_now(now)
    source_input_hash = compute_source_input_hash(
        source_event_id=eid,
        source_event_fingerprint=fp,
        source_canonical_headline=headline,
        source_verification_status=status,
        source_primary_url=url,
    )
    record_fp = compute_record_fingerprint(
        source_event_id=eid,
        derivation_version=derivation,
        taxonomy_version=taxonomy,
        source_input_hash=source_input_hash,
        classification=klass,
        facts={},
        classification_provenance=class_prov,
        fact_provenance=[],
        fact_parser_version=parser,
    )
    intelligence_id = compute_intelligence_id(
        source_event_id=eid,
        derivation_version=derivation,
        taxonomy_version=taxonomy,
    )
    record = {
        'intelligence_id': intelligence_id,
        'source_event_id': eid,
        'source_event_fingerprint': fp,
        'source_canonical_headline': headline,
        'source_verification_status': status,
        'source_primary_url': url,
        'source_event_updated_at': updated_at,
        'classification': klass,
        'facts': {},
        'classification_provenance': class_prov,
        'fact_provenance': [],
        'derivation_version': derivation,
        'taxonomy_version': taxonomy,
        'fact_parser_version': parser,
        'source_input_hash': source_input_hash,
        'record_fingerprint': record_fp,
        'derived_at': _iso(now_dt),
        'schema_version': INTELLIGENCE_SCHEMA_VERSION,
    }
    err = _validate_record(record)
    if err:
        raise VerifiedIntelligenceError(err)
    return record


def _semantic_core(record: dict[str, Any]) -> dict[str, Any]:
    return {
        'intelligence_id': record.get('intelligence_id'),
        'source_event_id': record.get('source_event_id'),
        'source_event_fingerprint': record.get('source_event_fingerprint'),
        'source_canonical_headline': record.get('source_canonical_headline'),
        'source_verification_status': record.get('source_verification_status'),
        'source_primary_url': record.get('source_primary_url'),
        'classification': record.get('classification'),
        'facts': record.get('facts'),
        'classification_provenance': record.get('classification_provenance'),
        'fact_provenance': record.get('fact_provenance'),
        'derivation_version': record.get('derivation_version'),
        'taxonomy_version': record.get('taxonomy_version'),
        'fact_parser_version': record.get('fact_parser_version'),
        'source_input_hash': record.get('source_input_hash'),
        'record_fingerprint': record.get('record_fingerprint'),
        'schema_version': record.get('schema_version'),
    }


def _empty_upsert(**overrides: Any) -> dict[str, Any]:
    result = {
        'ok': False,
        'inserted': False,
        'idempotent': False,
        'reason': '',
        'intelligence_id': '',
        'record': None,
        'lock_contended': False,
        'store_health': None,
    }
    result.update(overrides)
    return result


def upsert_verified_intelligence_record(
    payload: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise VerifiedIntelligenceError('payload must be a dict')
    extra = sorted(str(key) for key in payload.keys() if key not in UPSERT_ALLOWED_INPUT_KEYS)
    if extra:
        raise VerifiedIntelligenceError(
            f'upsert payload has unsupported fields: {extra}'
        )
    built = build_verified_intelligence_record(
        source_event_id=payload.get('source_event_id'),
        source_event_fingerprint=payload.get('source_event_fingerprint'),
        source_canonical_headline=payload.get('source_canonical_headline'),
        source_verification_status=payload.get('source_verification_status'),
        source_primary_url=payload.get('source_primary_url'),
        classification=payload.get('classification'),
        classification_provenance=payload.get('classification_provenance'),
        source_event_updated_at=payload.get('source_event_updated_at'),
        facts=payload.get('facts', {}),
        fact_provenance=payload.get('fact_provenance', []),
        derivation_version=payload.get('derivation_version', DEFAULT_DERIVATION_VERSION),
        taxonomy_version=payload.get('taxonomy_version', DEFAULT_TAXONOMY_VERSION),
        fact_parser_version=payload.get('fact_parser_version', DEFAULT_FACT_PARSER_VERSION),
        now=now,
    )
    now_dt = _normalize_now(now)
    lock = _IntelligenceLock(intelligence_lock_path())
    acquired = False
    try:
        acquired = lock.try_acquire()
        if not acquired:
            return _empty_upsert(
                reason='lock_contended',
                lock_contended=True,
                intelligence_id=built['intelligence_id'],
            )
        store, health = load_store()
        if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL):
            raise VerifiedIntelligenceError(f'intelligence store unhealthy: {health}')
        if health == HEALTH_MISSING:
            store = _empty_store(now=now_dt)
        records = list(store.get('records') or [])
        existing = None
        for row in records:
            if str(row.get('intelligence_id') or '') == built['intelligence_id']:
                existing = row
                break
        if existing is not None:
            same_input = existing.get('source_input_hash') == built['source_input_hash']
            same_output = _semantic_core(existing) == _semantic_core(built)
            if same_input and same_output:
                return _empty_upsert(
                    ok=True,
                    inserted=False,
                    idempotent=True,
                    reason='',
                    intelligence_id=existing['intelligence_id'],
                    record=copy.deepcopy(existing),
                    store_health=HEALTH_OK if health != HEALTH_MISSING else HEALTH_OK,
                )
            return _empty_upsert(
                reason='version_conflict',
                intelligence_id=built['intelligence_id'],
                record=copy.deepcopy(existing),
                store_health=health if health != HEALTH_MISSING else HEALTH_OK,
            )
        records.append(copy.deepcopy(built))
        store['records'] = records
        _save_store(store, now=now_dt)
        return _empty_upsert(
            ok=True,
            inserted=True,
            idempotent=False,
            intelligence_id=built['intelligence_id'],
            record=copy.deepcopy(built),
            store_health=HEALTH_OK,
        )
    finally:
        if acquired:
            lock.release()


def find_verified_intelligence_for_event(source_event_id: Any) -> list[dict[str, Any]]:
    eid = _require_event_id(source_event_id)
    store, health = load_store()
    if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL):
        raise VerifiedIntelligenceError(f'intelligence store unhealthy: {health}')
    if health == HEALTH_MISSING:
        return []
    rows = [
        copy.deepcopy(row)
        for row in (store.get('records') or [])
        if str(row.get('source_event_id') or '') == eid
    ]
    rows.sort(key=lambda row: (
        str(row.get('derivation_version') or ''),
        str(row.get('taxonomy_version') or ''),
        str(row.get('intelligence_id') or ''),
    ))
    return rows


def find_recent_verified_intelligence(*, limit: int = 50) -> list[dict[str, Any]]:
    try:
        lim = require_query_limit(limit, field='limit')
    except BrokerDiscoveryError as exc:
        raise VerifiedIntelligenceError(str(exc)) from exc
    store, health = load_store()
    if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL):
        raise VerifiedIntelligenceError(f'intelligence store unhealthy: {health}')
    if health == HEALTH_MISSING:
        return []
    rows = [copy.deepcopy(row) for row in (store.get('records') or [])]
    rows.sort(key=lambda row: str(row.get('intelligence_id') or ''))
    rows.sort(key=lambda row: str(row.get('derived_at') or ''), reverse=True)
    return rows[:lim]
