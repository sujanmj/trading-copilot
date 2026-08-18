"""
AstraEdge 52R-A1 — broker/public news discovery foundation.

Canonical news-event + source-sighting contracts, deterministic identity,
idempotent persistence, conservative exact matching, and verification state.

Paper/research only. No live collectors, HTTP, browser automation, AI, or
trading decisions. Does not store complete broker article bodies.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from backend.runtime.freshness_engine import normalize_timestamp
from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
SCHEMA_VERSION = '52R-A1'
STORE_RELATIVE = 'broker_news_discovery_store.json'

_ID_NAMESPACE = uuid.UUID('6f2c8d1a-52a1-4a01-9b7e-0c1d2e3f4a5b')

MAX_EXCERPT_LENGTH = 500
EXCERPT_OVERFLOW_SUFFIX = '…'
# Safe upper bound for public query limit arguments (inclusive).
MAX_QUERY_LIMIT = 1000

_CANONICAL_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)
_EVENT_FINGERPRINT_RE = re.compile(r'^[0-9a-f]{64}$')

HEALTH_OK = 'OK'
HEALTH_MISSING = 'MISSING'
HEALTH_UNREADABLE = 'UNREADABLE'
HEALTH_MALFORMED = 'MALFORMED'
HEALTH_PARTIAL = 'PARTIAL'

VERIFICATION_DISCOVERY_ONLY = 'DISCOVERY_ONLY'
VERIFICATION_MULTI_SOURCE = 'MULTI_SOURCE_CONFIRMED'
VERIFICATION_PRIMARY = 'PRIMARY_SOURCE_VERIFIED'
VERIFICATION_REJECTED = 'REJECTED'

ALLOWED_VERIFICATION_STATES = frozenset({
    VERIFICATION_DISCOVERY_ONLY,
    VERIFICATION_MULTI_SOURCE,
    VERIFICATION_PRIMARY,
    VERIFICATION_REJECTED,
})

SOURCE_KIND_BROKER_PUBLIC = 'BROKER_PUBLIC'
SOURCE_KIND_NEWS_PUBLISHER = 'NEWS_PUBLISHER'
SOURCE_KIND_EXCHANGE = 'EXCHANGE'
SOURCE_KIND_COMPANY_IR = 'COMPANY_IR'
SOURCE_KIND_MANUAL_FEED = 'MANUAL_FEED'

ALLOWED_SOURCE_KINDS = frozenset({
    SOURCE_KIND_BROKER_PUBLIC,
    SOURCE_KIND_NEWS_PUBLISHER,
    SOURCE_KIND_EXCHANGE,
    SOURCE_KIND_COMPANY_IR,
    SOURCE_KIND_MANUAL_FEED,
})

EVENT_TYPES = frozenset({
    'RESULT', 'RESULT_PREVIEW', 'GUIDANCE', 'ORDER_WIN', 'CONTRACT',
    'ACQUISITION', 'MERGER', 'DEMERGER', 'DIVIDEND', 'BUYBACK', 'FUND_RAISE',
    'CAPEX', 'EXPANSION', 'MANAGEMENT_CHANGE', 'REGULATORY', 'ANALYST_CALL',
    'RATING_CHANGE', 'TARGET_PRICE_CHANGE', 'CORPORATE_ACTION', 'OTHER',
})

_TRACKING_QUERY_KEYS = frozenset({
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'fbclid', 'gclid', 'gclsrc', 'mc_cid', 'mc_eid', 'igshid',
    'si', 'ref', 'ref_src', 'spm',
})

_PUNCT_RE = re.compile(r'[^\w\s]+', re.UNICODE)
_WS_RE = re.compile(r'\s+')
# Detectable HTML/markup tags — does not match bare comparisons like "x < 5".
_HTML_MARKUP_RE = re.compile(
    r'(?is)(?:<!DOCTYPE\s+html\b|</?\s*(?:html|script|style|div|p|span|a|br|table|tr|td|'
    r'th|body|head|meta|link|ul|ol|li|section|article|header|footer|nav|img|form|input|'
    r'button|h[1-6])\b[^>]*>|</?[A-Za-z][A-Za-z0-9]*\b[^>]*>)'
)

_FORBIDDEN_BODY_KEYS = frozenset({
    'article_body', 'full_article', 'html', 'raw_html',
    'cookies', 'auth_token', 'browser_state',
})

_EVENT_REQUIRED = (
    'event_id', 'event_fingerprint', 'event_type', 'symbols', 'company_names',
    'canonical_headline', 'normalized_headline', 'structured_facts', 'published_at',
    'first_seen_at', 'last_seen_at', 'verification_status', 'source_count',
    'primary_source_url', 'created_at', 'updated_at', 'schema_version',
)
_SIGHTING_REQUIRED = (
    'sighting_id', 'event_id', 'source_name', 'source_kind', 'source_url',
    'source_headline', 'normalized_headline', 'source_published_at',
    'first_seen_at', 'last_seen_at', 'original_publisher', 'content_hash',
    'attribution', 'bounded_excerpt', 'schema_version',
)


class BrokerDiscoveryError(ValueError):
    """Raised for invalid discovery payloads or unhealthy store access."""


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _require_utf8_text(text: str, *, field: str) -> str:
    """Reject unpaired surrogates / non-UTF-8-encodable strings before hashing or persistence."""
    if not isinstance(text, str):
        raise BrokerDiscoveryError(f'{field} must be a string')
    try:
        text.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise BrokerDiscoveryError(f'{field} must be valid UTF-8 text') from exc
    return text


def require_external_id(value: Any, *, field: str) -> str:
    """
    Deterministic validator for externally supplied event/sighting IDs.

    Requires a nonempty, trimmed, valid-UTF-8 canonical UUID string (lowercase hyphenated).
    Does not silently stringify unsupported values.
    """
    if value is None:
        raise BrokerDiscoveryError(f'{field} is required')
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray, int, float)):
        raise BrokerDiscoveryError(f'{field} rejects unsupported type {type(value).__name__}')
    if not isinstance(value, str):
        raise BrokerDiscoveryError(f'{field} must be a string')
    _require_utf8_text(value, field=field)
    if value != value.strip():
        raise BrokerDiscoveryError(f'{field} must be canonical UUID text')
    text = value.strip()
    if not text:
        raise BrokerDiscoveryError(f'{field} is required')
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError) as exc:
        raise BrokerDiscoveryError(f'{field} must be a canonical UUID') from exc
    canonical = str(parsed)
    if text != canonical or not _CANONICAL_UUID_RE.fullmatch(text):
        raise BrokerDiscoveryError(f'{field} must be canonical UUID text')
    return canonical


def require_event_fingerprint(value: Any, *, field: str = 'fingerprint') -> str:
    """Externally supplied event fingerprint: exactly 64 lowercase hex characters."""
    if value is None:
        raise BrokerDiscoveryError(f'{field} is required')
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray, int, float)):
        raise BrokerDiscoveryError(f'{field} rejects unsupported type {type(value).__name__}')
    if not isinstance(value, str):
        raise BrokerDiscoveryError(f'{field} must be a string')
    _require_utf8_text(value, field=field)
    if value != value.strip() or not value:
        raise BrokerDiscoveryError(f'{field} must be 64 lowercase hex characters')
    if not _EVENT_FINGERPRINT_RE.fullmatch(value):
        raise BrokerDiscoveryError(f'{field} must be 64 lowercase hex characters')
    return value


def require_query_limit(value: Any, *, field: str = 'limit') -> int:
    """
    Query limit: Python int only (not bool), nonnegative, <= MAX_QUERY_LIMIT.
    """
    if value is None or isinstance(value, bool):
        raise BrokerDiscoveryError(f'{field} must be a nonnegative int')
    if isinstance(value, (dict, list, set, tuple, bytes, bytearray, str, float)):
        raise BrokerDiscoveryError(f'{field} must be a nonnegative int')
    if type(value) is not int:
        raise BrokerDiscoveryError(f'{field} must be a nonnegative int')
    if value < 0:
        raise BrokerDiscoveryError(f'{field} must be nonnegative')
    if value > MAX_QUERY_LIMIT:
        raise BrokerDiscoveryError(f'{field} exceeds safe maximum {MAX_QUERY_LIMIT}')
    return value


def require_optional_event_payload(value: Any) -> Optional[dict[str, Any]]:
    """Optional event payload for upsert_sighting: None or a dictionary."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BrokerDiscoveryError(f'event must be a dict or None, got {type(value).__name__}')
    return value


