"""
AstraEdge 52R-D1 — news pipeline reliability sidecar.

Restart-safe RSS outcome + attempt/completed-run lifecycle.
No network. No AI. No trading guards. No A1/C1A mutation.
Event-age projection is deferred to 52R-D2.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.utils.market_hours import (
    classify_source_freshness,
    get_collection_profile,
    get_market_period,
    get_watchdog_config,
)

IST = ZoneInfo('Asia/Kolkata')
IST_OFFSET = timedelta(hours=5, minutes=30)

SCHEMA_VERSION = '52R-D1'
SIDECAR_RELATIVE = 'news_pipeline_reliability.json'
LOCK_RELATIVE = 'news_pipeline_reliability.lock'
LOCK_ENV = 'NEWS_PIPELINE_RELIABILITY_LOCK_PATH'
SIDECAR_ENV = 'NEWS_PIPELINE_RELIABILITY_PATH'
DIAGNOSTIC_LIMIT = 200

HEALTH_MISSING = 'MISSING'
HEALTH_OK = 'OK'
HEALTH_UNREADABLE = 'UNREADABLE'
HEALTH_MALFORMED = 'MALFORMED'

RUN_IN_PROGRESS = 'IN_PROGRESS'
RUN_FINALIZED = 'FINALIZED'
RUN_STATES = frozenset({RUN_IN_PROGRESS, RUN_FINALIZED})

RSS_ALL_CURRENT = 'RSS_ALL_CURRENT'
RSS_ZERO_RESULT = 'RSS_ZERO_RESULT'
RSS_MIXED_CURRENT_MISSING = 'RSS_MIXED_CURRENT_MISSING'
RSS_PARTIAL = 'RSS_PARTIAL'
RSS_PARTIAL_ERRORS = 'RSS_PARTIAL_ERRORS'
RSS_ALL_FAILED = 'RSS_ALL_FAILED'
RSS_NO_PROVIDERS = 'RSS_NO_PROVIDERS'
RSS_STEP1_EXCEPTION = 'RSS_STEP1_EXCEPTION'
RSS_OUTCOMES = frozenset({
    RSS_ALL_CURRENT,
    RSS_ZERO_RESULT,
    RSS_MIXED_CURRENT_MISSING,
    RSS_PARTIAL,
    RSS_PARTIAL_ERRORS,
    RSS_ALL_FAILED,
    RSS_NO_PROVIDERS,
    RSS_STEP1_EXCEPTION,
})
RSS_SUCCESS_OUTCOMES = frozenset({
    RSS_ALL_CURRENT,
    RSS_ZERO_RESULT,
    RSS_MIXED_CURRENT_MISSING,
})
SUCCESS_CLOCK_OUTCOMES = frozenset({
    RSS_ALL_CURRENT,
    RSS_ZERO_RESULT,
    RSS_MIXED_CURRENT_MISSING,
    RSS_PARTIAL_ERRORS,
})
FAILURE_CLOCK_OUTCOMES = frozenset({
    RSS_ALL_FAILED,
    RSS_NO_PROVIDERS,
    RSS_STEP1_EXCEPTION,
})

STORE_HEALTH_VALUES = frozenset({
    'OK', 'MISSING', 'UNREADABLE', 'MALFORMED', 'PARTIAL',
})

FRESHNESS_MISSING = 'MISSING'
FRESHNESS_CURRENT = 'CURRENT'
FRESHNESS_STALE = 'STALE'
FRESHNESS_IDLE = 'IDLE'

HEALTH_NONE = 'NONE'
HEALTH_SUCCESS = 'SUCCESS'
HEALTH_SUCCESS_WITH_COMPONENT_FAILURE = 'SUCCESS_WITH_COMPONENT_FAILURE'
HEALTH_PARTIAL = 'PARTIAL'
HEALTH_FAILED = 'FAILED'

SCHEDULER_UNKNOWN = 'SCHEDULER_UNKNOWN'
SCHEDULER_RUNNING = 'SCHEDULER_RUNNING'
SCHEDULER_STALE = 'SCHEDULER_STALE'

STATUS_WRITTEN = 'WRITTEN'
STATUS_SKIPPED = 'SKIPPED'
STATUS_IDEMPOTENT = 'IDEMPOTENT'
STATUS_LOCK_CONTENDED = 'LOCK_CONTENDED'
STATUS_UNREADABLE = 'UNREADABLE'
STATUS_MALFORMED = 'MALFORMED'
STATUS_REFUSED = 'REFUSED'

SCHEMA_KEYS = (
    'schema_version',
    'updated_at',
    'run_state',
    'run_started_ns',
    'last_attempt_at',
    'last_completed_run_started_ns',
    'last_success_at',
    'last_failure_at',
    'last_error',
    'last_run_ok',
    'rss_ok',
    'rss_outcome',
    'rss_zero_result_ambiguous',
    'rss_error_count',
    'items_found',
    'sources_checked',
    'feeds_ok',
    'feeds_failed',
    'provider_current_count',
    'provider_stale_count',
    'provider_missing_count',
    'a2_isolated_exception',
    'a2_lock_contended',
    'a2_store_unhealthy',
    'b2_isolated_exception',
    'c1b_isolated_exception',
    'discovery_store_health',
    'intelligence_store_health',
    'primary_verification_ok',
    'primary_verification_failed',
    'classification_ok',
    'classification_failed',
)
SCHEMA_KEY_SET = frozenset(SCHEMA_KEYS)

COMPLETED_RESULT_KEYS = (
    'last_error',
    'last_run_ok',
    'rss_ok',
    'rss_outcome',
    'rss_zero_result_ambiguous',
    'rss_error_count',
    'items_found',
    'sources_checked',
    'feeds_ok',
    'feeds_failed',
    'provider_current_count',
    'provider_stale_count',
    'provider_missing_count',
    'a2_isolated_exception',
    'a2_lock_contended',
    'a2_store_unhealthy',
    'b2_isolated_exception',
    'c1b_isolated_exception',
    'discovery_store_health',
    'intelligence_store_health',
    'primary_verification_ok',
    'primary_verification_failed',
    'classification_ok',
    'classification_failed',
)

FRESHNESS_FROM_CLASSIFY = {
    'missing': FRESHNESS_MISSING,
    'ok': FRESHNESS_CURRENT,
    'stale': FRESHNESS_STALE,
    'idle': FRESHNESS_IDLE,
}


def sidecar_path() -> Path:
    override = os.environ.get(SIDECAR_ENV, '').strip()
    if override:
        return Path(override)
    return get_data_path(SIDECAR_RELATIVE)


def reliability_lock_path() -> Path:
    override = os.environ.get(LOCK_ENV, '').strip()
    if override:
        return Path(override)
    return get_data_path(LOCK_RELATIVE)


def _iso_from_ns(run_started_ns: int) -> str:
    dt = datetime.fromtimestamp(run_started_ns / 1_000_000_000, tz=IST)
    return dt.isoformat()


def _now_iso(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    return current.astimezone(IST).isoformat()


def _nonneg_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _is_canonical_ist_timestamp(value: Any) -> bool:
    """Strict persisted D1 timestamp: exact writer isoformat, no strip/canonicalize."""
    if not isinstance(value, str) or value == '':
        return False
    if value.endswith('Z') or value.endswith('z'):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    if parsed.utcoffset() != IST_OFFSET:
        return False
    canonical = parsed.astimezone(IST).isoformat()
    return value == canonical


def _parse_iso(value: Any) -> Optional[datetime]:
    """Runtime parse of already-validated (or equivalently IST-aware) timestamps."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(IST)


