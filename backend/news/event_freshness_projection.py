"""
AstraEdge 52R-D2 — read-time event/source-time freshness projection.

Read-only. No writes, locks, HTTP, AI, file mtime, or store scans.
Ages are never persisted. Event.published_at is never aged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.news.broker_discovery_foundation import (
    BrokerDiscoveryError,
    require_external_id,
    validate_persisted_timestamp,
)
from backend.news.source_time_provenance import (
    ALLOWED_BASIS,
    BASIS_PUBLISHED_PARSED,
    BASIS_UPDATED_PARSED,
    HEALTH_MALFORMED,
    HEALTH_MISSING,
    HEALTH_OK,
    HEALTH_UNREADABLE,
    SOURCE_TIME_AMBIGUOUS,
    SOURCE_TIME_PRESENT,
    load_source_time_provenance,
)

IST = ZoneInfo('Asia/Kolkata')
SCHEMA_VERSION = '52R-D2'

KIND_PUBLICATION = 'PUBLICATION'
KIND_UPDATE = 'UPDATE'

STATE_OK = 'OK'
STATE_AMBIGUOUS = SOURCE_TIME_AMBIGUOUS
STATE_SIDECAR_UNHEALTHY = 'SIDECAR_UNHEALTHY'
STATE_BINDING_MISMATCH = 'BINDING_MISMATCH'
STATE_MALFORMED = 'MALFORMED'
STATE_FUTURE = 'FUTURE'
STATE_MISSING = 'MISSING'

AGGREGATE_NO_SIGHTINGS = 'NO_SIGHTINGS'
AGGREGATE_ALL_AMBIGUOUS = 'ALL_AMBIGUOUS'
AGGREGATE_ALL_PRESENT = 'ALL_PRESENT'
AGGREGATE_MIXED = 'MIXED'
AGGREGATE_SIDECAR_UNHEALTHY = 'SIDECAR_UNHEALTHY'

SIGHTING_PROJECTION_KEYS = (
    'schema_version',
    'sighting_id',
    'source_time_provenance',
    'source_time_basis',
    'source_time_kind',
    'source_published_at_canonical',
    'publication_age_seconds',
    'source_update_age_seconds',
    'discovery_first_seen_at',
    'discovery_age_seconds',
    'source_time_state',
    'discovery_time_state',
    'now',
)

EVENT_PROJECTION_KEYS = (
    'schema_version',
    'event_id',
    'event_source_time_aggregate',
    'linked_sighting_count',
    'projected_sighting_count',
    'publication_age_seconds',
    'source_update_age_seconds',
    'discovery_first_seen_at',
    'discovery_age_seconds',
    'discovery_time_state',
    'sighting_projections',
    'now',
)


def _resolve_now(now: Optional[datetime]) -> tuple[datetime, str]:
    current = now if now is not None else datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    current = current.astimezone(IST)
    text = validate_persisted_timestamp(current.isoformat(), field='now')
    return datetime.fromisoformat(text), text


def _canonical_timestamp(value: Any, *, field: str) -> Optional[str]:
    try:
        return validate_persisted_timestamp(value, field=field)
    except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError):
        return None


def _elapsed_seconds(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds())


def _project_clock_age(
    value: Any,
    *,
    field: str,
    now_dt: datetime,
) -> tuple[Optional[str], Optional[int], str]:
    if value is None or value == '':
        return None, None, STATE_MISSING
    canonical = _canonical_timestamp(value, field=field)
    if canonical is None:
        return None, None, STATE_MALFORMED
    stamp = datetime.fromisoformat(canonical)
    if stamp > now_dt:
        return canonical, None, STATE_FUTURE
    return canonical, _elapsed_seconds(stamp, now_dt), STATE_OK


def _lookup_entry(
    sighting_id: Optional[str],
    payload: Optional[dict[str, Any]],
    health: str,
) -> dict[str, Any]:
    if health == HEALTH_MISSING:
        return {
            'health': health,
            'provenance': SOURCE_TIME_AMBIGUOUS,
            'entry': None,
        }
    if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED):
        return {
            'health': health,
            'provenance': None,
            'entry': None,
        }
    if health != HEALTH_OK or not isinstance(payload, dict):
        return {
            'health': health,
            'provenance': None,
            'entry': None,
        }
    entry = (payload.get('entries') or {}).get(sighting_id)
    if not isinstance(entry, dict):
        return {
            'health': health,
            'provenance': SOURCE_TIME_AMBIGUOUS,
            'entry': None,
        }
    return {
        'health': health,
        'provenance': SOURCE_TIME_PRESENT,
        'entry': entry,
    }


def _sighting_envelope(
    *,
    now_text: str,
    sighting_id: Optional[str] = None,
    source_time_provenance: Optional[str] = None,
    source_time_basis: Optional[str] = None,
    source_time_kind: Optional[str] = None,
    source_published_at_canonical: Optional[str] = None,
    publication_age_seconds: Optional[int] = None,
    source_update_age_seconds: Optional[int] = None,
    discovery_first_seen_at: Optional[str] = None,
    discovery_age_seconds: Optional[int] = None,
    source_time_state: str,
    discovery_time_state: str,
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'sighting_id': sighting_id,
        'source_time_provenance': source_time_provenance,
        'source_time_basis': source_time_basis,
        'source_time_kind': source_time_kind,
        'source_published_at_canonical': source_published_at_canonical,
        'publication_age_seconds': publication_age_seconds,
        'source_update_age_seconds': source_update_age_seconds,
        'discovery_first_seen_at': discovery_first_seen_at,
        'discovery_age_seconds': discovery_age_seconds,
        'source_time_state': source_time_state,
        'discovery_time_state': discovery_time_state,
        'now': now_text,
    }


def project_sighting_freshness(
    sighting: dict,
    *,
    now: Optional[datetime] = None,
    _sidecar_payload: Optional[dict[str, Any]] = None,
    _sidecar_health: Optional[str] = None,
) -> dict[str, Any]:
    """Project one already-loaded A1 sighting against D2P provenance + injected now."""
    now_dt, now_text = _resolve_now(now)

    if not isinstance(sighting, dict):
        return _sighting_envelope(
            now_text=now_text,
            source_time_state=STATE_MALFORMED,
            discovery_time_state=STATE_MALFORMED,
        )

    try:
        sighting_id = require_external_id(sighting.get('sighting_id'), field='sighting_id')
    except BrokerDiscoveryError:
        sighting_id = None

    first_canonical, discovery_age, discovery_state = _project_clock_age(
        sighting.get('first_seen_at'),
        field='first_seen_at',
        now_dt=now_dt,
    )
    a1_canonical = _canonical_timestamp(
        sighting.get('source_published_at'),
        field='source_published_at',
    )

    if sighting_id is None:
        return _sighting_envelope(
            now_text=now_text,
            sighting_id=None,
            source_time_provenance=None,
            source_published_at_canonical=a1_canonical,
            discovery_first_seen_at=first_canonical,
            discovery_age_seconds=discovery_age,
            source_time_state=STATE_MALFORMED,
            discovery_time_state=discovery_state,
        )

    if _sidecar_health is None:
        payload, health = load_source_time_provenance()
    else:
        payload, health = _sidecar_payload, _sidecar_health

    looked = _lookup_entry(sighting_id, payload, health)
    provenance = looked['provenance']
    entry = looked['entry']

    if looked['health'] in (HEALTH_UNREADABLE, HEALTH_MALFORMED):
        return _sighting_envelope(
            now_text=now_text,
            sighting_id=sighting_id,
            source_time_provenance=None,
            source_published_at_canonical=a1_canonical,
            discovery_first_seen_at=first_canonical,
            discovery_age_seconds=discovery_age,
            source_time_state=STATE_SIDECAR_UNHEALTHY,
            discovery_time_state=discovery_state,
        )

    if provenance != SOURCE_TIME_PRESENT or not isinstance(entry, dict):
        return _sighting_envelope(
            now_text=now_text,
            sighting_id=sighting_id,
            source_time_provenance=SOURCE_TIME_AMBIGUOUS,
            source_published_at_canonical=a1_canonical,
            discovery_first_seen_at=first_canonical,
            discovery_age_seconds=discovery_age,
            source_time_state=STATE_AMBIGUOUS,
            discovery_time_state=discovery_state,
        )

    a1_raw = sighting.get('source_published_at')
    bound = (
        entry.get('sighting_id') == sighting_id
        and entry.get('source_time_value') == a1_raw
        and entry.get('source_time_provenance') == SOURCE_TIME_PRESENT
        and entry.get('source_time_basis') in ALLOWED_BASIS
    )
    if not bound:
        return _sighting_envelope(
            now_text=now_text,
            sighting_id=sighting_id,
            source_time_provenance=SOURCE_TIME_PRESENT,
            source_published_at_canonical=a1_canonical,
            discovery_first_seen_at=first_canonical,
            discovery_age_seconds=discovery_age,
            source_time_state=STATE_BINDING_MISMATCH,
            discovery_time_state=discovery_state,
        )

    if a1_canonical is None:
        return _sighting_envelope(
            now_text=now_text,
            sighting_id=sighting_id,
            source_time_provenance=SOURCE_TIME_PRESENT,
            source_published_at_canonical=None,
            discovery_first_seen_at=first_canonical,
            discovery_age_seconds=discovery_age,
            source_time_state=STATE_MALFORMED,
            discovery_time_state=discovery_state,
        )

    stamp = datetime.fromisoformat(a1_canonical)
    basis = entry.get('source_time_basis')
    if stamp > now_dt:
        return _sighting_envelope(
            now_text=now_text,
            sighting_id=sighting_id,
            source_time_provenance=SOURCE_TIME_PRESENT,
            source_time_basis=basis,
            source_published_at_canonical=a1_canonical,
            discovery_first_seen_at=first_canonical,
            discovery_age_seconds=discovery_age,
            source_time_state=STATE_FUTURE,
            discovery_time_state=discovery_state,
        )

    age = _elapsed_seconds(stamp, now_dt)
    if age < 0:
        return _sighting_envelope(
            now_text=now_text,
            sighting_id=sighting_id,
            source_time_provenance=SOURCE_TIME_PRESENT,
            source_time_basis=basis,
            source_published_at_canonical=a1_canonical,
            discovery_first_seen_at=first_canonical,
            discovery_age_seconds=discovery_age,
            source_time_state=STATE_FUTURE,
            discovery_time_state=discovery_state,
        )

    publication_age = age if basis == BASIS_PUBLISHED_PARSED else None
    update_age = age if basis == BASIS_UPDATED_PARSED else None
    kind = KIND_PUBLICATION if basis == BASIS_PUBLISHED_PARSED else KIND_UPDATE
    return _sighting_envelope(
        now_text=now_text,
        sighting_id=sighting_id,
        source_time_provenance=SOURCE_TIME_PRESENT,
        source_time_basis=basis,
        source_time_kind=kind,
        source_published_at_canonical=a1_canonical,
        publication_age_seconds=publication_age,
        source_update_age_seconds=update_age,
        discovery_first_seen_at=first_canonical,
        discovery_age_seconds=discovery_age,
        source_time_state=STATE_OK,
        discovery_time_state=discovery_state,
    )


def _verified_linked_sighting(row: Any, event_id: Optional[str]) -> Optional[dict[str, Any]]:
    """Return the row only when A1 sighting.event_id exactly matches event.event_id."""
    if event_id is None or not isinstance(row, dict):
        return None
    try:
        require_external_id(row.get('sighting_id'), field='sighting_id')
        sighting_event_id = require_external_id(row.get('event_id'), field='event_id')
    except BrokerDiscoveryError:
        return None
    if sighting_event_id != event_id:
        return None
    return row


def _event_aggregate(projections: list[dict[str, Any]]) -> str:
    if not projections:
        return AGGREGATE_NO_SIGHTINGS
    states = [row.get('source_time_state') for row in projections]
    if any(state == STATE_SIDECAR_UNHEALTHY for state in states):
        return AGGREGATE_SIDECAR_UNHEALTHY
    if all(state == STATE_AMBIGUOUS for state in states):
        return AGGREGATE_ALL_AMBIGUOUS
    kinds = {row.get('source_time_kind') for row in projections}
    all_present_ok = all(
        row.get('source_time_provenance') == SOURCE_TIME_PRESENT
        and row.get('source_time_state') == STATE_OK
        for row in projections
    )
    if all_present_ok and len(kinds) == 1 and None not in kinds:
        return AGGREGATE_ALL_PRESENT
    return AGGREGATE_MIXED


def project_event_freshness(
    event: dict,
    *,
    linked_sightings: Optional[list[dict]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Project an already-loaded A1 event using caller-supplied linked sightings.

    Does not scan the A1 store. Does not age event['published_at'].
    Does not select PRIMARY as a time source.
    Caller-supplied rows are included only when sighting.event_id equals event.event_id.
    """
    now_dt, now_text = _resolve_now(now)
    payload, health = load_source_time_provenance()

    if not isinstance(event, dict):
        return {
            'schema_version': SCHEMA_VERSION,
            'event_id': None,
            'event_source_time_aggregate': AGGREGATE_NO_SIGHTINGS,
            'linked_sighting_count': 0,
            'projected_sighting_count': 0,
            'publication_age_seconds': None,
            'source_update_age_seconds': None,
            'discovery_first_seen_at': None,
            'discovery_age_seconds': None,
            'discovery_time_state': STATE_MALFORMED,
            'sighting_projections': [],
            'now': now_text,
        }

    try:
        event_id = require_external_id(event.get('event_id'), field='event_id')
    except BrokerDiscoveryError:
        event_id = None

    first_canonical, discovery_age, discovery_state = _project_clock_age(
        event.get('first_seen_at'),
        field='first_seen_at',
        now_dt=now_dt,
    )

    supplied = linked_sightings if linked_sightings is not None else []
    if not isinstance(supplied, list):
        supplied = []
    linked_rows = [
        row
        for row in (
            _verified_linked_sighting(item, event_id)
            for item in supplied
        )
        if row is not None
    ]
    projections = [
        project_sighting_freshness(
            row,
            now=now_dt,
            _sidecar_payload=payload,
            _sidecar_health=health,
        )
        for row in linked_rows
    ]
    return {
        'schema_version': SCHEMA_VERSION,
        'event_id': event_id,
        'event_source_time_aggregate': _event_aggregate(projections),
        'linked_sighting_count': len(linked_rows),
        'projected_sighting_count': len(projections),
        'publication_age_seconds': None,
        'source_update_age_seconds': None,
        'discovery_first_seen_at': first_canonical,
        'discovery_age_seconds': discovery_age,
        'discovery_time_state': discovery_state,
        'sighting_projections': projections,
        'now': now_text,
    }