def _require_scalar_text(value: Any, *, field: str, allow_empty: bool = True) -> str:
    """Reject containers/bools; do not silently stringify them into text fields."""
    if value is None:
        if allow_empty:
            return ''
        raise BrokerDiscoveryError(f'{field} is required')
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray)):
        raise BrokerDiscoveryError(f'{field} rejects unsupported type {type(value).__name__}')
    if not isinstance(value, str):
        raise BrokerDiscoveryError(f'{field} must be a string')
    _require_utf8_text(value, field=field)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise BrokerDiscoveryError(f'{field} rejects control characters')
    text = value.strip()
    if not text and not allow_empty:
        raise BrokerDiscoveryError(f'{field} is required')
    return text


def normalize_symbol(value: Any) -> str:
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray)):
        raise BrokerDiscoveryError(f'symbol rejects unsupported type {type(value).__name__}')
    if not isinstance(value, str):
        raise BrokerDiscoveryError('symbol must be a string')
    _require_utf8_text(value, field='symbol')
    text = value.strip().upper()
    return re.sub(r'[^A-Z0-9.&-]', '', text)


def normalize_symbols(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, bool) or isinstance(values, (dict, bytes, bytearray)):
        raise BrokerDiscoveryError('symbols must be a sequence of symbol strings')
    raw = values if isinstance(values, (list, tuple, set)) else [values]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        sym = normalize_symbol(item)
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return sorted(out)


def normalize_company_name(value: Any) -> str:
    return _WS_RE.sub(' ', _require_scalar_text(value, field='company_name'))


def normalize_company_names(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, bool) or isinstance(values, (dict, bytes, bytearray)):
        raise BrokerDiscoveryError('company_names must be a sequence of strings')
    raw = values if isinstance(values, (list, tuple, set)) else [values]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = normalize_company_name(item)
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return sorted(out, key=lambda s: s.casefold())


def normalize_source_name(value: Any) -> str:
    return _WS_RE.sub(' ', _require_scalar_text(value, field='source_name')).casefold()


def canonical_source_name(value: Any) -> str:
    """Persisted source_name form: trimmed, whitespace-collapsed, case preserved."""
    return _WS_RE.sub(' ', _require_scalar_text(value, field='source_name', allow_empty=False))


def normalize_publisher(value: Any) -> str:
    return _WS_RE.sub(' ', _require_scalar_text(value, field='original_publisher'))


def canonical_attribution(value: Any) -> str:
    """Deterministic attribution: strip + collapse internal whitespace; empty allowed."""
    return _WS_RE.sub(' ', _require_scalar_text(value, field='attribution'))


def normalize_event_type(value: Any) -> str:
    token = _require_scalar_text(value, field='event_type').upper().replace(' ', '_').replace('-', '_')
    return token if token in EVENT_TYPES else 'OTHER'


def normalize_source_kind(value: Any) -> str:
    token = _require_scalar_text(value, field='source_kind').upper().replace(' ', '_')
    if token in ALLOWED_SOURCE_KINDS:
        return token
    raise BrokerDiscoveryError(f'unsupported source_kind: {value!r}')


def normalize_verification_status(value: Any) -> str:
    token = _require_scalar_text(value, field='verification_status').upper()
    if token in ALLOWED_VERIFICATION_STATES:
        return token
    raise BrokerDiscoveryError(f'unsupported verification_status: {value!r}')


def normalize_headline(value: Any) -> str:
    text = _require_scalar_text(value, field='headline').casefold()
    text = _PUNCT_RE.sub(' ', text)
    return _WS_RE.sub(' ', text).strip()


_SCHEMELESS_HOST_RE = re.compile(
    r'^(?P<host>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?P<path>/.*)?$'
)
_REJECTED_URL_SCHEMES = frozenset({
    'javascript', 'file', 'data', 'ftp', 'mailto', 'blob', 'about', 'ws', 'wss',
})
_DNS_LABEL_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')
# All-numeric dotted hosts (e.g. 999.999.999.999) must not fall through to DNS.
_DOTTED_IPV4_CANDIDATE_RE = re.compile(r'^\d+(?:\.\d+)+$')


def _validate_public_hostname(hostname: str) -> str:
    """Validate DNS / IPv4 / IPv6 hostnames for public-source URLs."""
    import ipaddress

    host = str(hostname or '').strip().lower()
    if not host:
        raise BrokerDiscoveryError('url hostname is required')

    # IPv4 — accept only when the address library accepts it.
    try:
        ipaddress.IPv4Address(host)
        return host
    except ipaddress.AddressValueError:
        # Fail closed for all-numeric dotted candidates; do not treat as DNS.
        if _DOTTED_IPV4_CANDIDATE_RE.fullmatch(host):
            raise BrokerDiscoveryError(f'invalid IPv4 literal: {hostname!r}') from None

    # IPv6 (urlparse hostname is unbracketed)
    try:
        ipaddress.IPv6Address(host)
        return host
    except ipaddress.AddressValueError:
        pass

    # IDNA / DNS
    try:
        ascii_host = host.encode('idna').decode('ascii').lower()
    except UnicodeError as exc:
        raise BrokerDiscoveryError(f'invalid hostname: {hostname!r}') from exc

    if len(ascii_host) > 253:
        raise BrokerDiscoveryError('hostname exceeds DNS length limit')
    if ascii_host.startswith('.') or ascii_host.endswith('.'):
        raise BrokerDiscoveryError(f'invalid hostname: {hostname!r}')
    labels = ascii_host.split('.')
    if len(labels) < 2:
        raise BrokerDiscoveryError(f'single-label hostname rejected: {hostname!r}')
    for label in labels:
        if not label:
            raise BrokerDiscoveryError(f'hostname contains empty label: {hostname!r}')
        if len(label) > 63:
            raise BrokerDiscoveryError(f'DNS label too long: {label!r}')
        if label.startswith('-') or label.endswith('-'):
            raise BrokerDiscoveryError(f'invalid DNS label: {label!r}')
        if '_' in label or not _DNS_LABEL_RE.match(label):
            raise BrokerDiscoveryError(f'invalid DNS label: {label!r}')
    return ascii_host


def _format_netloc(hostname: str, port: Optional[int], *, scheme: str) -> str:
    import ipaddress

    host_out = hostname
    try:
        ipaddress.IPv6Address(hostname)
        host_out = f'[{hostname}]'
    except ipaddress.AddressValueError:
        pass
    if port is None:
        return host_out
    if scheme == 'http' and port == 80:
        return host_out
    if scheme == 'https' and port == 443:
        return host_out
    return f'{host_out}:{port}'