def _bound_text(value: str) -> str:
    text = value.replace('\n', ' ').replace('\r', ' ')
    if len(text) <= DIAGNOSTIC_LIMIT:
        return text
    return text[:DIAGNOSTIC_LIMIT]


def _join_errors(errors: Any, prefix: str = '') -> str:
    parts: list[str] = []
    if isinstance(errors, list):
        for item in errors[:12]:
            parts.append(str(item).replace('\n', ' ')[:80])
    joined = ';'.join(parts)
    if prefix:
        return _bound_text(prefix + joined)
    return _bound_text(joined)


class _ReliabilityLock:
    """Dedicated advisory lock. Never shares A1, C1A, or scheduler locks."""

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


def _empty_completed_fields() -> dict[str, Any]:
    return {
        'last_completed_run_started_ns': None,
        'last_success_at': None,
        'last_failure_at': None,
        'last_error': None,
        'last_run_ok': None,
        'rss_ok': None,
        'rss_outcome': None,
        'rss_zero_result_ambiguous': None,
        'rss_error_count': None,
        'items_found': None,
        'sources_checked': None,
        'feeds_ok': None,
        'feeds_failed': None,
        'provider_current_count': None,
        'provider_stale_count': None,
        'provider_missing_count': None,
        'a2_isolated_exception': None,
        'a2_lock_contended': None,
        'a2_store_unhealthy': None,
        'b2_isolated_exception': None,
        'c1b_isolated_exception': None,
        'discovery_store_health': None,
        'intelligence_store_health': None,
        'primary_verification_ok': None,
        'primary_verification_failed': None,
        'classification_ok': None,
        'classification_failed': None,
    }


def _first_attempt_document(run_started_ns: int, *, attempt_at: str, updated_at: str) -> dict[str, Any]:
    payload = {
        'schema_version': SCHEMA_VERSION,
        'updated_at': updated_at,
        'run_state': RUN_IN_PROGRESS,
        'run_started_ns': run_started_ns,
        'last_attempt_at': attempt_at,
    }
    payload.update(_empty_completed_fields())
    return payload


def _ordered(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in SCHEMA_KEYS}


def _completed_run_stamp(completed_ns: int) -> str:
    return _iso_from_ns(completed_ns)


