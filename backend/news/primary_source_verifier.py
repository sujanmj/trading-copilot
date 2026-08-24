"""
AstraEdge 52R-B1 — governed primary-source verification boundary.

Deterministic, non-network, non-AI policy wrapper around the 52R-A1
mark_primary_source_verified persistence primitive.

This module inspects already-persisted discovery-store events and sightings.
It does not fetch URLs, parse feeds, scrape HTML, call AI, or score trades.

B1 identity limitation:
    Sighting rows do not independently retain canonical event symbols,
    event_type, or structured_facts. B1 therefore cannot independently prove
    symbol/fact identity from the sighting. Promotion requires:
      * exact existing event/sighting linkage (sighting.event_id == event.event_id)
      * exact normalized headline equality
      * the same foundation IST date bucket
      * EXCHANGE source kind plus EXCHANGE_PRIMARY host/path policy
    Do not treat this as a completed provenance/evidence system.

B1 eligibility:
    Only EXCHANGE_PRIMARY may promote. That requires source_kind EXCHANGE, an
    exact authorised HTTPS exchange hostname, AND a known B1 event-specific
    corporate-document path family. Official host membership is not PRIMARY
    eligibility. Generic feed denylisting is an additional defense, not proof
    of event specificity. COMPANY_IR_PRIMARY, REGULATOR_PRIMARY,
    GOVERNMENT_PRIMARY, and ORIGINAL_AUTHORISED_PRIMARY exist as policy
    vocabulary only — they are not active promotion paths.

Production scheduling: none. This capability is dormant.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Optional
from urllib.parse import urlsplit

from backend.news.broker_discovery_foundation import (
    HEALTH_MALFORMED,
    HEALTH_MISSING,
    HEALTH_OK,
    HEALTH_PARTIAL,
    HEALTH_UNREADABLE,
    SOURCE_KIND_BROKER_PUBLIC,
    SOURCE_KIND_COMPANY_IR,
    SOURCE_KIND_EXCHANGE,
    SOURCE_KIND_MANUAL_FEED,
    SOURCE_KIND_NEWS_PUBLISHER,
    VERIFICATION_DISCOVERY_ONLY,
    VERIFICATION_MULTI_SOURCE,
    VERIFICATION_PRIMARY,
    VERIFICATION_REJECTED,
    BrokerDiscoveryError,
    event_date_bucket,
    get_event,
    get_sighting,
    get_store_health,
    mark_primary_source_verified,
    normalize_aware_datetime,
    normalize_headline,
    normalize_url,
    require_external_id,
)

# Deliberately share the 52R-A2 discovery-store write lock. A second lock file
# would reintroduce last-writer-wins between RSS ingest and PRIMARY promotion.
from backend.news.rss_discovery_adapter import _BatchLock, discovery_lock_path

# ---------------------------------------------------------------------------
# Verification-source classes (policy vocabulary; distinct from foundation
# source_kind). Only EXCHANGE_PRIMARY is an active B1 promotion path.
# ---------------------------------------------------------------------------

CLASS_EXCHANGE_PRIMARY = 'EXCHANGE_PRIMARY'
CLASS_COMPANY_IR_PRIMARY = 'COMPANY_IR_PRIMARY'
CLASS_REGULATOR_PRIMARY = 'REGULATOR_PRIMARY'
CLASS_GOVERNMENT_PRIMARY = 'GOVERNMENT_PRIMARY'
CLASS_ORIGINAL_AUTHORISED_PRIMARY = 'ORIGINAL_AUTHORISED_PRIMARY'
CLASS_NEWS_PUBLISHER = 'NEWS_PUBLISHER'
CLASS_BROKER = 'BROKER'
CLASS_AGGREGATOR = 'AGGREGATOR'
CLASS_UNKNOWN = 'UNKNOWN'

PROMOTION_ELIGIBLE_CLASSES = frozenset({CLASS_EXCHANGE_PRIMARY})

# Recognised exchange hostnames. Recognition is not PRIMARY eligibility.
# www/apex NSE and BSE marketing hosts have zero active B1 document classes.
EXCHANGE_PRIMARY_HOSTS = frozenset({
    'nseindia.com',
    'www.nseindia.com',
    'nsearchives.nseindia.com',
    'bseindia.com',
    'www.bseindia.com',
})

# Positive B1 event-document path families. Prefix match is exact.
NSE_ARCHIVE_EVENT_HOSTS = frozenset({'nsearchives.nseindia.com'})
NSE_ARCHIVE_EVENT_PREFIX = '/corporate/'
BSE_EVENT_HOSTS = frozenset({'bseindia.com', 'www.bseindia.com'})
BSE_EVENT_PREFIX = '/xml-data/corpfiling/'

# Known generic discovery/listing/feed surfaces currently used by the registry.
# Additional defense only — not positive proof of event specificity.
GENERIC_EXCHANGE_PATHS = frozenset({
    '',
    '/',
    '/rss-feed',
    '/data/xml/notices.xml',
})

UNHEALTHY_STORE = frozenset({HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL})

_KIND_TO_CLASS = {
    SOURCE_KIND_EXCHANGE: CLASS_EXCHANGE_PRIMARY,
    SOURCE_KIND_COMPANY_IR: CLASS_COMPANY_IR_PRIMARY,
    SOURCE_KIND_NEWS_PUBLISHER: CLASS_NEWS_PUBLISHER,
    SOURCE_KIND_BROKER_PUBLIC: CLASS_BROKER,
    SOURCE_KIND_MANUAL_FEED: CLASS_UNKNOWN,
}

_REASON_LOCK = 'lock_contended'
_REASON_UNHEALTHY = 'store_unhealthy'
_REASON_MALFORMED_EVENT = 'malformed_event_id'
_REASON_MALFORMED_SIGHTING = 'malformed_sighting_id'
_REASON_EVENT_MISSING = 'event_not_found'
_REASON_SIGHTING_MISSING = 'sighting_not_found'
_REASON_LINKAGE = 'linkage_mismatch'
_REASON_HEADLINE = 'headline_mismatch'
_REASON_DATE = 'date_bucket_mismatch'
_REASON_KIND = 'source_kind_ineligible'
_REASON_HOST = 'host_policy_rejected'
_REASON_GENERIC = 'generic_feed_rejected'
_REASON_EVENT_PATH = 'event_path_not_authoritative'
_REASON_EXISTING_PRIMARY = 'existing_primary_invalid'
_REASON_REJECTED = 'rejected_terminal'
_REASON_CONFLICT = 'primary_conflict'
_REASON_UNSUPPORTED = 'unsupported_argument'
_REASON_MALFORMED = 'malformed_input'
_REASON_PROMOTED = 'promoted'
_REASON_IDEMPOTENT = 'already_verified'


def _empty_result(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        'ok': False,
        'promoted': False,
        'idempotent': False,
        'reason': '',
        'event_id': None,
        'sighting_id': None,
        'verification_class': None,
        'primary_source_url': None,
        'previous_status': None,
        'final_status': None,
        'lock_contended': False,
    }
    row.update(overrides)
    return row


def verification_class_for_source_kind(source_kind: Any) -> str:
    kind = str(source_kind or '').strip()
    return _KIND_TO_CLASS.get(kind, CLASS_UNKNOWN)


def _idna_hostname(host: str) -> Optional[str]:
    text = str(host or '').strip().rstrip('.')
    if not text:
        return None
    try:
        return text.encode('idna').decode('ascii').casefold()
    except (UnicodeError, ValueError, AttributeError):
        return None


def _is_ip_literal(host: str) -> bool:
    candidate = host.strip()
    if candidate.startswith('[') and candidate.endswith(']'):
        candidate = candidate[1:-1]
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        return False


def _remainder_is_safe_event_resource(remainder: str) -> bool:
    """
    Conservative structural-escape rejection after an authorised prefix.

    Does not decode or rewrite filenames. Rejects raw '.'/'..' segments,
    backslashes, percent-encoded dot/slash/backslash, doubled separators,
    and an empty remainder.
    """
    if not remainder or remainder.strip('/') == '':
        return False
    if '\\' in remainder:
        return False
    lowered = remainder.casefold()
    if '%2e' in lowered or '%2f' in lowered or '%5c' in lowered:
        return False
    if '//' in remainder or remainder.startswith('/') or remainder.endswith('/'):
        return False
    for segment in remainder.split('/'):
        if not segment or segment in ('.', '..'):
            return False
    return True


def _path_has_resource_after(path: str, prefix: str) -> bool:
    """True when path begins exactly with prefix and a safe nonempty resource follows."""
    if not path.startswith(prefix):
        return False
    return _remainder_is_safe_event_resource(path[len(prefix):])


def _b1_authoritative_event_path(hostname: str, path: str) -> bool:
    """Positive B1 corporate-document path families. Official host is not enough."""
    if hostname in NSE_ARCHIVE_EVENT_HOSTS:
        return _path_has_resource_after(path, NSE_ARCHIVE_EVENT_PREFIX)
    if hostname in BSE_EVENT_HOSTS:
        return _path_has_resource_after(path, BSE_EVENT_PREFIX)
    return False


def classify_exchange_primary_url(url: Any) -> dict[str, Any]:
    """
    Strict HTTPS exchange-host + B1 event-document path classifier.
    Standard-library parsing only. No DNS, no network, no substring matching.
    Official hostname membership is necessary but not sufficient for PRIMARY.
    """
    result = {
        'ok': False,
        'reason': _REASON_HOST,
        'hostname': None,
        'path': None,
        'normalized_url': None,
    }
    if not isinstance(url, str):
        result['reason'] = 'url_not_string'
        return result
    raw = url.strip()
    if not raw or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        result['reason'] = 'url_empty_or_control'
        return result
    if any(ch.isspace() for ch in raw):
        result['reason'] = 'url_whitespace'
        return result
    try:
        parsed = urlsplit(raw)
    except ValueError:
        result['reason'] = 'url_unparseable'
        return result
    scheme = (parsed.scheme or '').casefold()
    if scheme != 'https':
        result['reason'] = 'scheme_not_https'
        return result
    if parsed.username is not None or parsed.password is not None:
        result['reason'] = 'embedded_credentials'
        return result
    if '@' in (parsed.netloc or ''):
        result['reason'] = 'embedded_credentials'
        return result
    try:
        hostname = parsed.hostname
    except ValueError:
        result['reason'] = 'invalid_hostname'
        return result
    if not hostname:
        result['reason'] = 'missing_hostname'
        return result
    if _is_ip_literal(hostname):
        result['reason'] = 'ip_literal'
        return result
    host_cf = hostname.casefold().rstrip('.')
    if host_cf == 'localhost' or host_cf.endswith('.localhost'):
        result['reason'] = 'localhost'
        return result
    ascii_host = _idna_hostname(hostname)
    if ascii_host is None:
        result['reason'] = 'idna_failed'
        return result
    result['hostname'] = ascii_host
    try:
        port = parsed.port
    except ValueError:
        result['reason'] = 'malformed_port'
        return result
    if port is not None and port != 443:
        result['reason'] = 'nondefault_https_port'
        return result
    if ascii_host not in EXCHANGE_PRIMARY_HOSTS:
        result['reason'] = _REASON_HOST
        return result
    raw_path = parsed.path or ''
    result['path'] = raw_path
    generic_key = raw_path if raw_path == '/' else raw_path.rstrip('/')
    generic = {item.casefold() for item in GENERIC_EXCHANGE_PATHS}
    if generic_key.casefold() in generic:
        result['reason'] = _REASON_GENERIC
        return result
    if not _b1_authoritative_event_path(ascii_host, raw_path):
        result['reason'] = _REASON_EVENT_PATH
        return result
    result['ok'] = True
    result['reason'] = 'exchange_primary_url'
    result['normalized_url'] = raw
    return result


def _canonical_ids(event_id: Any, sighting_id: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        eid = require_external_id(event_id, field='event_id')
    except BrokerDiscoveryError:
        return None, None, _REASON_MALFORMED_EVENT
    except Exception:
        return None, None, _REASON_MALFORMED_EVENT
    try:
        sid = require_external_id(sighting_id, field='sighting_id')
    except BrokerDiscoveryError:
        return eid, None, _REASON_MALFORMED_SIGHTING
    except Exception:
        return eid, None, _REASON_MALFORMED_SIGHTING
    return eid, sid, None


def _date_bucket(value: Any, *, field: str) -> Optional[str]:
    try:
        dt = normalize_aware_datetime(value, field=field)
        return event_date_bucket(dt)
    except (BrokerDiscoveryError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def _normalized_headline(value: Any) -> Optional[str]:
    try:
        text = normalize_headline(value)
    except (BrokerDiscoveryError, TypeError, ValueError, AttributeError):
        return None
    if not text:
        return None
    return text


def _evaluate_under_lock(
    eid: str,
    sid: str,
    *,
    now: Any,
) -> dict[str, Any]:
    try:
        health_info = get_store_health()
    except Exception:
        return _empty_result(
            event_id=eid,
            sighting_id=sid,
            reason=_REASON_UNHEALTHY,
        )
    health = str(health_info.get('health') or '')
    if health in UNHEALTHY_STORE:
        return _empty_result(
            event_id=eid,
            sighting_id=sid,
            reason=_REASON_UNHEALTHY,
            final_status=health,
        )
    if health not in (HEALTH_OK, HEALTH_MISSING):
        return _empty_result(
            event_id=eid,
            sighting_id=sid,
            reason=_REASON_UNHEALTHY,
            final_status=health,
        )

    try:
        event = get_event(eid)
        sighting = get_sighting(sid)
    except BrokerDiscoveryError:
        return _empty_result(
            event_id=eid,
            sighting_id=sid,
            reason=_REASON_UNHEALTHY,
        )
    if event is None:
        return _empty_result(
            event_id=eid,
            sighting_id=sid,
            reason=_REASON_EVENT_MISSING,
        )
    if sighting is None:
        previous = str(event.get('verification_status') or '') or None
        return _empty_result(
            event_id=eid,
            sighting_id=sid,
            previous_status=previous,
            final_status=previous,
            reason=_REASON_SIGHTING_MISSING,
        )

    previous = str(event.get('verification_status') or '') or None
    sighting_event_id = str(sighting.get('event_id') or '')
    source_kind = str(sighting.get('source_kind') or '')
    vclass = verification_class_for_source_kind(source_kind)
    source_url = sighting.get('source_url')
    url_info = classify_exchange_primary_url(source_url)
    base = _empty_result(
        event_id=eid,
        sighting_id=sid,
        previous_status=previous,
        final_status=previous,
        verification_class=vclass,
        primary_source_url=source_url if isinstance(source_url, str) else None,
    )

    if sighting_event_id != eid:
        base['reason'] = _REASON_LINKAGE
        return base

    event_headline = _normalized_headline(
        event.get('canonical_headline') or event.get('normalized_headline')
    )
    sighting_headline = _normalized_headline(
        sighting.get('source_headline') or sighting.get('normalized_headline')
    )
    if event_headline is None or sighting_headline is None or event_headline != sighting_headline:
        base['reason'] = _REASON_HEADLINE
        return base

    event_bucket = _date_bucket(event.get('published_at'), field='published_at')
    sighting_bucket = _date_bucket(sighting.get('source_published_at'), field='source_published_at')
    if event_bucket is None or sighting_bucket is None or event_bucket != sighting_bucket:
        base['reason'] = _REASON_DATE
        return base

    if source_kind != SOURCE_KIND_EXCHANGE or vclass != CLASS_EXCHANGE_PRIMARY:
        base['reason'] = _REASON_KIND
        if source_kind != SOURCE_KIND_EXCHANGE:
            base['verification_class'] = vclass
        return base

    if not url_info.get('ok'):
        reason = str(url_info.get('reason') or _REASON_HOST)
        if reason == _REASON_GENERIC:
            base['reason'] = _REASON_GENERIC
            base['verification_class'] = CLASS_EXCHANGE_PRIMARY
        elif reason == _REASON_EVENT_PATH:
            base['reason'] = _REASON_EVENT_PATH
            base['verification_class'] = CLASS_EXCHANGE_PRIMARY
        else:
            base['reason'] = _REASON_HOST
            base['verification_class'] = CLASS_UNKNOWN
        return base

    try:
        candidate_canonical = normalize_url(source_url)
    except (BrokerDiscoveryError, TypeError, ValueError, AttributeError):
        base['reason'] = _REASON_MALFORMED
        return base
    if not candidate_canonical:
        base['reason'] = _REASON_MALFORMED
        return base
    base['primary_source_url'] = candidate_canonical
    base['verification_class'] = CLASS_EXCHANGE_PRIMARY
    if vclass not in PROMOTION_ELIGIBLE_CLASSES:
        base['reason'] = _REASON_KIND
        return base

    if previous == VERIFICATION_REJECTED:
        base['reason'] = _REASON_REJECTED
        return base

    if previous == VERIFICATION_PRIMARY:
        existing_raw = event.get('primary_source_url')
        try:
            existing_canonical = normalize_url(existing_raw)
        except (BrokerDiscoveryError, TypeError, ValueError, AttributeError):
            base['reason'] = _REASON_EXISTING_PRIMARY
            base['primary_source_url'] = existing_raw if isinstance(existing_raw, str) else None
            return base
        if not existing_canonical:
            base['reason'] = _REASON_EXISTING_PRIMARY
            base['primary_source_url'] = existing_raw if isinstance(existing_raw, str) else None
            return base
        if existing_canonical == candidate_canonical:
            base['ok'] = True
            base['idempotent'] = True
            base['promoted'] = False
            base['reason'] = _REASON_IDEMPOTENT
            base['primary_source_url'] = existing_canonical
            return base
        base['reason'] = _REASON_CONFLICT
        base['primary_source_url'] = existing_canonical
        return base

    if previous not in (VERIFICATION_DISCOVERY_ONLY, VERIFICATION_MULTI_SOURCE, ''):
        base['reason'] = _REASON_KIND
        return base

    try:
        marked = mark_primary_source_verified(
            eid,
            primary_source_url=candidate_canonical,
            now=now,
        )
    except BrokerDiscoveryError:
        return _empty_result(
            event_id=eid,
            sighting_id=sid,
            previous_status=previous,
            final_status=previous,
            verification_class=CLASS_EXCHANGE_PRIMARY,
            primary_source_url=candidate_canonical,
            reason=_REASON_MALFORMED,
        )
    final_status = str(marked.get('verification_status') or '')
    final_url = marked.get('primary_source_url')
    base['ok'] = True
    base['promoted'] = True
    base['idempotent'] = False
    base['reason'] = _REASON_PROMOTED
    base['final_status'] = final_status
    base['primary_source_url'] = final_url
    return base


def verify_linked_primary_sighting(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """
    Governed mutation boundary: promote an existing linked EXCHANGE sighting
    to PRIMARY_SOURCE_VERIFIED when every B1 policy gate passes.

    The primary URL is taken from the linked sighting. Callers cannot supply
    an independent primary_source_url.
    """
    parsed_event_id: Any = None
    parsed_sighting_id: Any = None
    try:
        extra = dict(kwargs)
        if 'primary_source_url' in extra:
            return _empty_result(reason=_REASON_UNSUPPORTED)
        now = extra.pop('now', None)
        if len(args) > 2:
            return _empty_result(reason=_REASON_UNSUPPORTED)
        if args:
            parsed_event_id = args[0]
            if 'event_id' in extra:
                return _empty_result(reason=_REASON_UNSUPPORTED)
        else:
            parsed_event_id = extra.pop('event_id', None)
        if len(args) >= 2:
            parsed_sighting_id = args[1]
            if 'sighting_id' in extra:
                return _empty_result(reason=_REASON_UNSUPPORTED)
        else:
            parsed_sighting_id = extra.pop('sighting_id', None)
        if extra:
            return _empty_result(reason=_REASON_UNSUPPORTED)

        eid, sid, id_reason = _canonical_ids(parsed_event_id, parsed_sighting_id)
        if id_reason is not None:
            return _empty_result(
                event_id=eid,
                sighting_id=sid,
                reason=id_reason,
            )

        lock = _BatchLock(discovery_lock_path())
        acquired = False
        try:
            acquired = bool(lock.try_acquire())
            if not acquired:
                return _empty_result(
                    event_id=eid,
                    sighting_id=sid,
                    reason=_REASON_LOCK,
                    lock_contended=True,
                )
            return _evaluate_under_lock(eid, sid, now=now)
        finally:
            if acquired:
                lock.release()
    except Exception:
        return _empty_result(
            reason=_REASON_MALFORMED,
            event_id=parsed_event_id if isinstance(parsed_event_id, str) else None,
            sighting_id=parsed_sighting_id if isinstance(parsed_sighting_id, str) else None,
        )