def _safe_urlparse(raw: str):
    """urlparse wrapper that converts raw ValueError into BrokerDiscoveryError."""
    try:
        return urlparse(raw)
    except ValueError as exc:
        raise BrokerDiscoveryError(f'unsupported url: {raw!r}') from exc


def normalize_url(value: Any) -> str:
    """
    Strict HTTP/HTTPS URL normalizer.

    Empty input returns '' (allowed for MANUAL_FEED only at the sighting contract).
    Scheme-less host/path forms such as www.example.com/x may become https://...
    """
    import ipaddress

    if value is None or value == '':
        return ''
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray)):
        raise BrokerDiscoveryError(f'url rejects unsupported type {type(value).__name__}')
    if not isinstance(value, str):
        raise BrokerDiscoveryError('url must be a string')
    _require_utf8_text(value, field='url')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise BrokerDiscoveryError('url rejects control characters')
    raw = value.strip()
    if any(ch.isspace() for ch in raw):
        raise BrokerDiscoveryError('url rejects whitespace')
    if not raw:
        return ''

    try:
        # Windows path / relative path without host
        if re.match(r'^[A-Za-z]:[\\/]', raw) or raw.startswith('\\\\'):
            raise BrokerDiscoveryError(f'unsupported url: {raw!r}')
        if raw.startswith('/') or raw.startswith('./') or raw.startswith('../'):
            raise BrokerDiscoveryError(f'unsupported relative url: {raw!r}')

        parsed = _safe_urlparse(raw)
        scheme = (parsed.scheme or '').lower()
        if scheme in _REJECTED_URL_SCHEMES:
            raise BrokerDiscoveryError(f'unsupported url scheme: {scheme}')

        # Scheme-less normal web host/path -> https
        if not scheme and not parsed.netloc:
            m = _SCHEMELESS_HOST_RE.match(raw)
            if not m or '.' not in m.group('host'):
                raise BrokerDiscoveryError(f'unsupported url: {raw!r}')
            raw = 'https://' + raw
            parsed = _safe_urlparse(raw)
            scheme = 'https'

        if scheme not in ('http', 'https'):
            raise BrokerDiscoveryError(f'url scheme must be http or https, got {scheme!r}')

        if parsed.username is not None or parsed.password is not None:
            raise BrokerDiscoveryError('url credentials are not allowed')
        netloc_raw = parsed.netloc or ''
        if '@' in netloc_raw:
            raise BrokerDiscoveryError('url credentials are not allowed')
        try:
            hostname = parsed.hostname
        except ValueError as exc:
            raise BrokerDiscoveryError(f'invalid url hostname: {raw!r}') from exc
        if not hostname:
            raise BrokerDiscoveryError('url hostname is required')
        host = _validate_public_hostname(hostname)

        try:
            port = parsed.port
        except ValueError as exc:
            raise BrokerDiscoveryError(f'invalid url port: {raw!r}') from exc
        if port is not None and (port < 1 or port > 65535):
            raise BrokerDiscoveryError(f'invalid url port: {port}')

        path = parsed.path or ''
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')
        query_pairs = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.casefold() not in _TRACKING_QUERY_KEYS
        ]
        query_pairs.sort(key=lambda kv: (kv[0].casefold(), kv[1]))
        query = urlencode(query_pairs, doseq=True)
        netloc = _format_netloc(host, port, scheme=scheme)
        # Fragments intentionally dropped.
        return urlunparse((scheme, netloc, path, '', query, ''))
    except BrokerDiscoveryError:
        raise
    except (ValueError, UnicodeError, ipaddress.AddressValueError) as exc:
        raise BrokerDiscoveryError(f'unsupported url: {raw!r}') from exc