def _outcome_semantics_ok(data: dict[str, Any]) -> bool:
    outcome = data.get('rss_outcome')
    rss_ok = data.get('rss_ok')
    last_run_ok = data.get('last_run_ok')
    ambiguous = data.get('rss_zero_result_ambiguous')
    if outcome in RSS_SUCCESS_OUTCOMES and rss_ok is not True:
        return False
    if outcome in (
        RSS_PARTIAL_ERRORS,
        RSS_PARTIAL,
        RSS_ALL_FAILED,
        RSS_NO_PROVIDERS,
        RSS_STEP1_EXCEPTION,
    ) and rss_ok is not False:
        return False
    if last_run_ok is True and rss_ok is not True:
        return False
    if rss_ok is False and last_run_ok is True:
        return False
    if outcome == RSS_ZERO_RESULT and ambiguous is not True:
        return False
    if outcome != RSS_ZERO_RESULT and ambiguous is not False:
        return False

    n = data.get('sources_checked')
    items = data.get('items_found')
    current = data.get('provider_current_count')
    stale = data.get('provider_stale_count')
    missing = data.get('provider_missing_count')
    errors = data.get('rss_error_count')
    last_error = data.get('last_error')

    if outcome == RSS_STEP1_EXCEPTION:
        if rss_ok is not False or last_run_ok is not False:
            return False
        if not isinstance(last_error, str) or not last_error:
            return False
        fabricated = (
            'sources_checked',
            'items_found',
            'rss_error_count',
            'feeds_ok',
            'feeds_failed',
            'provider_current_count',
            'provider_stale_count',
            'provider_missing_count',
        )
        return all(data.get(key) is None for key in fabricated)

    if outcome == RSS_NO_PROVIDERS:
        return n == 0 and current == 0 and stale == 0 and missing == 0 and rss_ok is False

    if outcome == RSS_ALL_CURRENT:
        return (
            isinstance(n, int)
            and n > 0
            and isinstance(items, int)
            and items > 0
            and current == n
            and stale == 0
            and missing == 0
            and errors == 0
            and rss_ok is True
        )

    if outcome == RSS_ZERO_RESULT:
        return (
            isinstance(n, int)
            and n > 0
            and items == 0
            and current == 0
            and stale == 0
            and missing == n
            and errors == 0
            and rss_ok is True
        )

    if outcome == RSS_MIXED_CURRENT_MISSING:
        return (
            isinstance(n, int)
            and n > 0
            and isinstance(items, int)
            and items > 0
            and isinstance(current, int)
            and current > 0
            and isinstance(missing, int)
            and missing > 0
            and stale == 0
            and current + missing == n
            and errors == 0
            and rss_ok is True
        )

    if outcome == RSS_ALL_FAILED:
        return (
            isinstance(n, int)
            and n > 0
            and items == 0
            and current == 0
            and stale == n
            and missing == 0
            and rss_ok is False
        )

    if outcome == RSS_PARTIAL_ERRORS:
        return (
            isinstance(n, int)
            and n > 0
            and isinstance(items, int)
            and items > 0
            and stale == 0
            and isinstance(errors, int)
            and errors > 0
            and rss_ok is False
        )

    if outcome == RSS_PARTIAL:
        return rss_ok is False and last_run_ok is not True and ambiguous is False

    return False


def _history_clocks_ok(data: dict[str, Any], completed_ns: int) -> bool:
    outcome = data.get('rss_outcome')
    run_stamp = _completed_run_stamp(completed_ns)
    if outcome in SUCCESS_CLOCK_OUTCOMES:
        if data.get('last_success_at') != run_stamp:
            return False
    if outcome in FAILURE_CLOCK_OUTCOMES:
        if data.get('last_failure_at') != run_stamp:
            return False
    return True


def _classify_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return HEALTH_MALFORMED
    if set(data.keys()) != SCHEMA_KEY_SET:
        return HEALTH_MALFORMED
    if data.get('schema_version') != SCHEMA_VERSION:
        return HEALTH_MALFORMED
    if not _is_canonical_ist_timestamp(data.get('updated_at')):
        return HEALTH_MALFORMED
    if data.get('run_state') not in RUN_STATES:
        return HEALTH_MALFORMED
    run_ns = _nonneg_int(data.get('run_started_ns'))
    if run_ns is None:
        return HEALTH_MALFORMED
    if not _is_canonical_ist_timestamp(data.get('last_attempt_at')):
        return HEALTH_MALFORMED
    completed_ns = data.get('last_completed_run_started_ns')
    if completed_ns is not None and _nonneg_int(completed_ns) is None:
        return HEALTH_MALFORMED
    if data.get('run_state') == RUN_FINALIZED:
        if completed_ns is None or int(completed_ns) != run_ns:
            return HEALTH_MALFORMED
    else:
        if completed_ns is not None:
            completed_int = int(completed_ns)
            if completed_int >= run_ns:
                return HEALTH_MALFORMED
    last_success = data.get('last_success_at')
    last_failure = data.get('last_failure_at')
    if last_success is not None and not _is_canonical_ist_timestamp(last_success):
        return HEALTH_MALFORMED
    if last_failure is not None and not _is_canonical_ist_timestamp(last_failure):
        return HEALTH_MALFORMED
    last_error = data.get('last_error')
    if last_error is not None and not isinstance(last_error, str):
        return HEALTH_MALFORMED
    bool_or_null = (
        'last_run_ok', 'rss_ok', 'rss_zero_result_ambiguous',
        'a2_isolated_exception', 'a2_lock_contended', 'a2_store_unhealthy',
        'b2_isolated_exception', 'c1b_isolated_exception',
        'primary_verification_ok', 'classification_ok',
    )
    for key in bool_or_null:
        value = data.get(key)
        if value is not None and not isinstance(value, bool):
            return HEALTH_MALFORMED
    outcome = data.get('rss_outcome')
    if outcome is not None and outcome not in RSS_OUTCOMES:
        return HEALTH_MALFORMED
    int_or_null = (
        'rss_error_count', 'items_found', 'sources_checked', 'feeds_ok',
        'feeds_failed', 'provider_current_count', 'provider_stale_count',
        'provider_missing_count', 'primary_verification_failed',
        'classification_failed',
    )
    for key in int_or_null:
        value = data.get(key)
        if value is not None and _nonneg_int(value) is None:
            return HEALTH_MALFORMED
    for key in ('discovery_store_health', 'intelligence_store_health'):
        value = data.get(key)
        if value is not None and value not in STORE_HEALTH_VALUES:
            return HEALTH_MALFORMED
    if completed_ns is None:
        for key in COMPLETED_RESULT_KEYS:
            if data.get(key) is not None:
                return HEALTH_MALFORMED
        if last_success is not None or last_failure is not None:
            return HEALTH_MALFORMED
    else:
        if outcome is None:
            return HEALTH_MALFORMED
        if data.get('rss_ok') is None or data.get('last_run_ok') is None:
            return HEALTH_MALFORMED
        if data.get('rss_zero_result_ambiguous') is None:
            return HEALTH_MALFORMED
        if last_error is None:
            return HEALTH_MALFORMED
        if not _outcome_semantics_ok(data):
            return HEALTH_MALFORMED
        if not _history_clocks_ok(data, int(completed_ns)):
            return HEALTH_MALFORMED
    return HEALTH_OK


