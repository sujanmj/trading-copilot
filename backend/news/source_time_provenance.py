"""
AstraEdge 52R-D2P — source timestamp provenance sidecar.

Write-once sighting_id binding for feed-supplied source times.
No network. No AI. No age/freshness projection. No A1/C1A/C1B/D1 mutation.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.news.broker_discovery_foundation import (
    BrokerDiscoveryError,
    require_external_id,
    validate_persisted_timestamp,
)
from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')

SCHEMA_VERSION = '52R-D2P'
SIDECAR_RELATIVE = 'news_source_time_provenance.json'
LOCK_RELATIVE = 'news_source_time_provenance.lock'
SIDECAR_ENV = 'NEWS_SOURCE_TIME_PROVENANCE_PATH'
LOCK_ENV = 'NEWS_SOURCE_TIME_PROVENANCE_LOCK_PATH'

HEALTH_MISSING = 'MISSING'
HEALTH_OK = 'OK'
HEALTH_UNREADABLE = 'UNREADABLE'
HEALTH_MALFORMED = 'MALFORMED'

SOURCE_TIME_PRESENT = 'SOURCE_TIME_PRESENT'
SOURCE_TIME_AMBIGUOUS = 'SOURCE_TIME_AMBIGUOUS'

BASIS_PUBLISHED_PARSED = 'PUBLISHED_PARSED'
BASIS_UPDATED_PARSED = 'UPDATED_PARSED'
ALLOWED_BASIS = frozenset({BASIS_PUBLISHED_PARSED, BASIS_UPDATED_PARSED})

TIMEZONE_ASSUMPTION_UTC = 'UTC'
ALLOWED_TIMEZONES = frozenset({TIMEZONE_ASSUMPTION_UTC})

STATUS_INSERTED = 'INSERTED'
STATUS_IDEMPOTENT = 'IDEMPOTENT'
STATUS_CONFLICT = 'CONFLICT'
STATUS_LOCK_CONTENDED = 'LOCK_CONTENDED'
STATUS_STORE_UNHEALTHY = 'STORE_UNHEALTHY'
STATUS_FAILED = 'FAILED'

TOP_KEYS = ('schema_version', 'updated_at', 'entries')
TOP_KEY_SET = frozenset(TOP_KEYS)
ENTRY_KEYS = (
    'sighting_id',
    'source_time_provenance',
    'source_time_basis',
    'source_time_value',
    'timezone_assumption',
    'recorded_at',
    'schema_version',
)
ENTRY_KEY_SET = frozenset(ENTRY_KEYS)

LOOKUP_AMBIGUOUS = SOURCE_TIME_AMBIGUOUS
LOOKUP_PRESENT = SOURCE_TIME_PRESENT
LOOKUP_UNREADABLE = 'SIDECAR_UNREADABLE'
LOOKUP_MALFORMED = 'SIDECAR_MALFORMED'


def sidecar_path() -> Path:
    override = os.environ.get(SIDECAR_ENV, '').strip()
    if override:
        return Path(override)
    return get_data_path(SIDECAR_RELATIVE)


def provenance_lock_path() -> Path:
    override = os.environ.get(LOCK_ENV, '').strip()
    if override:
        return Path(override)
    return get_data_path(LOCK_RELATIVE)


def _now_iso(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    text = current.astimezone(IST).isoformat()
    return validate_persisted_timestamp(text, field='now')


class _ProvenanceLock:
    """Dedicated advisory lock. Never shares A1, A2, C1A, or D1 locks."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: Optional[int] = None

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
        return True

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


def _atomic_save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    encoded = text.encode('utf-8')
    fd = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if getattr(os, 'O_BINARY', 0):
        flags |= os.O_BINARY
    try:
        fd = os.open(str(tmp), flags, 0o644)
        view = memoryview(encoded)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise OSError('short write')
            offset += written
        os.fsync(fd)
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        raise
    finally:
        if fd is not None:
            os.close(fd)
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        raise


def _empty_document(*, updated_at: str) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'updated_at': updated_at,
        'entries': {},
    }


