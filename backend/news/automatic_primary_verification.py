"""
AstraEdge 52R-B2 — automatic governed PRIMARY verification orchestration.

Runs a bounded, zero-network pass over already-persisted discovery sightings
and delegates eligibility/mutation to 52R-B1 verify_linked_primary_sighting.

B2 does not fetch documents, duplicate B1 host/path policy, or hold the
shared discovery-store write lock. B1 owns mutation locking.

PRIMARY means the linked exchange source satisfies the B1 authoritative
contract. It is not a trade signal, score boost, or materiality judgment.
"""

from __future__ import annotations

from typing import Any

from backend.news.broker_discovery_foundation import (
    HEALTH_MALFORMED,
    HEALTH_MISSING,
    HEALTH_OK,
    HEALTH_PARTIAL,
    HEALTH_UNREADABLE,
    SOURCE_KIND_EXCHANGE,
    VERIFICATION_PRIMARY,
    VERIFICATION_REJECTED,
    BrokerDiscoveryError,
    find_recent_events,
    get_store_health,
    list_event_sightings,
)
from backend.news.primary_source_verifier import verify_linked_primary_sighting

EVENT_SCAN_LIMIT = 50
MAX_VERIFICATION_ATTEMPTS = 20

UNHEALTHY_STORE = frozenset({HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL})

_SKIP_STORE_UNHEALTHY = 'store_unhealthy'
_SKIP_STORE_MISSING = 'store_missing'
_SKIP_ALREADY_PRIMARY = 'already_primary'
_SKIP_REJECTED = 'rejected_terminal'
_SKIP_KIND = 'source_kind_ineligible'
_SKIP_LINKAGE = 'linkage_mismatch'
_SKIP_MISSING_IDS = 'missing_ids'
_SKIP_BOUNDED = 'bounded'
_SKIP_B1 = 'b1_not_promoted'
_FAIL_CANDIDATE = 'candidate_failed'


def _empty_stats(**overrides: Any) -> dict[str, Any]:
    stats: dict[str, Any] = {
        'scanned': 0,
        'eligible': 0,
        'attempted': 0,
        'verified': 0,
        'already_primary': 0,
        'skipped': 0,
        'failed': 0,
        'bounded': False,
        'skip_reasons': {},
        'store_health': None,
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


def _sort_sightings(sightings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        sightings,
        key=lambda row: (
            str(row.get('first_seen_at') or ''),
            str(row.get('sighting_id') or ''),
        ),
    )


def _safe_reason(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return _SKIP_B1
    return text[:80]


def run_automatic_primary_verification() -> dict[str, Any]:
    """
    Best-effort PRIMARY enrichment over persisted EXCHANGE discovery sightings.

    One candidate failure never aborts the pass. No network. No outer store lock.
    """
    stats = _empty_stats()
    try:
        health_info = get_store_health()
    except Exception:
        stats['skipped'] = 1
        stats['store_health'] = HEALTH_UNREADABLE
        _bump_reason(stats, _SKIP_STORE_UNHEALTHY)
        return stats

    health = str(health_info.get('health') or '')
    stats['store_health'] = health
    if health in UNHEALTHY_STORE:
        stats['skipped'] = 1
        _bump_reason(stats, _SKIP_STORE_UNHEALTHY)
        return stats
    if health == HEALTH_MISSING:
        _bump_reason(stats, _SKIP_STORE_MISSING)
        return stats
    if health != HEALTH_OK:
        stats['skipped'] = 1
        _bump_reason(stats, _SKIP_STORE_UNHEALTHY)
        return stats

    try:
        events = _sort_events(find_recent_events(limit=EVENT_SCAN_LIMIT))
    except BrokerDiscoveryError:
        stats['skipped'] = 1
        _bump_reason(stats, _SKIP_STORE_UNHEALTHY)
        return stats
    except Exception:
        stats['failed'] = 1
        _bump_reason(stats, _FAIL_CANDIDATE)
        return stats

    for event in events:
        stats['scanned'] = int(stats['scanned']) + 1
        event_id = str(event.get('event_id') or '').strip()
        status = str(event.get('verification_status') or '')
        if not event_id:
            stats['skipped'] = int(stats['skipped']) + 1
            _bump_reason(stats, _SKIP_MISSING_IDS)
            continue
        if status == VERIFICATION_PRIMARY:
            stats['already_primary'] = int(stats['already_primary']) + 1
            _bump_reason(stats, _SKIP_ALREADY_PRIMARY)
            continue
        if status == VERIFICATION_REJECTED:
            stats['skipped'] = int(stats['skipped']) + 1
            _bump_reason(stats, _SKIP_REJECTED)
            continue

        try:
            sightings = _sort_sightings(list_event_sightings(event_id))
        except BrokerDiscoveryError:
            stats['skipped'] = int(stats['skipped']) + 1
            _bump_reason(stats, _SKIP_STORE_UNHEALTHY)
            continue
        except Exception:
            stats['failed'] = int(stats['failed']) + 1
            _bump_reason(stats, _FAIL_CANDIDATE)
            continue

        for sighting in sightings:
            try:
                _consider_sighting(stats, event_id, sighting)
            except Exception:
                stats['failed'] = int(stats['failed']) + 1
                stats['skipped'] = int(stats['skipped']) + 1
                _bump_reason(stats, _FAIL_CANDIDATE)

    return stats


def _consider_sighting(stats: dict[str, Any], event_id: str, sighting: dict[str, Any]) -> None:
    sighting_id = str(sighting.get('sighting_id') or '').strip()
    linked_event_id = str(sighting.get('event_id') or '').strip()
    kind = str(sighting.get('source_kind') or '').strip()
    if not sighting_id:
        stats['skipped'] = int(stats['skipped']) + 1
        _bump_reason(stats, _SKIP_MISSING_IDS)
        return
    if linked_event_id != event_id:
        stats['skipped'] = int(stats['skipped']) + 1
        _bump_reason(stats, _SKIP_LINKAGE)
        return
    if kind != SOURCE_KIND_EXCHANGE:
        stats['skipped'] = int(stats['skipped']) + 1
        _bump_reason(stats, _SKIP_KIND)
        return

    stats['eligible'] = int(stats['eligible']) + 1
    if int(stats['attempted']) >= MAX_VERIFICATION_ATTEMPTS:
        stats['bounded'] = True
        stats['skipped'] = int(stats['skipped']) + 1
        _bump_reason(stats, _SKIP_BOUNDED)
        return

    stats['attempted'] = int(stats['attempted']) + 1
    result = verify_linked_primary_sighting(event_id, sighting_id)
    if not isinstance(result, dict):
        stats['failed'] = int(stats['failed']) + 1
        stats['skipped'] = int(stats['skipped']) + 1
        _bump_reason(stats, _FAIL_CANDIDATE)
        return
    if result.get('promoted'):
        stats['verified'] = int(stats['verified']) + 1
        return
    if result.get('idempotent') or result.get('reason') == 'already_verified':
        stats['already_primary'] = int(stats['already_primary']) + 1
        _bump_reason(stats, _SKIP_ALREADY_PRIMARY)
        return
    stats['skipped'] = int(stats['skipped']) + 1
    _bump_reason(stats, _safe_reason(result.get('reason')))