def load_sidecar() -> tuple[Optional[dict[str, Any]], str]:
    path = sidecar_path()
    try:
        exists = path.is_file()
    except OSError:
        return None, HEALTH_UNREADABLE
    if not exists:
        return None, HEALTH_MISSING
    try:
        raw = path.read_bytes()
    except OSError:
        return None, HEALTH_UNREADABLE
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return None, HEALTH_UNREADABLE
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, HEALTH_MALFORMED
    health = _classify_payload(data)
    if health != HEALTH_OK:
        return None, health
    return copy.deepcopy(data), HEALTH_OK


def _result_status(status: str, *, mutated: bool = False, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    payload = {
        'ok': status in (STATUS_WRITTEN, STATUS_IDEMPOTENT, STATUS_SKIPPED) and status != STATUS_LOCK_CONTENDED,
        'status': status,
        'mutated': mutated,
        'sidecar_health': None,
    }
    if extra:
        payload.update(extra)
    if status in (STATUS_UNREADABLE, STATUS_MALFORMED):
        payload['ok'] = False
        payload['sidecar_health'] = status
    if status == STATUS_LOCK_CONTENDED:
        payload['ok'] = False
    if status == STATUS_REFUSED:
        payload['ok'] = False
    if status == STATUS_SKIPPED:
        payload['ok'] = True
    if status == STATUS_IDEMPOTENT:
        payload['ok'] = True
    if status == STATUS_WRITTEN:
        payload['ok'] = True
    return payload


def _provider_counts(result: dict[str, Any]) -> tuple[Optional[dict[str, int]], bool]:
    """Return counts dict and whether provider-status structure is inconsistent."""
    n = _nonneg_int(result.get('sources_checked'))
    items = _nonneg_int(result.get('items_found'))
    error_count = result.get('error_count')
    if error_count is None and isinstance(result.get('errors'), list):
        error_count = len(result.get('errors') or [])
    error_n = _nonneg_int(error_count)
    if n is None or items is None or error_n is None:
        return None, True
    status = result.get('provider_status')
    if n == 0:
        if status not in (None, {}, []):
            if not isinstance(status, dict) or len(status) != 0:
                return {
                    'n': 0,
                    'items_found': items,
                    'error_count': error_n,
                    'current_count': 0,
                    'stale_count': 0,
                    'missing_count': 0,
                    'feeds_ok': 0,
                    'feeds_failed': 0,
                }, True
        return {
            'n': 0,
            'items_found': items,
            'error_count': error_n,
            'current_count': 0,
            'stale_count': 0,
            'missing_count': 0,
            'feeds_ok': 0,
            'feeds_failed': 0,
        }, False
    if not isinstance(status, dict):
        return None, True
    if len(status) != n:
        inconsistent = True
    else:
        inconsistent = False
    current = stale = missing = unknown = 0
    feeds_failed = 0
    for row in status.values():
        if not isinstance(row, dict):
            unknown += 1
            continue
        label = row.get('freshness_status')
        if label == 'CURRENT':
            current += 1
        elif label == 'STALE':
            stale += 1
        elif label == 'MISSING':
            missing += 1
        else:
            unknown += 1
        err = row.get('error_count', 0)
        found = row.get('items_found', 0)
        try:
            err_n = int(err or 0)
            found_n = int(found or 0)
        except (TypeError, ValueError):
            inconsistent = True
            continue
        if err_n > 0 and not found_n:
            feeds_failed += 1
    if unknown:
        inconsistent = True
    if current + stale + missing != n:
        inconsistent = True
    return {
        'n': n,
        'items_found': items,
        'error_count': error_n,
        'current_count': current,
        'stale_count': stale,
        'missing_count': missing,
        'feeds_ok': current,
        'feeds_failed': feeds_failed,
    }, inconsistent


def _last_error_for_outcome(outcome: str, *, result: Optional[dict[str, Any]], step1_exception: Optional[BaseException]) -> str:
    errors = (result or {}).get('errors')
    if outcome in (RSS_ALL_CURRENT, RSS_ZERO_RESULT, RSS_MIXED_CURRENT_MISSING):
        return ''
    if outcome == RSS_PARTIAL_ERRORS:
        return _join_errors(errors, 'rss_partial_errors:')
    if outcome == RSS_PARTIAL:
        if isinstance(errors, list) and errors:
            return _join_errors(errors, 'rss_partial:')
        return 'rss_partial:inconsistent_or_partial_provider_state'
    if outcome == RSS_ALL_FAILED:
        joined = _join_errors(errors)
        return joined or 'rss_all_failed'
    if outcome == RSS_NO_PROVIDERS:
        return 'no_enabled_providers'
    if outcome == RSS_STEP1_EXCEPTION:
        if step1_exception is None:
            return 'Exception:unknown'
        return _bound_text(f'{type(step1_exception).__name__}:{step1_exception}')
    return 'rss_partial:inconsistent_or_partial_provider_state'


def classify_rss_outcome(
    *,
    result: Any = None,
    step1_exception: Optional[BaseException] = None,
) -> dict[str, Any]:
    """Total ordered RSS outcome classifier. Sole D1 outcome function."""
    if step1_exception is not None and result is None:
        return {
            'rss_outcome': RSS_STEP1_EXCEPTION,
            'rss_ok': False,
            'rss_zero_result_ambiguous': False,
            'n': None,
            'items_found': None,
            'error_count': None,
            'current_count': None,
            'stale_count': None,
            'missing_count': None,
            'feeds_ok': None,
            'feeds_failed': None,
            'last_error': _last_error_for_outcome(
                RSS_STEP1_EXCEPTION, result=None, step1_exception=step1_exception
            ),
            'inconsistent': False,
        }
    if not isinstance(result, dict):
        return {
            'rss_outcome': RSS_PARTIAL,
            'rss_ok': False,
            'rss_zero_result_ambiguous': False,
            'n': None,
            'items_found': None,
            'error_count': None,
            'current_count': None,
            'stale_count': None,
            'missing_count': None,
            'feeds_ok': None,
            'feeds_failed': None,
            'last_error': 'rss_partial:inconsistent_or_partial_provider_state',
            'inconsistent': True,
        }

    counts, inconsistent = _provider_counts(result)
    if counts is None:
        n = _nonneg_int(result.get('sources_checked'))
        if n == 0:
            outcome = RSS_NO_PROVIDERS
            classified = {
                'rss_outcome': outcome,
                'rss_ok': False,
                'rss_zero_result_ambiguous': False,
                'n': 0,
                'items_found': _nonneg_int(result.get('items_found')) or 0,
                'error_count': _nonneg_int(result.get('error_count')) or 0,
                'current_count': 0,
                'stale_count': 0,
                'missing_count': 0,
                'feeds_ok': 0,
                'feeds_failed': 0,
                'last_error': 'no_enabled_providers',
                'inconsistent': True,
            }
            return classified
        return {
            'rss_outcome': RSS_PARTIAL,
            'rss_ok': False,
            'rss_zero_result_ambiguous': False,
            'n': n,
            'items_found': _nonneg_int(result.get('items_found')),
            'error_count': _nonneg_int(result.get('error_count')),
            'current_count': None,
            'stale_count': None,
            'missing_count': None,
            'feeds_ok': None,
            'feeds_failed': None,
            'last_error': 'rss_partial:inconsistent_or_partial_provider_state',
            'inconsistent': True,
        }

    n = counts['n']
    items = counts['items_found']
    error_count = counts['error_count']
    current_count = counts['current_count']
    stale_count = counts['stale_count']
    missing_count = counts['missing_count']

    # STEP 1
    if n == 0:
        outcome = RSS_NO_PROVIDERS
    # STEP 2
    elif inconsistent:
        outcome = RSS_PARTIAL
    # STEP 3 zero-item Z1-Z4
    elif items == 0:
        if (
            stale_count == 0
            and missing_count == n
            and current_count == 0
            and error_count == 0
        ):
            outcome = RSS_ZERO_RESULT
        elif stale_count == n and missing_count == 0 and current_count == 0:
            outcome = RSS_ALL_FAILED
        elif (
            stale_count > 0
            and missing_count > 0
            and current_count == 0
            and stale_count + missing_count == n
        ):
            outcome = RSS_PARTIAL
        else:
            outcome = RSS_PARTIAL
    # STEP 4
    elif stale_count > 0:
        outcome = RSS_PARTIAL
    # STEP 5
    elif error_count > 0:
        outcome = RSS_PARTIAL_ERRORS
    # STEP 6
    elif current_count == n and missing_count == 0:
        outcome = RSS_ALL_CURRENT
    # STEP 7
    elif current_count > 0 and missing_count > 0 and current_count + missing_count == n:
        outcome = RSS_MIXED_CURRENT_MISSING
    # STEP 8
    else:
        outcome = RSS_PARTIAL

    rss_ok = outcome in RSS_SUCCESS_OUTCOMES
    return {
        'rss_outcome': outcome,
        'rss_ok': rss_ok,
        'rss_zero_result_ambiguous': outcome == RSS_ZERO_RESULT,
        'n': n,
        'items_found': items,
        'error_count': error_count,
        'current_count': current_count,
        'stale_count': stale_count,
        'missing_count': missing_count,
        'feeds_ok': counts['feeds_ok'],
        'feeds_failed': counts['feeds_failed'],
        'last_error': _last_error_for_outcome(
            outcome, result=result, step1_exception=step1_exception
        ),
        'inconsistent': inconsistent,
    }


def _extract_component_flags(result: Any) -> dict[str, Any]:
    discovery = result.get('discovery') if isinstance(result, dict) else None
    verification = result.get('primary_verification') if isinstance(result, dict) else None
    classification = result.get('verified_intelligence') if isinstance(result, dict) else None
    a2_isolated = isinstance(discovery, dict) and discovery.get('ok') is False
    a2_lock = isinstance(discovery, dict) and discovery.get('lock_contended') is True
    a2_unhealthy = isinstance(discovery, dict) and discovery.get('store_unhealthy') is True
    b2_isolated = (
        isinstance(verification, dict)
        and verification.get('ok') is False
        and 'error_type' in verification
    )
    c1b_isolated = (
        isinstance(classification, dict)
        and classification.get('ok') is False
        and 'error_type' in classification
    )

    def _health(value: Any) -> Optional[str]:
        if value in STORE_HEALTH_VALUES:
            return str(value)
        return None

    def _bool_or_none(container: Any, key: str) -> Optional[bool]:
        if not isinstance(container, dict) or key not in container:
            return None
        value = container.get(key)
        return value if isinstance(value, bool) else None

    def _int_or_none(container: Any, key: str) -> Optional[int]:
        if not isinstance(container, dict) or key not in container:
            return None
        return _nonneg_int(container.get(key))

    discovery_health = _health(discovery.get('store_health') if isinstance(discovery, dict) else None)
    intel_health = _health(
        classification.get('store_health') if isinstance(classification, dict) else None
    )
    return {
        'a2_isolated_exception': bool(a2_isolated),
        'a2_lock_contended': bool(a2_lock),
        'a2_store_unhealthy': bool(a2_unhealthy),
        'b2_isolated_exception': bool(b2_isolated),
        'c1b_isolated_exception': bool(c1b_isolated),
        'discovery_store_health': discovery_health,
        'intelligence_store_health': intel_health,
        'primary_verification_ok': _bool_or_none(verification, 'ok'),
        'primary_verification_failed': _int_or_none(verification, 'failed'),
        'classification_ok': _bool_or_none(classification, 'ok'),
        'classification_failed': _int_or_none(classification, 'failed'),
    }


def _last_run_ok(rss_ok: bool, flags: dict[str, Any]) -> bool:
    return (
        rss_ok
        and not flags.get('a2_isolated_exception')
        and not flags.get('b2_isolated_exception')
        and not flags.get('c1b_isolated_exception')
        and not flags.get('a2_lock_contended')
        and not flags.get('a2_store_unhealthy')
    )


def _build_completed_snapshot(
    *,
    run_started_ns: int,
    result: Any,
    step1_exception: Optional[BaseException],
    existing: Optional[dict[str, Any]],
    attempt_at: str,
) -> dict[str, Any]:
    classified = classify_rss_outcome(result=result, step1_exception=step1_exception)
    flags = _extract_component_flags(result if step1_exception is None or result is not None else None)
    if classified['rss_outcome'] == RSS_STEP1_EXCEPTION:
        flags = {
            'a2_isolated_exception': False,
            'a2_lock_contended': False,
            'a2_store_unhealthy': False,
            'b2_isolated_exception': False,
            'c1b_isolated_exception': False,
            'discovery_store_health': None,
            'intelligence_store_health': None,
            'primary_verification_ok': None,
            'primary_verification_failed': None,
            'classification_ok': None,
            'classification_failed': None,
        }
    rss_ok = bool(classified['rss_ok'])
    outcome = classified['rss_outcome']
    last_run_ok = _last_run_ok(rss_ok, flags)
    prior_success = existing.get('last_success_at') if existing else None
    prior_failure = existing.get('last_failure_at') if existing else None
    last_success_at = prior_success
    last_failure_at = prior_failure
    if outcome in SUCCESS_CLOCK_OUTCOMES:
        last_success_at = attempt_at
    if outcome in FAILURE_CLOCK_OUTCOMES:
        last_failure_at = attempt_at
    snapshot = {
        'last_completed_run_started_ns': run_started_ns,
        'last_success_at': last_success_at,
        'last_failure_at': last_failure_at,
        'last_error': classified['last_error'],
        'last_run_ok': last_run_ok,
        'rss_ok': rss_ok,
        'rss_outcome': outcome,
        'rss_zero_result_ambiguous': bool(classified['rss_zero_result_ambiguous']),
        'rss_error_count': classified['error_count'],
        'items_found': classified['items_found'],
        'sources_checked': classified['n'],
        'feeds_ok': classified['feeds_ok'],
        'feeds_failed': classified['feeds_failed'],
        'provider_current_count': classified['current_count'],
        'provider_stale_count': classified['stale_count'],
        'provider_missing_count': classified['missing_count'],
    }
    snapshot.update(flags)
    return snapshot


def _completed_equal(existing: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    keys = ('last_completed_run_started_ns', 'last_success_at', 'last_failure_at') + COMPLETED_RESULT_KEYS
    for key in keys:
        if existing.get(key) != snapshot.get(key):
            return False
    return True


def _persist(payload: dict[str, Any]) -> dict[str, Any]:
    ordered = _ordered(payload)
    health = _classify_payload(ordered)
    if health != HEALTH_OK:
        return _result_status(STATUS_REFUSED, extra={'sidecar_health': health})
    _atomic_save(sidecar_path(), ordered)
    return _result_status(STATUS_WRITTEN, mutated=True, extra={'sidecar_health': HEALTH_OK})


def record_news_pipeline_attempt(run_started_ns: int) -> dict[str, Any]:
    run_ns = _nonneg_int(run_started_ns)
    if run_ns is None:
        return _result_status(STATUS_REFUSED, extra={'reason': 'invalid_run_started_ns'})
    lock = _ReliabilityLock(reliability_lock_path())
    if not lock.try_acquire():
        return _result_status(STATUS_LOCK_CONTENDED)
    try:
        existing, health = load_sidecar()
        if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED):
            return _result_status(health)
        attempt_at = _iso_from_ns(run_ns)
        updated_at = _now_iso()
        if health == HEALTH_MISSING:
            payload = _first_attempt_document(run_ns, attempt_at=attempt_at, updated_at=updated_at)
            return _persist(payload)
        assert existing is not None
        existing_ns = int(existing['run_started_ns'])
        if run_ns < existing_ns:
            return _result_status(STATUS_SKIPPED, extra={'reason': 'older_attempt'})
        if run_ns == existing_ns:
            if existing['run_state'] == RUN_IN_PROGRESS:
                return _result_status(STATUS_IDEMPOTENT, extra={'reason': 'duplicate_in_progress'})
            return _result_status(STATUS_SKIPPED, extra={'reason': 'already_finalized'})
        payload = copy.deepcopy(existing)
        payload['run_state'] = RUN_IN_PROGRESS
        payload['run_started_ns'] = run_ns
        payload['last_attempt_at'] = attempt_at
        payload['updated_at'] = updated_at
        return _persist(payload)
    finally:
        lock.release()


def finalize_news_pipeline_run(
    run_started_ns: int,
    result: Any,
    step1_exception: Optional[BaseException] = None,
) -> dict[str, Any]:
    run_ns = _nonneg_int(run_started_ns)
    if run_ns is None:
        return _result_status(STATUS_REFUSED, extra={'reason': 'invalid_run_started_ns'})
    lock = _ReliabilityLock(reliability_lock_path())
    if not lock.try_acquire():
        return _result_status(STATUS_LOCK_CONTENDED)
    try:
        existing, health = load_sidecar()
        if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED):
            return _result_status(health)
        attempt_at = _iso_from_ns(run_ns)
        updated_at = _now_iso()
        exc = step1_exception if result is None else None
        snapshot = _build_completed_snapshot(
            run_started_ns=run_ns,
            result=result,
            step1_exception=exc,
            existing=existing,
            attempt_at=attempt_at,
        )
        if health == HEALTH_MISSING:
            payload = {
                'schema_version': SCHEMA_VERSION,
                'updated_at': updated_at,
                'run_state': RUN_FINALIZED,
                'run_started_ns': run_ns,
                'last_attempt_at': attempt_at,
            }
            payload.update(snapshot)
            return _persist(payload)
        assert existing is not None
        existing_ns = int(existing['run_started_ns'])
        if run_ns < existing_ns:
            return _result_status(STATUS_SKIPPED, extra={'reason': 'older_finalize'})
        if run_ns == existing_ns:
            if existing['run_state'] == RUN_FINALIZED:
                if _completed_equal(existing, snapshot):
                    return _result_status(STATUS_IDEMPOTENT, extra={'reason': 'duplicate_finalize'})
                return _result_status(STATUS_SKIPPED, extra={'reason': 'first_finalized_snapshot_wins'})
            payload = copy.deepcopy(existing)
            payload['run_state'] = RUN_FINALIZED
            payload['updated_at'] = updated_at
            payload.update(snapshot)
            return _persist(payload)
        payload = copy.deepcopy(existing)
        payload['run_state'] = RUN_FINALIZED
        payload['run_started_ns'] = run_ns
        prior_attempt = existing.get('last_attempt_at')
        if isinstance(prior_attempt, str) and prior_attempt > attempt_at:
            payload['last_attempt_at'] = prior_attempt
        else:
            payload['last_attempt_at'] = attempt_at
        payload['updated_at'] = updated_at
        payload.update(snapshot)
        return _persist(payload)
    finally:
        lock.release()


