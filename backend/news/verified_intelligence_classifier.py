"""
AstraEdge 52R-C1B — deterministic PRIMARY-only verified intelligence classifier.

Consumes already-persisted discovery events. Writes classification only to the
C1A sidecar. No discovery mutation. No network. No AI. No trading coupling.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.news.broker_discovery_foundation import (
    BrokerDiscoveryError,
    find_recent_events,
    normalize_aware_datetime,
    require_event_fingerprint,
    require_external_id,
    validate_persisted_timestamp,
)
from backend.news.verified_intelligence_store import (
    HEALTH_MALFORMED,
    HEALTH_MISSING,
    HEALTH_OK,
    HEALTH_PARTIAL,
    HEALTH_UNREADABLE,
    VerifiedIntelligenceError,
    build_verified_intelligence_record,
    find_verified_intelligence_for_event,
    get_verified_intelligence_store_health,
    upsert_verified_intelligence_record,
)

EVENT_SCAN_LIMIT = 50
MAX_CLASSIFICATION_ATTEMPTS = 20
DERIVATION_VERSION = '52R-C1B'
TAXONOMY_VERSION = '52R-C1A'
FACT_PARSER_VERSION = 'classification_only'
HEADLINE_SEPARATOR = ' — '
PRIMARY_STATUS = 'PRIMARY_SOURCE_VERIFIED'

CLASS_BOARD_MEETING_INTIMATION = 'BOARD_MEETING_INTIMATION'
CLASS_INVESTOR_PRESENTATION = 'INVESTOR_PRESENTATION'
CLASS_PRESS_RELEASE = 'PRESS_RELEASE'
CLASS_OTHER = 'OTHER'

PROVENANCE_PARSED = 'PARSED_CANONICAL_HEADLINE'
PROVENANCE_UNKNOWN = 'UNKNOWN'

# Deterministic total order. Exact subject equality makes the first three disjoint.
_SUBJECT_RULES: tuple[tuple[str, str], ...] = (
    ('board meeting intimation', CLASS_BOARD_MEETING_INTIMATION),
    ('investor presentation', CLASS_INVESTOR_PRESENTATION),
    ('press release', CLASS_PRESS_RELEASE),
)

UNHEALTHY_C1A = frozenset({HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL})

_WS_RE = re.compile(r'\s+')

_SKIP_NOT_PRIMARY = 'not_primary'
_SKIP_MISSING_IDS = 'missing_ids'
_SKIP_MISSING_HEADLINE = 'missing_headline'
_SKIP_MISSING_PRIMARY_URL = 'missing_primary_url'
_SKIP_MISSING_UPDATED_AT = 'missing_updated_at'
_SKIP_STORE_UNHEALTHY = 'store_unhealthy'
_SKIP_DISCOVERY_UNHEALTHY = 'discovery_unhealthy'
_SKIP_BOUNDED = 'bounded'
_SKIP_LOCK_STOP = 'lock_contention_stop'
_FAIL_CANDIDATE = 'candidate_failed'


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(' ', text.strip())


def classify_verified_intelligence_headline(canonical_headline: Any) -> dict[str, str]:
    """
    Deterministic classification from a persisted canonical headline.

    Precedence: BOARD_MEETING_INTIMATION, INVESTOR_PRESENTATION, PRESS_RELEASE, OTHER.
    """
    other = {
        'classification': CLASS_OTHER,
        'classification_provenance': PROVENANCE_UNKNOWN,
    }
    if not isinstance(canonical_headline, str):
        return dict(other)
    if HEADLINE_SEPARATOR not in canonical_headline:
        return dict(other)
    _issuer, suffix = canonical_headline.split(HEADLINE_SEPARATOR, 1)
    subject = _collapse_ws(suffix).casefold()
    if not subject:
        return dict(other)
    for phrase, klass in _SUBJECT_RULES:
        if subject == phrase:
            return {
                'classification': klass,
                'classification_provenance': PROVENANCE_PARSED,
            }
    return dict(other)


def _empty_stats(**overrides: Any) -> dict[str, Any]:
    stats: dict[str, Any] = {
        'ok': True,
        'scanned': 0,
        'eligible_seen': 0,
        'attempted': 0,
        'inserted': 0,
        'idempotent': 0,
        'skipped': 0,
        'version_conflicts': 0,
        'lock_contended': 0,
        'failed': 0,
        'bounded': False,
        'store_health': None,
        'skip_reasons': {},
    }
    stats.update(overrides)
    return stats


def _bump_reason(stats: dict[str, Any], reason: str) -> None:
    key = str(reason or 'unknown')[:80]
    reasons = stats.setdefault('skip_reasons', {})
    reasons[key] = int(reasons.get(key) or 0) + 1


def _sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda row: (
            str(row.get('last_seen_at') or row.get('updated_at') or ''),
            str(row.get('event_id') or ''),
        ),
        reverse=True,
    )


def _eligible_event(event: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not isinstance(event, dict):
        return None, _SKIP_MISSING_IDS
    status = str(event.get('verification_status') or '')
    if status != PRIMARY_STATUS:
        return None, _SKIP_NOT_PRIMARY
    try:
        event_id = require_external_id(event.get('event_id'), field='event_id')
        fingerprint = require_event_fingerprint(
            event.get('event_fingerprint'),
            field='event_fingerprint',
        )
    except BrokerDiscoveryError:
        return None, _SKIP_MISSING_IDS
    headline = event.get('canonical_headline')
    if not isinstance(headline, str) or not headline.strip():
        return None, _SKIP_MISSING_HEADLINE
    url = event.get('primary_source_url')
    if not isinstance(url, str) or not url.strip():
        return None, _SKIP_MISSING_PRIMARY_URL
    updated_at = event.get('updated_at')
    if updated_at in (None, ''):
        return None, _SKIP_MISSING_UPDATED_AT
    try:
        dt = normalize_aware_datetime(updated_at, field='updated_at')
        validate_persisted_timestamp(dt.isoformat(), field='updated_at')
    except BrokerDiscoveryError:
        return None, _SKIP_MISSING_UPDATED_AT
    return {
        'event_id': event_id,
        'event_fingerprint': fingerprint,
        'canonical_headline': headline,
        'primary_source_url': url,
        'updated_at': updated_at,
        'verification_status': PRIMARY_STATUS,
    }, None


def _matching_logical_row(rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for row in rows:
        if (
            str(row.get('derivation_version') or '') == DERIVATION_VERSION
            and str(row.get('taxonomy_version') or '') == TAXONOMY_VERSION
        ):
            return row
    return None


def _build_candidate(eligible: dict[str, Any], classified: dict[str, str]) -> dict[str, Any]:
    return build_verified_intelligence_record(
        source_event_id=eligible['event_id'],
        source_event_fingerprint=eligible['event_fingerprint'],
        source_canonical_headline=eligible['canonical_headline'],
        source_verification_status=eligible['verification_status'],
        source_primary_url=eligible['primary_source_url'],
        classification=classified['classification'],
        classification_provenance=classified['classification_provenance'],
        source_event_updated_at=eligible['updated_at'],
        facts={},
        fact_provenance=[],
        derivation_version=DERIVATION_VERSION,
        taxonomy_version=TAXONOMY_VERSION,
        fact_parser_version=FACT_PARSER_VERSION,
    )


def _upsert_payload(eligible: dict[str, Any], classified: dict[str, str]) -> dict[str, Any]:
    return {
        'source_event_id': eligible['event_id'],
        'source_event_fingerprint': eligible['event_fingerprint'],
        'source_canonical_headline': eligible['canonical_headline'],
        'source_verification_status': eligible['verification_status'],
        'source_primary_url': eligible['primary_source_url'],
        'source_event_updated_at': eligible['updated_at'],
        'classification': classified['classification'],
        'classification_provenance': classified['classification_provenance'],
        'facts': {},
        'fact_provenance': [],
        'derivation_version': DERIVATION_VERSION,
        'taxonomy_version': TAXONOMY_VERSION,
        'fact_parser_version': FACT_PARSER_VERSION,
    }


def _abort_unhealthy(stats: dict[str, Any], health: str) -> dict[str, Any]:
    stats['ok'] = False
    stats['store_health'] = health
    stats['skipped'] = int(stats['skipped']) + 1
    _bump_reason(stats, _SKIP_STORE_UNHEALTHY)
    return stats


def run_verified_intelligence_classification() -> dict[str, Any]:
    """
    Bounded PRIMARY-only classification pass over already-persisted discovery events.

    Snapshot discovery reads first. C1A upserts happen only after that snapshot.
    """
    stats = _empty_stats()
    try:
        health_info = get_verified_intelligence_store_health()
    except Exception:
        stats['ok'] = False
        stats['failed'] = 1
        stats['store_health'] = HEALTH_UNREADABLE
        _bump_reason(stats, _SKIP_STORE_UNHEALTHY)
        return stats

    health = str(health_info.get('health') or '')
    stats['store_health'] = health
    if health in UNHEALTHY_C1A:
        return _abort_unhealthy(stats, health)
    if health not in (HEALTH_MISSING, HEALTH_OK):
        return _abort_unhealthy(stats, health)

    try:
        snapshot = _sort_events(find_recent_events(limit=EVENT_SCAN_LIMIT))
    except BrokerDiscoveryError:
        stats['skipped'] = int(stats['skipped']) + 1
        _bump_reason(stats, _SKIP_DISCOVERY_UNHEALTHY)
        return stats
    except Exception:
        stats['failed'] = 1
        _bump_reason(stats, _FAIL_CANDIDATE)
        return stats

    write_stopped = False
    remaining_after_cap = False
    for event in snapshot:
        stats['scanned'] = int(stats['scanned']) + 1
        eligible, skip_reason = _eligible_event(event)
        if eligible is None:
            stats['skipped'] = int(stats['skipped']) + 1
            _bump_reason(stats, str(skip_reason or _SKIP_NOT_PRIMARY))
            continue
        stats['eligible_seen'] = int(stats['eligible_seen']) + 1

        if write_stopped:
            stats['skipped'] = int(stats['skipped']) + 1
            _bump_reason(stats, _SKIP_LOCK_STOP)
            remaining_after_cap = True
            continue

        try:
            classified = classify_verified_intelligence_headline(eligible['canonical_headline'])
            candidate = _build_candidate(eligible, classified)
        except Exception:
            stats['failed'] = int(stats['failed']) + 1
            _bump_reason(stats, _FAIL_CANDIDATE)
            continue

        try:
            existing_rows = find_verified_intelligence_for_event(eligible['event_id'])
        except VerifiedIntelligenceError:
            return _abort_unhealthy(stats, HEALTH_MALFORMED)
        except Exception:
            stats['failed'] = int(stats['failed']) + 1
            _bump_reason(stats, _FAIL_CANDIDATE)
            continue

        existing = _matching_logical_row(existing_rows)
        if existing is not None:
            same_input = existing.get('source_input_hash') == candidate.get('source_input_hash')
            same_fp = existing.get('record_fingerprint') == candidate.get('record_fingerprint')
            if same_input and same_fp:
                stats['idempotent'] = int(stats['idempotent']) + 1
                continue

        if int(stats['attempted']) >= MAX_CLASSIFICATION_ATTEMPTS:
            stats['bounded'] = True
            remaining_after_cap = True
            stats['skipped'] = int(stats['skipped']) + 1
            _bump_reason(stats, _SKIP_BOUNDED)
            continue

        stats['attempted'] = int(stats['attempted']) + 1
        try:
            result = upsert_verified_intelligence_record(_upsert_payload(eligible, classified))
        except VerifiedIntelligenceError as exc:
            detail = str(exc)
            if 'unhealthy' in detail:
                abort_health = HEALTH_MALFORMED
                for token in UNHEALTHY_C1A:
                    if token in detail:
                        abort_health = token
                        break
                return _abort_unhealthy(stats, abort_health)
            stats['failed'] = int(stats['failed']) + 1
            _bump_reason(stats, _FAIL_CANDIDATE)
            continue
        except Exception:
            stats['failed'] = int(stats['failed']) + 1
            _bump_reason(stats, _FAIL_CANDIDATE)
            continue

        if not isinstance(result, dict):
            stats['failed'] = int(stats['failed']) + 1
            _bump_reason(stats, _FAIL_CANDIDATE)
            continue
        if result.get('lock_contended'):
            stats['lock_contended'] = int(stats['lock_contended']) + 1
            write_stopped = True
            continue
        if result.get('reason') == 'version_conflict':
            stats['version_conflicts'] = int(stats['version_conflicts']) + 1
            continue
        if result.get('inserted'):
            stats['inserted'] = int(stats['inserted']) + 1
            continue
        if result.get('idempotent'):
            stats['idempotent'] = int(stats['idempotent']) + 1
            continue
        stats['failed'] = int(stats['failed']) + 1
        _bump_reason(stats, _FAIL_CANDIDATE)

    if remaining_after_cap and int(stats['attempted']) >= MAX_CLASSIFICATION_ATTEMPTS:
        stats['bounded'] = True
    return stats