def _validate_entry(key: str, entry: Any) -> Optional[str]:
    if not isinstance(entry, dict):
        return 'entry value is not a dictionary'
    extra = set(entry.keys()) - ENTRY_KEY_SET
    if extra:
        return f'entry has unknown fields: {sorted(extra)}'
    for field in ENTRY_KEYS:
        if field not in entry:
            return f'entry missing field {field}'
    if str(entry.get('schema_version') or '') != SCHEMA_VERSION:
        return 'entry schema_version invalid'
    try:
        sid = require_external_id(entry.get('sighting_id'), field='sighting_id')
    except BrokerDiscoveryError:
        return 'entry sighting_id invalid'
    if sid != str(key):
        return 'entry key/sighting_id mismatch'
    if entry.get('source_time_provenance') != SOURCE_TIME_PRESENT:
        return 'entry source_time_provenance invalid'
    if entry.get('source_time_basis') not in ALLOWED_BASIS:
        return 'entry source_time_basis invalid'
    if entry.get('timezone_assumption') not in ALLOWED_TIMEZONES:
        return 'entry timezone_assumption invalid'
    try:
        validate_persisted_timestamp(entry.get('source_time_value'), field='source_time_value')
    except BrokerDiscoveryError:
        return 'entry source_time_value invalid'
    try:
        validate_persisted_timestamp(entry.get('recorded_at'), field='recorded_at')
    except BrokerDiscoveryError:
        return 'entry recorded_at invalid'
    return None


def _classify_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return HEALTH_MALFORMED
    extra = set(data.keys()) - TOP_KEY_SET
    if extra:
        return HEALTH_MALFORMED
    for field in TOP_KEYS:
        if field not in data:
            return HEALTH_MALFORMED
    if data.get('schema_version') != SCHEMA_VERSION:
        return HEALTH_MALFORMED
    try:
        validate_persisted_timestamp(data.get('updated_at'), field='updated_at')
    except BrokerDiscoveryError:
        return HEALTH_MALFORMED
    entries = data.get('entries')
    if not isinstance(entries, dict):
        return HEALTH_MALFORMED
    for key, entry in entries.items():
        if not isinstance(key, str) or not key:
            return HEALTH_MALFORMED
        if _validate_entry(key, entry) is not None:
            return HEALTH_MALFORMED
    return HEALTH_OK


def load_source_time_provenance() -> tuple[Optional[dict[str, Any]], str]:
    """Read-only load. Never creates a sidecar file."""
    path = sidecar_path()
    if not path.is_file():
        return None, HEALTH_MISSING
    try:
        raw = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None, HEALTH_UNREADABLE
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, HEALTH_MALFORMED
    health = _classify_payload(data)
    if health != HEALTH_OK:
        return None, health
    return copy.deepcopy(data), HEALTH_OK


def get_source_time_provenance_health() -> dict[str, Any]:
    path = sidecar_path()
    _payload, health = load_source_time_provenance()
    return {
        'health': health,
        'path': str(path),
        'exists': path.is_file(),
        'schema_version': SCHEMA_VERSION,
        'available': health in (HEALTH_OK, HEALTH_MISSING),
    }


def lookup_source_time_provenance(sighting_id: str) -> dict[str, Any]:
    """
    Resolve persisted provenance for one sighting_id.

    Missing sidecar or missing entry => SOURCE_TIME_AMBIGUOUS.
    Unreadable/malformed sidecar => fail closed, no A1 parseability fallback.
    """
    try:
        sid = require_external_id(sighting_id, field='sighting_id')
    except BrokerDiscoveryError:
        return {
            'health': HEALTH_OK,
            'provenance': SOURCE_TIME_AMBIGUOUS,
            'lookup': LOOKUP_AMBIGUOUS,
            'entry': None,
            'reason': 'invalid_sighting_id',
        }
    payload, health = load_source_time_provenance()
    if health == HEALTH_MISSING:
        return {
            'health': health,
            'provenance': SOURCE_TIME_AMBIGUOUS,
            'lookup': LOOKUP_AMBIGUOUS,
            'entry': None,
            'reason': 'sidecar_missing',
        }
    if health == HEALTH_UNREADABLE:
        return {
            'health': health,
            'provenance': None,
            'lookup': LOOKUP_UNREADABLE,
            'entry': None,
            'reason': 'sidecar_unreadable',
        }
    if health != HEALTH_OK:
        return {
            'health': health,
            'provenance': None,
            'lookup': LOOKUP_MALFORMED,
            'entry': None,
            'reason': 'sidecar_malformed',
        }
    entry = (payload or {}).get('entries', {}).get(sid)
    if not isinstance(entry, dict):
        return {
            'health': health,
            'provenance': SOURCE_TIME_AMBIGUOUS,
            'lookup': LOOKUP_AMBIGUOUS,
            'entry': None,
            'reason': 'entry_missing',
        }
    return {
        'health': health,
        'provenance': SOURCE_TIME_PRESENT,
        'lookup': LOOKUP_PRESENT,
        'entry': copy.deepcopy(entry),
        'reason': None,
    }