def _freshness_state(last_success_at: Any, now: datetime) -> str:
    parsed = _parse_iso(last_success_at)
    if parsed is None:
        return FRESHNESS_MISSING
    age = max(0, int((now - parsed).total_seconds()))
    period = str(get_market_period(now))
    threshold = int(get_watchdog_config(now).get('stale_threshold_seconds') or 0)
    status, _unhealthy = classify_source_freshness(age, threshold, period)
    return FRESHNESS_FROM_CLASSIFY.get(status, FRESHNESS_MISSING)


def _latest_run_health(payload: Optional[dict[str, Any]]) -> str:
    if not payload or payload.get('last_completed_run_started_ns') is None:
        return HEALTH_NONE
    outcome = payload.get('rss_outcome')
    if outcome in FAILURE_CLOCK_OUTCOMES:
        return HEALTH_FAILED
    if outcome in (RSS_PARTIAL, RSS_PARTIAL_ERRORS):
        return HEALTH_PARTIAL
    if outcome in RSS_SUCCESS_OUTCOMES and payload.get('rss_ok') is True:
        if payload.get('last_run_ok') is True:
            return HEALTH_SUCCESS
        if payload.get('last_run_ok') is False:
            return HEALTH_SUCCESS_WITH_COMPONENT_FAILURE
    return HEALTH_PARTIAL