def normalize_aware_datetime(value: Any, *, field: str = 'timestamp') -> datetime:
    """Input-time normalizer (may accept broader parseable values)."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray)):
        raise BrokerDiscoveryError(f'{field} rejects unsupported type {type(value).__name__}')
    parsed = normalize_timestamp(value)
    if parsed is None:
        raise BrokerDiscoveryError(f'{field} must be a timezone-aware parseable timestamp')
    return parsed.astimezone(IST)


def _iso(dt: datetime) -> str:
    """Canonical persisted IST ISO-8601 representation."""
    return dt.astimezone(IST).isoformat()


def _now_ist() -> datetime:
    return datetime.now(IST)


def _normalize_operation_now(now: Optional[datetime] = None) -> datetime:
    """Normalize the single operation clock used for one logical mutation/builder call."""
    if now is None:
        return _now_ist()
    if isinstance(now, bool) or isinstance(now, (int, float, dict, list, set, tuple, bytes, bytearray)):
        raise BrokerDiscoveryError(f'now rejects unsupported type {type(now).__name__}')
    if isinstance(now, datetime):
        return normalize_aware_datetime(now, field='now')
    if isinstance(now, str):
        return normalize_aware_datetime(now, field='now')
    raise BrokerDiscoveryError(f'now rejects unsupported type {type(now).__name__}')


def require_query_date(value: Any, *, field: str = 'date') -> str:
    """
    Accept only datetime, date, or parseable timestamp/date string.
    Never invoke an arbitrary object's isoformat() method.
    Returns canonical YYYY-MM-DD (IST calendar day for datetimes).
    """
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray, int, float)):
        raise BrokerDiscoveryError(f'{field} rejects unsupported type {type(value).__name__}')
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).date().isoformat()
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, str):
        _require_utf8_text(value, field=field)
        text = value.strip()
        if not text:
            raise BrokerDiscoveryError(f'{field} must be a parseable date or timestamp')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError as exc:
                raise BrokerDiscoveryError(f'{field} is not a valid date') from exc
        try:
            dt = normalize_aware_datetime(text, field=field)
        except BrokerDiscoveryError:
            raise
        except (TypeError, ValueError, AttributeError) as exc:
            raise BrokerDiscoveryError(f'{field} must be a parseable date or timestamp') from exc
        return dt.date().isoformat()
    raise BrokerDiscoveryError(f'{field} rejects unsupported type {type(value).__name__}')


def validate_persisted_timestamp(value: Any, *, field: str = 'timestamp') -> str:
    """
    Strict validator for already-persisted timestamps.

    Requires a string, timezone-aware ISO-8601 value whose exact text equals the
    canonical IST serialization after parse (round-trip stable).
    """
    if value is None or isinstance(value, bool):
        raise BrokerDiscoveryError(f'{field} must be a canonical ISO timestamp string')
    if isinstance(value, (int, float, datetime)) or type(value).__name__ == 'date':
        raise BrokerDiscoveryError(f'{field} must be a canonical ISO timestamp string')
    if not isinstance(value, str):
        raise BrokerDiscoveryError(f'{field} must be a canonical ISO timestamp string')
    try:
        _require_utf8_text(value, field=field)
    except BrokerDiscoveryError:
        raise
    text = value
    if not text or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise BrokerDiscoveryError(f'{field} is not a canonical ISO timestamp')
    # Must include an explicit numeric offset or Z (Z then fails IST round-trip).
    if not re.search(r'(Z|[+-]\d{2}:\d{2})$', text):
        raise BrokerDiscoveryError(f'{field} must be timezone-aware ISO with offset')
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError as exc:
        raise BrokerDiscoveryError(f'{field} is not valid ISO-8601: {text!r}') from exc
    if dt.tzinfo is None:
        raise BrokerDiscoveryError(f'{field} must be timezone-aware')
    canonical = _iso(dt)
    if canonical != text:
        raise BrokerDiscoveryError(
            f'{field} is not canonical IST representation: {text!r} != {canonical!r}'
        )
    return canonical


def _safe_fact_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise BrokerDiscoveryError('structured_facts reject NaN/Infinity')
        return value
    if isinstance(value, str):
        _require_utf8_text(value, field='structured_fact')
        return _WS_RE.sub(' ', value.strip())
    if isinstance(value, list):
        return [_safe_fact_value(v) for v in value]
    if isinstance(value, dict):
        return normalize_structured_facts(value)
    if isinstance(value, (set, tuple, bytes, bytearray)):
        raise BrokerDiscoveryError(f'unsupported structured_fact type: {type(value).__name__}')
    raise BrokerDiscoveryError(f'unsupported structured_fact type: {type(value).__name__}')


def normalize_structured_facts(facts: Any) -> dict[str, Any]:
    if facts is None:
        return {}
    if not isinstance(facts, dict):
        raise BrokerDiscoveryError('structured_facts must be a mapping')
    for raw_key in facts.keys():
        if not isinstance(raw_key, str):
            raise BrokerDiscoveryError(
                f'structured_facts keys must be strings, got {type(raw_key).__name__}'
            )
        _require_utf8_text(raw_key, field='structured_facts_key')
    # Detect collisions where distinct keys normalize to the same string (already strings).
    key_owners: dict[str, str] = {}
    for raw_key in facts.keys():
        key = str(raw_key)
        if key in key_owners and key_owners[key] != raw_key:
            raise BrokerDiscoveryError(f'structured_facts key collision after normalization: {key!r}')
        key_owners[key] = raw_key
    out: dict[str, Any] = {}
    for key in sorted(key_owners):
        out[key] = _safe_fact_value(facts[key_owners[key]])
    return out


def bound_excerpt(value: Any, *, max_length: int = MAX_EXCERPT_LENGTH) -> str:
    if value is None:
        text = ''
    elif isinstance(value, bool) or isinstance(value, (dict, list, set, tuple, bytes, bytearray)):
        raise BrokerDiscoveryError(f'bounded_excerpt rejects unsupported type {type(value).__name__}')
    elif not isinstance(value, str):
        raise BrokerDiscoveryError('bounded_excerpt must be a string')
    else:
        text = value
    _require_utf8_text(text, field='bounded_excerpt')
    if _HTML_MARKUP_RE.search(text):
        raise BrokerDiscoveryError('raw HTML/markup excerpts are not allowed')
    if len(text) <= max_length:
        return text
    keep = max(0, max_length - len(EXCERPT_OVERFLOW_SUFFIX))
    return text[:keep] + EXCERPT_OVERFLOW_SUFFIX


def _stable_hash(parts: list[str]) -> str:
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()


def _uuid5_from_fingerprint(fingerprint: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, fingerprint))


def event_date_bucket(published_at: datetime) -> str:
    return published_at.astimezone(IST).date().isoformat()


def content_hash_for_sighting(
    *,
    source_name: str,
    source_url: str,
    normalized_headline: str,
    source_published_at: datetime,
    original_publisher: str,
) -> str:
    return _stable_hash([
        normalize_source_name(source_name),
        normalize_url(source_url),
        normalized_headline,
        event_date_bucket(source_published_at),
        normalize_publisher(original_publisher).casefold(),
    ])


def compute_sighting_fingerprint(
    *,
    source_name: str,
    source_url: str,
    normalized_headline: str,
    source_published_at: datetime,
    original_publisher: str,
) -> str:
    return content_hash_for_sighting(
        source_name=source_name,
        source_url=source_url,
        normalized_headline=normalized_headline,
        source_published_at=source_published_at,
        original_publisher=original_publisher,
    )


def compute_event_fingerprint(
    *,
    symbols: list[str],
    event_type: str,
    structured_facts: dict[str, Any],
    normalized_headline: str,
    published_at: datetime,
) -> str:
    facts_blob = json.dumps(structured_facts, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return _stable_hash([
        ','.join(normalize_symbols(symbols)),
        normalize_event_type(event_type),
        facts_blob,
        normalize_headline(normalized_headline),
        event_date_bucket(published_at),
    ])


# ---------------------------------------------------------------------------
# Contract builders
# ---------------------------------------------------------------------------


def build_canonical_event(
    *,
    event_type: Any,
    symbols: Any,
    canonical_headline: Any,
    published_at: Any,
    company_names: Any = None,
    structured_facts: Any = None,
    primary_source_url: Any = '',
    verification_status: Any = VERIFICATION_DISCOVERY_ONLY,
    first_seen_at: Any = None,
    last_seen_at: Any = None,
    source_count: int = 0,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    now_dt = _normalize_operation_now(now)
    pub = normalize_aware_datetime(published_at, field='published_at')
    first = normalize_aware_datetime(first_seen_at or now_dt, field='first_seen_at')
    last = normalize_aware_datetime(last_seen_at or now_dt, field='last_seen_at')
    syms = normalize_symbols(symbols)
    if not syms:
        raise BrokerDiscoveryError('canonical event requires at least one symbol')
    headline = _require_scalar_text(canonical_headline, field='canonical_headline', allow_empty=False)
    norm_headline = normalize_headline(headline)
    facts = normalize_structured_facts(structured_facts)
    etype = normalize_event_type(event_type)
    status = normalize_verification_status(verification_status)
    primary = normalize_url(primary_source_url)
    fingerprint = compute_event_fingerprint(
        symbols=syms,
        event_type=etype,
        structured_facts=facts,
        normalized_headline=norm_headline,
        published_at=pub,
    )
    event_id = _uuid5_from_fingerprint(f'event:{fingerprint}')
    # Builder default is 0; callers cannot force a trusted persisted count through upsert.
    sc = 0
    if source_count not in (0, None):
        # Accept only for in-memory construction diagnostics; upsert paths ignore this.
        if type(source_count) is int and not isinstance(source_count, bool) and source_count >= 0:
            sc = source_count
        else:
            raise BrokerDiscoveryError('source_count must be a nonnegative int')
    return {
        'event_id': event_id,
        'event_fingerprint': fingerprint,
        'event_type': etype,
        'symbols': list(syms),
        'company_names': normalize_company_names(company_names),
        'canonical_headline': headline,
        'normalized_headline': norm_headline,
        'structured_facts': copy.deepcopy(facts),
        'published_at': _iso(pub),
        'first_seen_at': _iso(first),
        'last_seen_at': _iso(last),
        'verification_status': status,
        'source_count': sc,
        'primary_source_url': primary,
        'created_at': _iso(now_dt),
        'updated_at': _iso(now_dt),
        'schema_version': SCHEMA_VERSION,
    }


def build_source_sighting(
    *,
    source_name: Any,
    source_kind: Any,
    source_url: Any,
    source_headline: Any,
    source_published_at: Any,
    original_publisher: Any = '',
    attribution: Any = '',
    bounded_excerpt: Any = '',
    event_id: Any = '',
    first_seen_at: Any = None,
    last_seen_at: Any = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    now_dt = _normalize_operation_now(now)
    name = canonical_source_name(source_name)
    kind = normalize_source_kind(source_kind)
    url = normalize_url(source_url)
    if kind != SOURCE_KIND_MANUAL_FEED and not url:
        raise BrokerDiscoveryError(f'{kind} requires a valid non-empty source_url')
    # MANUAL_FEED may persist an empty URL when no public locator exists.
    headline = _require_scalar_text(source_headline, field='source_headline', allow_empty=False)
    norm_headline = normalize_headline(headline)
    pub = normalize_aware_datetime(source_published_at, field='source_published_at')
    first = normalize_aware_datetime(first_seen_at or now_dt, field='first_seen_at')
    last = normalize_aware_datetime(last_seen_at or now_dt, field='last_seen_at')
    publisher = normalize_publisher(original_publisher)
    attr = canonical_attribution(attribution)
    excerpt = bound_excerpt(bounded_excerpt)
    if event_id in (None, ''):
        eid = ''
    else:
        eid = _require_scalar_text(event_id, field='event_id')
    fingerprint = compute_sighting_fingerprint(
        source_name=name,
        source_url=url,
        normalized_headline=norm_headline,
        source_published_at=pub,
        original_publisher=publisher,
    )
    sighting_id = _uuid5_from_fingerprint(f'sighting:{fingerprint}')
    return {
        'sighting_id': sighting_id,
        'event_id': eid,
        'source_name': name,
        'source_kind': kind,
        'source_url': url,
        'source_headline': headline,
        'normalized_headline': norm_headline,
        'source_published_at': _iso(pub),
        'first_seen_at': _iso(first),
        'last_seen_at': _iso(last),
        'original_publisher': publisher,
        'content_hash': fingerprint,
        'attribution': attr,
        'bounded_excerpt': excerpt,
        'schema_version': SCHEMA_VERSION,
        'article_body': None,
    }


# ---------------------------------------------------------------------------
# Store validation / persistence
# ---------------------------------------------------------------------------


def store_path() -> Path:
    return get_data_path(STORE_RELATIVE)


def _empty_store() -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'events': {},
        'sightings': {},
        'updated_at': _iso(_now_ist()),
    }


def _is_valid_persisted_ts(value: Any) -> bool:
    try:
        validate_persisted_timestamp(value)
        return True
    except BrokerDiscoveryError:
        return False


def _strict_nonneg_int(value: Any) -> Optional[int]:
    """Return int only for true JSON/Python integers (not bool/float/str)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _linked_sightings(store_or_sightings: Any, event_id: str) -> list[dict[str, Any]]:
    if isinstance(store_or_sightings, dict) and 'sightings' in store_or_sightings:
        sightings = store_or_sightings.get('sightings') or {}
    else:
        sightings = store_or_sightings or {}
    eid = str(event_id or '').strip()
    return [s for s in sightings.values() if isinstance(s, dict) and str(s.get('event_id') or '') == eid]