def _write_result(status: str, **extra: Any) -> dict[str, Any]:
    ok = status in (STATUS_INSERTED, STATUS_IDEMPOTENT)
    result = {
        'ok': ok,
        'status': status,
        'inserted': status == STATUS_INSERTED,
        'idempotent': status == STATUS_IDEMPOTENT,
        'conflict': status == STATUS_CONFLICT,
    }
    result.update(extra)
    return result


def _incoming_entry(
    *,
    sighting_id: str,
    source_time_value: Any,
    source_time_basis: Any,
    timezone_assumption: Any,
    source_time_provenance: Any,
    recorded_at: str,
) -> dict[str, Any]:
    sid = require_external_id(sighting_id, field='sighting_id')
    if source_time_provenance != SOURCE_TIME_PRESENT:
        raise BrokerDiscoveryError('source_time_provenance must be SOURCE_TIME_PRESENT')
    if source_time_basis not in ALLOWED_BASIS:
        raise BrokerDiscoveryError('source_time_basis invalid')
    if timezone_assumption not in ALLOWED_TIMEZONES:
        raise BrokerDiscoveryError('timezone_assumption invalid')
    value = validate_persisted_timestamp(source_time_value, field='source_time_value')
    return {
        'sighting_id': sid,
        'source_time_provenance': SOURCE_TIME_PRESENT,
        'source_time_basis': source_time_basis,
        'source_time_value': value,
        'timezone_assumption': timezone_assumption,
        'recorded_at': recorded_at,
        'schema_version': SCHEMA_VERSION,
    }


def _identity_tuple(entry: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(entry.get('sighting_id') or ''),
        str(entry.get('source_time_provenance') or ''),
        str(entry.get('source_time_basis') or ''),
        str(entry.get('source_time_value') or ''),
        str(entry.get('timezone_assumption') or ''),
    )


def record_source_time_provenance(
    *,
    sighting_id: Any,
    source_time_value: Any,
    source_time_basis: Any,
    timezone_assumption: Any = TIMEZONE_ASSUMPTION_UTC,
    source_time_provenance: Any = SOURCE_TIME_PRESENT,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Write-once provenance for a sighting_id bound to exact canonical IST time.

    Exact identity match is a true no-op (zero sidecar bytes changed).
    """
    try:
        recorded_at = _now_iso(now)
        incoming = _incoming_entry(
            sighting_id=sighting_id,
            source_time_value=source_time_value,
            source_time_basis=source_time_basis,
            timezone_assumption=timezone_assumption,
            source_time_provenance=source_time_provenance,
            recorded_at=recorded_at,
        )
    except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError):
        return _write_result(STATUS_FAILED, reason='invalid_input')

    lock = _ProvenanceLock(provenance_lock_path())
    if not lock.try_acquire():
        return _write_result(STATUS_LOCK_CONTENDED)
    try:
        payload, health = load_source_time_provenance()
        if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED):
            return _write_result(STATUS_STORE_UNHEALTHY, health=health)
        if health == HEALTH_MISSING:
            document = _empty_document(updated_at=recorded_at)
        elif health == HEALTH_OK and payload is not None:
            document = payload
        else:
            return _write_result(STATUS_STORE_UNHEALTHY, health=health)

        existing = (document.get('entries') or {}).get(incoming['sighting_id'])
        if isinstance(existing, dict):
            if _identity_tuple(existing) == _identity_tuple(incoming):
                return _write_result(
                    STATUS_IDEMPOTENT,
                    sighting_id=incoming['sighting_id'],
                    entry=copy.deepcopy(existing),
                )
            return _write_result(
                STATUS_CONFLICT,
                sighting_id=incoming['sighting_id'],
                entry=copy.deepcopy(existing),
            )

        entries = dict(document.get('entries') or {})
        entries[incoming['sighting_id']] = copy.deepcopy(incoming)
        document['entries'] = entries
        document['schema_version'] = SCHEMA_VERSION
        document['updated_at'] = recorded_at
        if _classify_payload(document) != HEALTH_OK:
            return _write_result(STATUS_FAILED, reason='refusing_unhealthy_write')
        _atomic_save(sidecar_path(), document)
        return _write_result(
            STATUS_INSERTED,
            sighting_id=incoming['sighting_id'],
            entry=copy.deepcopy(incoming),
        )
    except (OSError, TypeError, ValueError, UnicodeError, BrokerDiscoveryError):
        return _write_result(STATUS_FAILED, reason='write_exception')
    finally:
        lock.release()