def _scheduler_state(orchestrator_state: Optional[dict[str, Any]], *, now: datetime) -> str:
    if not isinstance(orchestrator_state, dict):
        return SCHEDULER_UNKNOWN
    raw = orchestrator_state.get('last_scheduler_tick_unix')
    if raw is None:
        return SCHEDULER_UNKNOWN
    try:
        tick_age = max(0.0, now.timestamp() - float(raw))
    except (TypeError, ValueError):
        return SCHEDULER_UNKNOWN
    from backend.orchestration.orchestrator_state import TICK_STALE_SECONDS

    if tick_age > float(TICK_STALE_SECONDS):
        return SCHEDULER_STALE
    return SCHEDULER_RUNNING


def _expected_live_news_collection_now(now: datetime) -> bool:
    """True when the 30-minute interval collector is expected to run live_news_tracker."""
    profile = get_collection_profile(now)
    return bool(profile.get('run_parallel_ingestion'))


def _evaluate_missed_expected_run(
    payload: Optional[dict[str, Any]],
    now: datetime,
    scheduler_state: str,
) -> bool:
    """Sole D1 missed-run classifier. Read-only. Used for FINALIZED and IN_PROGRESS."""
    if scheduler_state != SCHEDULER_RUNNING:
        return False
    if not _expected_live_news_collection_now(now):
        return False
    if not isinstance(payload, dict):
        return False
    reference = None
    if payload.get('last_success_at') is not None:
        reference = _parse_iso(payload.get('last_success_at'))
    elif payload.get('last_attempt_at') is not None:
        reference = _parse_iso(payload.get('last_attempt_at'))
    if reference is None:
        return False
    age = max(0, int((now - reference).total_seconds()))
    threshold = int(get_watchdog_config(now).get('stale_threshold_seconds') or 0)
    return age > threshold