def _distinct_normalized_sources(sightings: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for s in sightings:
        name = s.get('source_name')
        if not isinstance(name, str) or not name.strip():
            continue
        out.add(normalize_source_name(name))
    return out


def _facts_contain_bad_number(value: Any) -> bool:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return True
    if isinstance(value, list):
        return any(_facts_contain_bad_number(v) for v in value)
    if isinstance(value, dict):
        return any(_facts_contain_bad_number(v) for v in value.values())
    return False


def _validate_event_record(key: str, event: Any, sightings: dict) -> Optional[str]:
    if not isinstance(event, dict):
        return 'event value is not a dictionary'
    for field in _EVENT_REQUIRED:
        if field not in event:
            return f'event missing field {field}'
    if str(event.get('event_id') or '') != str(key):
        return 'event key/event_id mismatch'
    if str(event.get('schema_version') or '') != SCHEMA_VERSION:
        return 'event schema_version invalid'

    symbols = event.get('symbols')
    if not isinstance(symbols, list) or not symbols:
        return 'event symbols empty or invalid'
    if any(not isinstance(item, str) for item in symbols):
        return 'event symbols must contain only strings'
    try:
        for item in symbols:
            _require_utf8_text(item, field='symbol')
        expected_symbols = normalize_symbols(symbols)
    except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError, OverflowError):
        return 'event symbols malformed'
    if len(expected_symbols) != len(symbols):
        return 'event symbols not canonical (duplicates or empty members)'
    if symbols != expected_symbols:
        return 'event symbols not canonical (unsorted/malformed)'

    headline = event.get('canonical_headline')
    if not isinstance(headline, str) or not headline.strip():
        return 'event canonical_headline empty or invalid'
    try:
        expected_norm = normalize_headline(headline)
    except BrokerDiscoveryError:
        return 'event canonical_headline malformed'
    if event.get('normalized_headline') != expected_norm:
        return 'event normalized_headline incorrect'

    facts = event.get('structured_facts')
    if not isinstance(facts, dict):
        return 'event structured_facts must be a dict'
    if any(not isinstance(k, str) for k in facts.keys()):
        return 'event structured_facts keys must be strings'
    if _facts_contain_bad_number(facts):
        return 'event structured_facts contain NaN/Infinity'
    try:
        expected_facts = normalize_structured_facts(facts)
    except BrokerDiscoveryError:
        return 'event structured_facts malformed'
    if facts != expected_facts:
        return 'event structured_facts not canonical'

    company_names = event.get('company_names')
    if not isinstance(company_names, list):
        return 'event company_names must be a list'
    if any(not isinstance(item, str) for item in company_names):
        return 'event company_names must contain only strings'
    try:
        expected_companies = normalize_company_names(company_names)
    except BrokerDiscoveryError:
        return 'event company_names malformed'
    if company_names != expected_companies:
        return 'event company_names not canonical'

    sc = _strict_nonneg_int(event.get('source_count'))
    if sc is None:
        return 'event source_count malformed'
    linked = _linked_sightings(sightings, str(key))
    if sc != len(linked):
        return 'event source_count inconsistent with linked sightings'

    status = event.get('verification_status')
    if not isinstance(status, str) or status not in ALLOWED_VERIFICATION_STATES:
        return 'event verification_status unsupported'
    primary = event.get('primary_source_url')
    if not isinstance(primary, str):
        return 'event primary_source_url must be str'
    if primary:
        try:
            norm_primary = normalize_url(primary)
        except BrokerDiscoveryError:
            return 'event primary_source_url invalid'
        if primary != norm_primary:
            return 'event primary_source_url not canonical'
    distinct = _distinct_normalized_sources(linked)
    if status == VERIFICATION_DISCOVERY_ONLY:
        if len(distinct) >= 2:
            return 'DISCOVERY_ONLY has too many distinct sources'
        if primary:
            return 'DISCOVERY_ONLY must not have primary_source_url'
    elif status == VERIFICATION_MULTI_SOURCE:
        if len(distinct) < 2:
            return 'MULTI_SOURCE_CONFIRMED lacks distinct sources'
        if primary:
            return 'MULTI_SOURCE_CONFIRMED must not have primary_source_url'
    elif status == VERIFICATION_PRIMARY:
        if not primary:
            return 'PRIMARY_SOURCE_VERIFIED requires primary_source_url'

    et = event.get('event_type')
    if not isinstance(et, str) or et not in EVENT_TYPES:
        return 'event event_type unsupported'
    for ts_field in ('published_at', 'first_seen_at', 'last_seen_at', 'created_at', 'updated_at'):
        if not _is_valid_persisted_ts(event.get(ts_field)):
            return f'event {ts_field} malformed'

    try:
        pub = normalize_aware_datetime(event.get('published_at'), field='published_at')
        expected_fp = compute_event_fingerprint(
            symbols=expected_symbols,
            event_type=et,
            structured_facts=expected_facts,
            normalized_headline=expected_norm,
            published_at=pub,
        )
    except BrokerDiscoveryError:
        return 'event fingerprint inputs invalid'
    if event.get('event_fingerprint') != expected_fp:
        return 'event fingerprint incorrect'
    expected_id = _uuid5_from_fingerprint(f'event:{expected_fp}')
    if event.get('event_id') != expected_id or str(key) != expected_id:
        return 'event_id incorrect'
    return None


def _validate_sighting_record(key: str, sighting: Any, events: dict) -> Optional[str]:
    if not isinstance(sighting, dict):
        return 'sighting value is not a dictionary'
    for field in _SIGHTING_REQUIRED:
        if field not in sighting:
            return f'sighting missing field {field}'
    if str(sighting.get('sighting_id') or '') != str(key):
        return 'sighting key/sighting_id mismatch'
    if str(sighting.get('schema_version') or '') != SCHEMA_VERSION:
        return 'sighting schema_version invalid'

    name = sighting.get('source_name')
    if not isinstance(name, str) or not name.strip():
        return 'sighting source_name empty'
    try:
        expected_name = canonical_source_name(name)
    except BrokerDiscoveryError:
        return 'sighting source_name malformed'
    if name != expected_name:
        return 'sighting source_name not canonical'

    headline = sighting.get('source_headline')
    if not isinstance(headline, str) or not headline.strip():
        return 'sighting source_headline empty'
    kind = sighting.get('source_kind')
    if not isinstance(kind, str) or kind not in ALLOWED_SOURCE_KINDS:
        return 'sighting source_kind unsupported'
    url = sighting.get('source_url')
    if not isinstance(url, str):
        return 'sighting source_url must be str'
    try:
        norm_url = normalize_url(url)
    except BrokerDiscoveryError:
        return 'sighting source_url invalid'
    if url != norm_url:
        return 'sighting source_url not canonical'
    if kind != SOURCE_KIND_MANUAL_FEED and not norm_url:
        return 'sighting source_url required for kind'

    try:
        expected_norm = normalize_headline(headline)
    except BrokerDiscoveryError:
        return 'sighting headline malformed'
    if sighting.get('normalized_headline') != expected_norm:
        return 'sighting normalized_headline incorrect'

    publisher = sighting.get('original_publisher')
    if not isinstance(publisher, str):
        return 'sighting original_publisher must be str'
    try:
        expected_pub = normalize_publisher(publisher)
    except BrokerDiscoveryError:
        return 'sighting original_publisher malformed'
    if publisher != expected_pub:
        return 'sighting original_publisher not canonical'

    attr = sighting.get('attribution')
    if not isinstance(attr, str):
        return 'sighting attribution must be str'
    try:
        expected_attr = canonical_attribution(attr)
    except BrokerDiscoveryError:
        return 'sighting attribution malformed'
    if attr != expected_attr:
        return 'sighting attribution not canonical'

    eid = sighting.get('event_id')
    if not isinstance(eid, str) or not eid.strip():
        return 'sighting event_id missing'
    if eid not in events:
        return 'sighting references missing event_id'
    for ts_field in ('source_published_at', 'first_seen_at', 'last_seen_at'):
        if not _is_valid_persisted_ts(sighting.get(ts_field)):
            return f'sighting {ts_field} malformed'

    excerpt = sighting.get('bounded_excerpt')
    if not isinstance(excerpt, str):
        return 'sighting bounded_excerpt must be str'
    try:
        _require_utf8_text(excerpt, field='bounded_excerpt')
    except BrokerDiscoveryError:
        return 'sighting bounded_excerpt malformed'
    if len(excerpt) > MAX_EXCERPT_LENGTH:
        return 'sighting bounded_excerpt too long'
    if _HTML_MARKUP_RE.search(excerpt):
        return 'sighting bounded_excerpt contains markup'

    for bad in _FORBIDDEN_BODY_KEYS:
        if bad == 'article_body':
            if sighting.get('article_body') not in (None, ''):
                return 'sighting retains article_body'
        elif bad in sighting and sighting.get(bad) not in (None, ''):
            return f'sighting retains forbidden key {bad}'

    try:
        pub = normalize_aware_datetime(sighting.get('source_published_at'), field='source_published_at')
        expected_hash = compute_sighting_fingerprint(
            source_name=name,
            source_url=norm_url,
            normalized_headline=expected_norm,
            source_published_at=pub,
            original_publisher=publisher,
        )
    except BrokerDiscoveryError:
        return 'sighting fingerprint inputs invalid'
    if sighting.get('content_hash') != expected_hash:
        return 'sighting content_hash incorrect'
    expected_id = _uuid5_from_fingerprint(f'sighting:{expected_hash}')
    if sighting.get('sighting_id') != expected_id or str(key) != expected_id:
        return 'sighting_id incorrect'
    return None


def _classify_store_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return HEALTH_MALFORMED
    if 'events' not in data or 'sightings' not in data or 'updated_at' not in data:
        return HEALTH_MALFORMED
    if 'schema_version' not in data:
        return HEALTH_MALFORMED
    events = data.get('events')
    sightings = data.get('sightings')
    if not isinstance(events, dict) or not isinstance(sightings, dict):
        return HEALTH_MALFORMED
    schema = data.get('schema_version')
    if schema is None or not isinstance(schema, str) or not schema.strip():
        return HEALTH_MALFORMED
    if schema != SCHEMA_VERSION:
        return HEALTH_MALFORMED
    # Top-level updated_at is a store-contract field: invalid => MALFORMED.
    try:
        validate_persisted_timestamp(data.get('updated_at'), field='updated_at')
    except BrokerDiscoveryError:
        return HEALTH_MALFORMED

    for key, event in events.items():
        try:
            err = _validate_event_record(str(key), event, sightings)
        except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError, OverflowError):
            return HEALTH_PARTIAL
        if err:
            return HEALTH_PARTIAL
    for key, sighting in sightings.items():
        try:
            err = _validate_sighting_record(str(key), sighting, events)
        except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError, OverflowError):
            return HEALTH_PARTIAL
        if err:
            return HEALTH_PARTIAL
    return HEALTH_OK


def load_store() -> tuple[dict[str, Any], str]:
    """Read-only store load. Never creates or writes a store file."""
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


def _save_store(store: dict[str, Any], *, now: datetime) -> None:
    """Internal persistence helper. Not part of the public mutation surface."""
    payload = copy.deepcopy(store)
    payload['schema_version'] = SCHEMA_VERSION
    payload['updated_at'] = _iso(now)
    health = _classify_store_payload(payload)
    if health != HEALTH_OK:
        raise BrokerDiscoveryError(f'refusing to persist unhealthy discovery store: {health}')
    atomic_write_json(store_path(), payload)


def get_store_health() -> dict[str, Any]:
    path = store_path()
    exists = path.is_file()
    store, health = load_store()
    event_count = None
    sighting_count = None
    available = False
    counts_unavailable = health in (HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL)
    if health == HEALTH_OK:
        available = True
        event_count = len(store.get('events') or {})
        sighting_count = len(store.get('sightings') or {})
    elif health == HEALTH_MISSING:
        available = True
        event_count = 0
        sighting_count = 0
        counts_unavailable = False
    return {
        'health': health,
        'available': available,
        'path': str(path),
        'exists': exists,
        'event_count': event_count,
        'sighting_count': sighting_count,
        'schema_version': SCHEMA_VERSION,
        'counts_unavailable': counts_unavailable,
    }


def _require_healthy_store_for_write() -> dict[str, Any]:
    store, health = load_store()
    if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL):
        raise BrokerDiscoveryError(f'discovery store unhealthy: {health}')
    if health == HEALTH_MISSING:
        return _empty_store()
    if health != HEALTH_OK:
        raise BrokerDiscoveryError(f'discovery store unhealthy: {health}')
    return store


def _require_readable_store() -> dict[str, Any]:
    store, health = load_store()
    if health in (HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL):
        raise BrokerDiscoveryError(f'discovery store unhealthy: {health}')
    return store