def _collector_flags(
    *,
    health: str,
    payload: Optional[dict[str, Any]],
    now: datetime,
) -> list[str]:
    flags: list[str] = []
    if health != HEALTH_OK or payload is None:
        flags.append('COLLECTOR_NEVER_COMPLETED')
        return flags
    completed = payload.get('last_completed_run_started_ns')
    if completed is None:
        flags.append('COLLECTOR_NEVER_COMPLETED')
    if payload.get('last_success_at'):
        flags.append('COLLECTOR_LAST_SUCCESS')
    outcome = payload.get('rss_outcome')
    if payload.get('last_failure_at') or outcome in FAILURE_CLOCK_OUTCOMES:
        flags.append('COLLECTOR_LAST_FAILED')
    if outcome in FAILURE_CLOCK_OUTCOMES and payload.get('run_state') == RUN_FINALIZED:
        flags.append('COLLECTOR_FAILED')
    elif (
        outcome in FAILURE_CLOCK_OUTCOMES
        and completed is not None
        and payload.get('run_state') == RUN_IN_PROGRESS
    ):
        flags.append('COLLECTOR_FAILED')
    if payload.get('run_state') == RUN_IN_PROGRESS:
        flags.append('COLLECTOR_IN_PROGRESS')
        attempt_dt = _parse_iso(payload.get('last_attempt_at'))
        if attempt_dt is not None:
            age = max(0, int((now - attempt_dt).total_seconds()))
            threshold = int(get_watchdog_config(now).get('stale_threshold_seconds') or 0)
            if age > threshold:
                flags.append('IN_PROGRESS_STALE')
    seen: set[str] = set()
    ordered: list[str] = []
    for item in flags:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def evaluate_news_pipeline_reliability(
    *,
    now: Optional[datetime] = None,
    orchestrator_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Read-only reliability evaluation. Never writes sidecar/A1/C1A/trading."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    current = current.astimezone(IST)
    payload, health = load_sidecar()
    scheduler_source = orchestrator_state
    if scheduler_source is None:
        try:
            from backend.orchestration.orchestrator_state import load_orchestrator_state

            scheduler_source = load_orchestrator_state()
        except Exception:
            scheduler_source = None
    scheduler_state = _scheduler_state(scheduler_source, now=current)

    if health != HEALTH_OK or payload is None:
        collector = _collector_flags(
            health=health, payload=None, now=current
        )
        if health == HEALTH_MISSING:
            collector = ['COLLECTOR_NEVER_COMPLETED']
        return {
            'sidecar_health': health,
            'run_state': None,
            'latest_attempt': None,
            'last_completed': None,
            'scheduler_state': scheduler_state,
            'collector_state': collector,
            'freshness_state': FRESHNESS_MISSING,
            'latest_run_health': HEALTH_NONE,
            'rss_outcome': None,
            'missed_expected_run': False,
        }

    collector = _collector_flags(
        health=health, payload=payload, now=current
    )
    completed_ns = payload.get('last_completed_run_started_ns')
    last_completed = None
    if completed_ns is not None:
        last_completed = {
            'run_started_ns': completed_ns,
            'rss_outcome': payload.get('rss_outcome'),
            'rss_ok': payload.get('rss_ok'),
            'last_run_ok': payload.get('last_run_ok'),
            'last_error': payload.get('last_error'),
            'items_found': payload.get('items_found'),
            'sources_checked': payload.get('sources_checked'),
            'rss_zero_result_ambiguous': payload.get('rss_zero_result_ambiguous'),
        }
    latest_attempt = {
        'run_started_ns': payload.get('run_started_ns'),
        'last_attempt_at': payload.get('last_attempt_at'),
        'run_state': payload.get('run_state'),
        'in_progress': payload.get('run_state') == RUN_IN_PROGRESS,
    }
    return {
        'sidecar_health': health,
        'run_state': payload.get('run_state'),
        'latest_attempt': latest_attempt,
        'last_completed': last_completed,
        'scheduler_state': scheduler_state,
        'collector_state': collector,
        'freshness_state': _freshness_state(payload.get('last_success_at'), current),
        'latest_run_health': _latest_run_health(payload),
        'rss_outcome': payload.get('rss_outcome'),
        'missed_expected_run': _evaluate_missed_expected_run(
            payload, current, scheduler_state
        ),
    }


evaluate_pipeline_reliability = evaluate_news_pipeline_reliability