def _strip_forbidden_body_fields(row: dict[str, Any]) -> None:
    row['article_body'] = None
    for key in _FORBIDDEN_BODY_KEYS:
        if key in row and key != 'article_body':
            del row[key]


def _upsert_event_in_store(
    store: dict[str, Any],
    event: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Mutate store in memory. Does not save. New inserts always DISCOVERY_ONLY."""
    if not isinstance(event, dict):
        raise BrokerDiscoveryError('event must be a dict')
    now_dt = now
    built = build_canonical_event(
        event_type=event.get('event_type'),
        symbols=event.get('symbols'),
        canonical_headline=event.get('canonical_headline'),
        published_at=event.get('published_at'),
        company_names=event.get('company_names'),
        structured_facts=event.get('structured_facts'),
        primary_source_url='',
        verification_status=VERIFICATION_DISCOVERY_ONLY,
        first_seen_at=event.get('first_seen_at'),
        last_seen_at=event.get('last_seen_at') or now_dt,
        source_count=0,
        now=now_dt,
    )
    built['verification_status'] = VERIFICATION_DISCOVERY_ONLY
    built['primary_source_url'] = ''
    built['source_count'] = 0

    events = store.setdefault('events', {})
    existing = events.get(built['event_id'])
    inserted = existing is None
    if existing:
        built['created_at'] = existing.get('created_at') or built['created_at']
        built['first_seen_at'] = existing.get('first_seen_at') or built['first_seen_at']
        built['last_seen_at'] = _iso(now_dt)
        incoming_companies = normalize_company_names(event.get('company_names'))
        existing_companies = normalize_company_names(existing.get('company_names') or [])
        if not incoming_companies:
            built['company_names'] = existing_companies
        else:
            built['company_names'] = normalize_company_names(existing_companies + incoming_companies)
        prev_status = str(existing.get('verification_status') or VERIFICATION_DISCOVERY_ONLY)
        if prev_status == VERIFICATION_PRIMARY:
            built['verification_status'] = VERIFICATION_PRIMARY
            built['primary_source_url'] = str(existing.get('primary_source_url') or '')
        elif prev_status == VERIFICATION_REJECTED:
            built['verification_status'] = VERIFICATION_REJECTED
            built['primary_source_url'] = str(existing.get('primary_source_url') or '')
        else:
            built['verification_status'] = VERIFICATION_DISCOVERY_ONLY
            built['primary_source_url'] = ''
        built['updated_at'] = _iso(now_dt)
        deduplicated = built['event_fingerprint'] == existing.get('event_fingerprint')
        updated = True
    else:
        deduplicated = False
        updated = False
        built['verification_status'] = VERIFICATION_DISCOVERY_ONLY
        built['primary_source_url'] = ''
        built['source_count'] = 0
    events[built['event_id']] = copy.deepcopy(built)
    _recompute_event_verification(store, built['event_id'], now=now_dt)
    built = copy.deepcopy(events[built['event_id']])
    return {
        'inserted': inserted,
        'updated': updated and not inserted,
        'deduplicated': (not inserted) and deduplicated,
        'event_id': built['event_id'],
        'event': built,
    }


def upsert_event(event: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise BrokerDiscoveryError('event must be a dict')
    now_dt = _normalize_operation_now(now)
    store = _require_healthy_store_for_write()
    result = _upsert_event_in_store(store, event, now=now_dt)
    _save_store(store, now=now_dt)
    return result


def _recompute_event_verification(store: dict[str, Any], event_id: str, *, now: datetime) -> None:
    event = (store.get('events') or {}).get(event_id)
    if not event:
        return
    sightings = _linked_sightings(store, event_id)
    event['source_count'] = len(sightings)
    event['updated_at'] = _iso(now)
    status = str(event.get('verification_status') or VERIFICATION_DISCOVERY_ONLY)
    if status in (VERIFICATION_PRIMARY, VERIFICATION_REJECTED):
        return
    distinct_sources = _distinct_normalized_sources(sightings)
    if len(distinct_sources) >= 2:
        event['verification_status'] = VERIFICATION_MULTI_SOURCE
        event['primary_source_url'] = ''
    else:
        event['verification_status'] = VERIFICATION_DISCOVERY_ONLY
        event['primary_source_url'] = ''


def upsert_sighting(
    sighting: dict[str, Any],
    *,
    event: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Idempotently upsert a source sighting with a single atomic store write.

    New linked events always begin DISCOVERY_ONLY. Never auto-promotes to PRIMARY.
    Repeat ingestion preserves an explicit prior attachment unless a new target is supplied.
    """
    if not isinstance(sighting, dict):
        raise BrokerDiscoveryError('sighting must be a dict')
    require_optional_event_payload(event)
    now_dt = _normalize_operation_now(now)

    store = _require_healthy_store_for_write()
    explicit_event_id = ''
    raw_eid = sighting.get('event_id')
    if raw_eid not in (None, ''):
        explicit_event_id = require_external_id(raw_eid, field='event_id')

    built = build_source_sighting(
        source_name=sighting.get('source_name'),
        source_kind=sighting.get('source_kind') or SOURCE_KIND_BROKER_PUBLIC,
        source_url=sighting.get('source_url'),
        source_headline=sighting.get('source_headline'),
        source_published_at=sighting.get('source_published_at'),
        original_publisher=sighting.get('original_publisher'),
        attribution=sighting.get('attribution'),
        bounded_excerpt=sighting.get('bounded_excerpt'),
        event_id='',
        first_seen_at=sighting.get('first_seen_at'),
        last_seen_at=sighting.get('last_seen_at') or now_dt,
        now=now_dt,
    )

    sightings = store.setdefault('sightings', {})
    existing = sightings.get(built['sighting_id'])
    previous_event_id = str((existing or {}).get('event_id') or '').strip()

    if event is not None:
        event_payload = copy.deepcopy(event)
        event_payload['verification_status'] = VERIFICATION_DISCOVERY_ONLY
        event_payload['primary_source_url'] = ''
        if not event_payload.get('published_at'):
            event_payload['published_at'] = built['source_published_at']
        if not event_payload.get('canonical_headline'):
            event_payload['canonical_headline'] = built['source_headline']
        peek = build_canonical_event(
            event_type=event_payload.get('event_type'),
            symbols=event_payload.get('symbols'),
            canonical_headline=event_payload.get('canonical_headline'),
            published_at=event_payload.get('published_at'),
            company_names=event_payload.get('company_names'),
            structured_facts=event_payload.get('structured_facts'),
            verification_status=VERIFICATION_DISCOVERY_ONLY,
            source_count=0,
            now=now_dt,
        )
        prior_row = (store.get('events') or {}).get(peek['event_id'])
        prior_was_primary = bool(
            prior_row and str(prior_row.get('verification_status') or '') == VERIFICATION_PRIMARY
        )
        prior_was_rejected = bool(
            prior_row and str(prior_row.get('verification_status') or '') == VERIFICATION_REJECTED
        )
        ev_result = _upsert_event_in_store(store, event_payload, now=now_dt)
        event_id = ev_result['event_id']
        erow = (store.get('events') or {}).get(event_id)
        if erow is not None:
            if prior_was_primary:
                erow['verification_status'] = VERIFICATION_PRIMARY
                erow['primary_source_url'] = str(prior_row.get('primary_source_url') or '')
            elif prior_was_rejected:
                erow['verification_status'] = VERIFICATION_REJECTED
            elif str(erow.get('verification_status') or '') in (
                VERIFICATION_PRIMARY,
                VERIFICATION_REJECTED,
            ):
                erow['verification_status'] = VERIFICATION_DISCOVERY_ONLY
                erow['primary_source_url'] = ''
    elif explicit_event_id:
        if explicit_event_id not in (store.get('events') or {}):
            raise BrokerDiscoveryError(f'event_id not found: {explicit_event_id}')
        event_id = explicit_event_id
    elif existing and previous_event_id:
        event_id = previous_event_id
    else:
        auto_event = {
            'event_type': sighting.get('event_type') or 'OTHER',
            'symbols': sighting.get('symbols') or [],
            'canonical_headline': built['source_headline'],
            'published_at': built['source_published_at'],
            'company_names': sighting.get('company_names'),
            'structured_facts': sighting.get('structured_facts'),
            'verification_status': VERIFICATION_DISCOVERY_ONLY,
            'primary_source_url': '',
        }
        if not normalize_symbols(auto_event['symbols']):
            raise BrokerDiscoveryError('symbols are required when creating an event from a sighting')
        ev_result = _upsert_event_in_store(store, auto_event, now=now_dt)
        event_id = ev_result['event_id']

    built['event_id'] = event_id
    inserted = existing is None
    if existing:
        built['first_seen_at'] = existing.get('first_seen_at') or built['first_seen_at']
        built['last_seen_at'] = _iso(now_dt)
        if not built.get('attribution'):
            built['attribution'] = existing.get('attribution') or ''
        if not built.get('bounded_excerpt'):
            built['bounded_excerpt'] = existing.get('bounded_excerpt') or ''
        deduplicated = True
        updated = True
    else:
        deduplicated = False
        updated = False

    _strip_forbidden_body_fields(built)
    sightings[built['sighting_id']] = copy.deepcopy(built)

    new_event_id = str(built['event_id'] or '').strip()
    _recompute_event_verification(store, new_event_id, now=now_dt)
    if previous_event_id and previous_event_id != new_event_id:
        _recompute_event_verification(store, previous_event_id, now=now_dt)

    for eid, erow in list((store.get('events') or {}).items()):
        status = str(erow.get('verification_status') or '')
        primary_url = str(erow.get('primary_source_url') or '').strip()
        if status == VERIFICATION_PRIMARY and not primary_url:
            erow['verification_status'] = VERIFICATION_DISCOVERY_ONLY
            _recompute_event_verification(store, eid, now=now_dt)

    _save_store(store, now=now_dt)
    return {
        'inserted': inserted,
        'updated': (not inserted) and updated,
        'deduplicated': (not inserted) and deduplicated,
        'event_id': built['event_id'],
        'sighting_id': built['sighting_id'],
        'sighting': copy.deepcopy(built),
    }


def attach_sighting_to_event(
    sighting_id: str,
    event_id: str,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    sid = require_external_id(sighting_id, field='sighting_id')
    eid = require_external_id(event_id, field='event_id')
    now_dt = _normalize_operation_now(now)
    store = _require_healthy_store_for_write()
    sightings = store.get('sightings') or {}
    events = store.get('events') or {}
    if sid not in sightings:
        raise BrokerDiscoveryError(f'sighting not found: {sid}')
    if eid not in events:
        raise BrokerDiscoveryError(f'event not found: {eid}')
    previous_event_id = str(sightings[sid].get('event_id') or '').strip()
    sightings[sid]['event_id'] = eid
    sightings[sid]['last_seen_at'] = _iso(now_dt)
    _recompute_event_verification(store, eid, now=now_dt)
    if previous_event_id and previous_event_id != eid:
        _recompute_event_verification(store, previous_event_id, now=now_dt)
    _save_store(store, now=now_dt)
    return {
        'sighting_id': sid,
        'event_id': eid,
        'previous_event_id': previous_event_id,
        'verification_status': events[eid].get('verification_status'),
    }


def mark_primary_source_verified(
    event_id: str,
    *,
    primary_source_url: Any,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    eid = require_external_id(event_id, field='event_id')
    now_dt = _normalize_operation_now(now)
    store = _require_healthy_store_for_write()
    events = store.get('events') or {}
    if eid not in events:
        raise BrokerDiscoveryError(f'event not found: {eid}')
    current = str(events[eid].get('verification_status') or '')
    if current == VERIFICATION_REJECTED:
        raise BrokerDiscoveryError('REJECTED events cannot be promoted to PRIMARY_SOURCE_VERIFIED')
    url = normalize_url(primary_source_url)
    if not url:
        raise BrokerDiscoveryError('primary_source_url is required for primary verification')
    events[eid]['verification_status'] = VERIFICATION_PRIMARY
    events[eid]['primary_source_url'] = url
    events[eid]['updated_at'] = _iso(now_dt)
    events[eid]['last_seen_at'] = _iso(now_dt)
    _recompute_event_verification(store, eid, now=now_dt)
    events[eid]['verification_status'] = VERIFICATION_PRIMARY
    events[eid]['primary_source_url'] = url
    _save_store(store, now=now_dt)
    return copy.deepcopy(events[eid])

def get_event(event_id: str) -> Optional[dict[str, Any]]:
    store = _require_readable_store()
    eid = require_external_id(event_id, field='event_id')
    row = (store.get('events') or {}).get(eid)
    return copy.deepcopy(row) if row else None


def get_sighting(sighting_id: str) -> Optional[dict[str, Any]]:
    store = _require_readable_store()
    sid = require_external_id(sighting_id, field='sighting_id')
    row = (store.get('sightings') or {}).get(sid)
    return copy.deepcopy(row) if row else None


def list_event_sightings(event_id: str) -> list[dict[str, Any]]:
    store = _require_readable_store()
    eid = require_external_id(event_id, field='event_id')
    rows = [
        copy.deepcopy(s)
        for s in (store.get('sightings') or {}).values()
        if str(s.get('event_id') or '') == eid
    ]
    rows.sort(key=lambda r: str(r.get('first_seen_at') or ''))
    return rows


def find_events_by_symbol(symbol: str, *, limit: int = 50) -> list[dict[str, Any]]:
    store = _require_readable_store()
    lim = require_query_limit(limit, field='limit')
    sym = normalize_symbol(symbol)
    rows = [
        copy.deepcopy(e)
        for e in (store.get('events') or {}).values()
        if sym in (e.get('symbols') or [])
    ]
    rows.sort(key=lambda r: str(r.get('published_at') or ''), reverse=True)
    return rows[:lim]


def find_events_by_date(date_value: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    store = _require_readable_store()
    lim = require_query_limit(limit, field='limit')
    day = require_query_date(date_value, field='date')
    rows = []
    for e in (store.get('events') or {}).values():
        pub = str(e.get('published_at') or '')
        try:
            edt = normalize_aware_datetime(pub, field='published_at')
        except BrokerDiscoveryError:
            continue
        if edt.date().isoformat() == day:
            rows.append(copy.deepcopy(e))
    rows.sort(key=lambda r: str(r.get('published_at') or ''), reverse=True)
    return rows[:lim]


def find_recent_events(*, limit: int = 50) -> list[dict[str, Any]]:
    store = _require_readable_store()
    lim = require_query_limit(limit, field='limit')
    rows = [copy.deepcopy(e) for e in (store.get('events') or {}).values()]
    rows.sort(key=lambda r: str(r.get('last_seen_at') or r.get('updated_at') or ''), reverse=True)
    return rows[:lim]


def find_event_by_fingerprint(fingerprint: str) -> Optional[dict[str, Any]]:
    store = _require_readable_store()
    fp = require_event_fingerprint(fingerprint, field='fingerprint')
    for e in (store.get('events') or {}).values():
        if str(e.get('event_fingerprint') or '') == fp:
            return copy.deepcopy(e)
    return None
