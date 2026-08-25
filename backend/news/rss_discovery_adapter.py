"""
AstraEdge 52R-A2 — RSS discovery sidecar.

Maps already-fetched news_provider_registry articles into 52R-A1
upsert_sighting payloads. No network, no AI, no scoring, no primary promotion.

Ingest is opt-in at the registry boundary (default false). The only
intended production caller is live_news_tracker.

The batch lock serializes discovery persistence inside one Railway container.
Horizontal multi-replica serialization is out of scope.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from backend.news.broker_discovery_foundation import (
    HEALTH_MALFORMED,
    HEALTH_MISSING,
    HEALTH_OK,
    HEALTH_PARTIAL,
    HEALTH_UNREADABLE,
    SOURCE_KIND_EXCHANGE,
    SOURCE_KIND_NEWS_PUBLISHER,
    BrokerDiscoveryError,
    bound_excerpt,
    build_source_sighting,
    get_sighting,
    get_store_health,
    normalize_aware_datetime,
    normalize_headline,
    normalize_symbols,
    normalize_url,
    upsert_sighting,
)
from backend.news.source_time_provenance import (
    ALLOWED_BASIS,
    HEALTH_MALFORMED as PROVENANCE_MALFORMED,
    HEALTH_UNREADABLE as PROVENANCE_UNREADABLE,
    LOOKUP_PRESENT,
    STATUS_CONFLICT,
    STATUS_FAILED,
    STATUS_IDEMPOTENT,
    STATUS_INSERTED,
    STATUS_LOCK_CONTENDED,
    STATUS_STORE_UNHEALTHY,
    lookup_source_time_provenance,
    record_source_time_provenance,
)
from backend.storage.data_paths import get_data_path

LOCK_ENV = 'RSS_DISCOVERY_LOCK_PATH'
LOCK_RELATIVE = 'rss_discovery_ingest.lock'

EXCHANGE_PROVIDER_IDS = frozenset({'nse_rss', 'bse_rss'})
NEWS_PUBLISHER_PROVIDER_IDS = frozenset({
    'et_markets',
    'ndtv_profit',
    'mint_rss',
    'business_standard',
    'investing_india',
})

UNHEALTHY_SKIP = frozenset({HEALTH_UNREADABLE, HEALTH_MALFORMED, HEALTH_PARTIAL})
FORBIDDEN_PAYLOAD_KEYS = frozenset({
    'article_body', 'full_article', 'html', 'raw_html',
    'cookies', 'auth_token', 'browser_state', 'session',
})

_SKIP_MISSING_URL = 'skip_missing_url'
_SKIP_MISSING_SYMBOLS = 'skip_missing_symbols'
_SKIP_UNSUPPORTED_KIND = 'unsupported_source_kind'
_SKIP_MISSING_HEADLINE = 'skip_missing_headline'
_SKIP_MISSING_SOURCE_NAME = 'skip_missing_source_name'
_SKIP_MISSING_TIMESTAMP = 'skip_missing_timestamp'
_SKIP_MISSING_DISCOVERY_HEADLINE = 'skip_missing_discovery_headline'
_SKIP_MALFORMED = 'skip_malformed'
_SKIP_NOT_DICT = 'skip_not_dict'

NSE_ANNOUNCEMENTS_PROVIDER_ID = 'nse_rss'
MAX_NSE_FILING_SUBJECT_LENGTH = 200
NSE_DISCOVERY_HEADLINE_SEP = ' — '
_NSE_SUBJECT_MARKER_RE = re.compile(
    r'(?i)(?:^|[\s|/;,])SUBJECT\s*:\s*(.+)$',
    flags=re.DOTALL,
)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _empty_stats(**overrides: Any) -> dict[str, Any]:
    stats: dict[str, Any] = {
        'received': 0,
        'eligible': 0,
        'inserted': 0,
        'deduplicated': 0,
        'skipped': 0,
        'errors': 0,
        'skipped_missing_symbols': 0,
        'skipped_missing_url': 0,
        'skipped_unsupported_source_kind': 0,
        'skipped_missing_headline': 0,
        'skipped_missing_source_name': 0,
        'skipped_missing_timestamp': 0,
        'skipped_missing_discovery_headline': 0,
        'skipped_malformed': 0,
        'store_health': None,
        'store_unhealthy': False,
        'lock_contended': False,
        'lock_stale_cleared': False,
        'provenance_inserted': 0,
        'provenance_idempotent': 0,
        'provenance_conflict': 0,
        'provenance_blocked': 0,
    }
    stats.update(overrides)
    return stats


def discovery_lock_path() -> Path:
    override = os.environ.get(LOCK_ENV, '').strip()
    if override:
        return Path(override)
    return get_data_path(LOCK_RELATIVE)


class _BatchLock:
    """Stable-file OS advisory lock. Ownership lives in the kernel, not JSON."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: Optional[int] = None
        # Retained for the public stats shape; advisory locks never delete stale files.
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

                # msvcrt locks a byte range. Seed byte zero before locking so an
                # empty newly-created file has a stable, lockable range.
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

    def _write_metadata(self, *, started_at: Optional[float] = None) -> None:
        """Write diagnostics while held; metadata never grants or revokes ownership."""
        if self._fd is None:
            raise OSError('batch lock is not held')
        payload = json.dumps({
            'pid': os.getpid(),
            'started_at': time.time() if started_at is None else float(started_at),
            'script': 'rss_discovery_adapter',
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


def _strip_simple_html(text: str) -> str:
    return _HTML_TAG_RE.sub(' ', text)


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(' ', text).strip()


def extract_nse_filing_subject(raw_summary: Any) -> Optional[str]:
    """Deterministic SUBJECT: extractor for already-fetched NSE RSS summaries."""
    if raw_summary is None or isinstance(raw_summary, bool):
        return None
    if isinstance(raw_summary, (dict, list, set, tuple, bytes, bytearray, int, float)):
        return None
    if not isinstance(raw_summary, str):
        return None
    text = _collapse_ws(_strip_simple_html(html.unescape(raw_summary)))
    if not text:
        return None
    match = _NSE_SUBJECT_MARKER_RE.search(text)
    if match is None:
        match = re.search(r'(?i)\bSUBJECT\s*:\s*(.+)$', text, flags=re.DOTALL)
    if match is None:
        return None
    subject = _collapse_ws(match.group(1).split('\n', 1)[0])
    if not subject:
        return None
    if '://' in subject or subject.casefold().startswith('www.'):
        return None
    if len(subject) > MAX_NSE_FILING_SUBJECT_LENGTH:
        subject = subject[:MAX_NSE_FILING_SUBJECT_LENGTH].rstrip()
    if not subject:
        return None
    return subject


def _normalized_company_title(company_title: Any) -> Optional[str]:
    if not isinstance(company_title, str):
        return None
    company = _collapse_ws(_strip_simple_html(html.unescape(company_title)))
    return company or None


def _subject_is_safe(subject: str, *, company: str) -> bool:
    if not subject:
        return False
    if '://' in subject or subject.casefold().startswith('www.'):
        return False
    if len(subject) > MAX_NSE_FILING_SUBJECT_LENGTH:
        return False
    try:
        if normalize_headline(subject) == normalize_headline(company):
            return False
    except BrokerDiscoveryError:
        return False
    return True


def build_nse_discovery_headline(company_title: Any, raw_summary: Any) -> Optional[str]:
    """Compose issuer + filing subject. None when the subject is missing/unsafe."""
    company = _normalized_company_title(company_title)
    if company is None:
        return None
    subject = extract_nse_filing_subject(raw_summary)
    if subject is None or not _subject_is_safe(subject, company=company):
        return None
    return f'{company}{NSE_DISCOVERY_HEADLINE_SEP}{subject}'


def validate_nse_discovery_headline(company_title: Any, discovery_headline: Any) -> Optional[str]:
    """
    Accept only a canonical issuer + filing-subject headline.

    Explicit None/empty/non-string is terminal. Truncated description/summary
    is never consulted. Arbitrary non-canonical strings are rejected.
    """
    if not isinstance(discovery_headline, str):
        return None
    composed = _collapse_ws(_strip_simple_html(html.unescape(discovery_headline)))
    if not composed:
        return None
    company = _normalized_company_title(company_title)
    if company is None:
        return None
    try:
        if normalize_headline(composed) == normalize_headline(company):
            return None
    except BrokerDiscoveryError:
        return None
    prefix = f'{company}{NSE_DISCOVERY_HEADLINE_SEP}'
    if not composed.startswith(prefix):
        return None
    subject = composed[len(prefix):].strip()
    if not _subject_is_safe(subject, company=company):
        return None
    expected = f'{company}{NSE_DISCOVERY_HEADLINE_SEP}{subject}'
    if composed != expected:
        return None
    return expected


def resolve_nse_discovery_headline(article: dict[str, Any]) -> Optional[str]:
    """
    Production nse_rss identity uses the explicit registry field only.

    fetch_provider_rss evaluates the FULL raw summary into discovery_headline.
    An explicit None/missing/invalid value is a terminal fail-closed decision
    and must not be reconstructed from truncated description/summary.
    """
    company = article.get('title') or article.get('headline') or ''
    return validate_nse_discovery_headline(company, article.get('discovery_headline'))


def _provider_id(article: dict[str, Any]) -> str:
    return str(article.get('provider_id') or article.get('source_id') or '').strip().lower()


def map_source_kind(provider_id: str) -> Optional[str]:
    pid = str(provider_id or '').strip().lower()
    if pid in EXCHANGE_PROVIDER_IDS:
        return SOURCE_KIND_EXCHANGE
    if pid in NEWS_PUBLISHER_PROVIDER_IDS:
        return SOURCE_KIND_NEWS_PUBLISHER
    return None


def _text_or_none(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (dict, list, set, tuple, bytes, bytearray, int, float)):
        return None
    if not isinstance(value, str):
        return None
    return value


def evaluate_registry_article(article: Any) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """
    Classify one registry article.

    Returns (skip_reason, payload). skip_reason is None when eligible.
    """
    if not isinstance(article, dict):
        return _SKIP_NOT_DICT, None

    kind = map_source_kind(_provider_id(article))
    if kind is None:
        return _SKIP_UNSUPPORTED_KIND, None

    source_name = _text_or_none(article.get('source_name') or article.get('source'))
    if source_name is None or not str(source_name).strip():
        return _SKIP_MISSING_SOURCE_NAME, None

    raw_url = article.get('url')
    if raw_url in (None, ''):
        raw_url = article.get('link')
    url_text = _text_or_none(raw_url)
    if url_text is None or not str(url_text).strip():
        return _SKIP_MISSING_URL, None
    try:
        canon_url = normalize_url(url_text)
    except BrokerDiscoveryError:
        return _SKIP_MISSING_URL, None
    if not canon_url:
        return _SKIP_MISSING_URL, None

    headline = _text_or_none(article.get('title') or article.get('headline'))
    if headline is None or not str(headline).strip():
        return _SKIP_MISSING_HEADLINE, None
    try:
        normalize_headline(headline)
    except BrokerDiscoveryError:
        return _SKIP_MALFORMED, None

    if _provider_id(article) == NSE_ANNOUNCEMENTS_PROVIDER_ID:
        discovery_headline = resolve_nse_discovery_headline(article)
        if discovery_headline is None:
            return _SKIP_MISSING_DISCOVERY_HEADLINE, None
        try:
            normalize_headline(discovery_headline)
        except BrokerDiscoveryError:
            return _SKIP_MISSING_DISCOVERY_HEADLINE, None
        headline = discovery_headline

    published = article.get('published_at')
    if published in (None, ''):
        published = article.get('published')
    # ingested_at is feed-display only and is never read as source publication time.
    if published in (None, '', False, True) or isinstance(published, (dict, list, set, tuple, bytes, bytearray)):
        return _SKIP_MISSING_TIMESTAMP, None
    try:
        normalize_aware_datetime(published, field='published_at')
    except BrokerDiscoveryError:
        return _SKIP_MISSING_TIMESTAMP, None

    raw_symbols = article.get('symbols')
    if raw_symbols in (None, ''):
        raw_symbols = article.get('tickers')
    if raw_symbols in (None, '', [], ()):
        return _SKIP_MISSING_SYMBOLS, None
    try:
        symbols = normalize_symbols(raw_symbols)
    except BrokerDiscoveryError:
        return _SKIP_MISSING_SYMBOLS, None
    if not symbols:
        return _SKIP_MISSING_SYMBOLS, None

    excerpt = article.get('description')
    if excerpt in (None, ''):
        excerpt = article.get('summary') or ''
    if not isinstance(excerpt, str):
        excerpt = ''
    try:
        excerpt = bound_excerpt(excerpt)
    except BrokerDiscoveryError:
        excerpt = ''

    company_names: list[str] = []
    raw_companies = article.get('company_names')
    if isinstance(raw_companies, list) and raw_companies:
        company_names = list(raw_companies)

    payload = {
        'source_name': source_name,
        'source_kind': kind,
        'source_url': canon_url,
        'source_headline': headline,
        'source_published_at': published,
        'original_publisher': source_name,
        'bounded_excerpt': excerpt,
        'symbols': list(symbols),
        'event_type': 'OTHER',
        'structured_facts': {},
        'company_names': company_names,
    }
    for bad in FORBIDDEN_PAYLOAD_KEYS:
        payload.pop(bad, None)
    return None, payload


def article_to_sighting_payload(article: dict) -> Optional[dict[str, Any]]:
    """Return an upsert_sighting payload, or None when the article is ineligible."""
    try:
        _reason, payload = evaluate_registry_article(article)
    except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError, OverflowError):
        return None
    return payload


def _apply_skip(stats: dict[str, Any], reason: str) -> None:
    stats['skipped'] = int(stats['skipped']) + 1
    if reason == _SKIP_MISSING_URL:
        stats['skipped_missing_url'] = int(stats['skipped_missing_url']) + 1
    elif reason == _SKIP_MISSING_SYMBOLS:
        stats['skipped_missing_symbols'] = int(stats['skipped_missing_symbols']) + 1
    elif reason == _SKIP_UNSUPPORTED_KIND:
        stats['skipped_unsupported_source_kind'] = int(stats['skipped_unsupported_source_kind']) + 1
    elif reason == _SKIP_MISSING_HEADLINE:
        stats['skipped_missing_headline'] = int(stats['skipped_missing_headline']) + 1
    elif reason == _SKIP_MISSING_SOURCE_NAME:
        stats['skipped_missing_source_name'] = int(stats['skipped_missing_source_name']) + 1
    elif reason == _SKIP_MISSING_TIMESTAMP:
        stats['skipped_missing_timestamp'] = int(stats['skipped_missing_timestamp']) + 1
    elif reason == _SKIP_MISSING_DISCOVERY_HEADLINE:
        stats['skipped_missing_discovery_headline'] = int(stats['skipped_missing_discovery_headline']) + 1
    elif reason in (_SKIP_MALFORMED, _SKIP_NOT_DICT):
        stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
        stats['errors'] = int(stats['errors']) + 1


def _article_source_time_basis(article: dict[str, Any]) -> Optional[str]:
    basis = article.get('source_time_basis')
    if basis in ALLOWED_BASIS:
        return str(basis)
    return None


def _block_provenance(stats: dict[str, Any]) -> None:
    stats['skipped'] = int(stats['skipped']) + 1
    stats['provenance_blocked'] = int(stats['provenance_blocked']) + 1


def _apply_upsert_result(stats: dict[str, Any], result: dict[str, Any]) -> None:
    if result.get('inserted'):
        stats['inserted'] = int(stats['inserted']) + 1
    elif result.get('deduplicated'):
        stats['deduplicated'] = int(stats['deduplicated']) + 1


def _ingest_eligible_article(
    article: dict[str, Any],
    payload: dict[str, Any],
    stats: dict[str, Any],
) -> None:
    """Prebuild canonical sighting, bind D2P provenance, then maybe A1 upsert."""
    try:
        built = build_source_sighting(
            source_name=payload.get('source_name'),
            source_kind=payload.get('source_kind'),
            source_url=payload.get('source_url'),
            source_headline=payload.get('source_headline'),
            source_published_at=payload.get('source_published_at'),
            original_publisher=payload.get('original_publisher'),
            attribution=payload.get('attribution'),
            bounded_excerpt=payload.get('bounded_excerpt'),
            event_id='',
        )
    except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError, OverflowError):
        stats['errors'] = int(stats['errors']) + 1
        stats['skipped'] = int(stats['skipped']) + 1
        stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
        return

    sighting_id = str(built.get('sighting_id') or '')
    canonical_ts = built.get('source_published_at')
    basis = _article_source_time_basis(article)
    try:
        existing = get_sighting(sighting_id)
    except BrokerDiscoveryError:
        stats['errors'] = int(stats['errors']) + 1
        stats['skipped'] = int(stats['skipped']) + 1
        stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
        return

    lookup = lookup_source_time_provenance(sighting_id)
    lookup_health = str(lookup.get('health') or '')
    sidecar_unhealthy = lookup_health in (PROVENANCE_UNREADABLE, PROVENANCE_MALFORMED)
    sidecar_present = lookup.get('lookup') == LOOKUP_PRESENT and isinstance(lookup.get('entry'), dict)
    entry = lookup.get('entry') if sidecar_present else None
    bound_value = str((entry or {}).get('source_time_value') or '')
    bound_basis = str((entry or {}).get('source_time_basis') or '')
    existing_ts = str((existing or {}).get('source_published_at') or '') if existing else ''

    upsert_payload = dict(payload)
    allow_upsert = False

    if existing is None:
        if sidecar_unhealthy:
            _block_provenance(stats)
            return
        if basis is None or not isinstance(canonical_ts, str):
            _block_provenance(stats)
            return
        recorded = record_source_time_provenance(
            sighting_id=sighting_id,
            source_time_value=canonical_ts,
            source_time_basis=basis,
        )
        status = str(recorded.get('status') or '')
        if status == STATUS_INSERTED:
            stats['provenance_inserted'] = int(stats['provenance_inserted']) + 1
            upsert_payload['source_published_at'] = canonical_ts
            allow_upsert = True
        elif status == STATUS_IDEMPOTENT:
            stats['provenance_idempotent'] = int(stats['provenance_idempotent']) + 1
            bound = str((recorded.get('entry') or {}).get('source_time_value') or canonical_ts)
            rec_basis = str((recorded.get('entry') or {}).get('source_time_basis') or '')
            if bound != canonical_ts or rec_basis != basis:
                stats['provenance_conflict'] = int(stats['provenance_conflict']) + 1
                _block_provenance(stats)
                return
            upsert_payload['source_published_at'] = bound
            allow_upsert = True
        elif status == STATUS_CONFLICT:
            stats['provenance_conflict'] = int(stats['provenance_conflict']) + 1
            _block_provenance(stats)
            return
        elif status in (STATUS_LOCK_CONTENDED, STATUS_STORE_UNHEALTHY, STATUS_FAILED):
            _block_provenance(stats)
            return
        else:
            _block_provenance(stats)
            return
    else:
        # Existing A1 sighting.
        if sidecar_unhealthy:
            upsert_payload['source_published_at'] = existing_ts
            allow_upsert = True
        elif sidecar_present:
            if existing_ts != bound_value:
                # Do not widen or repair an A1/sidecar mismatch.
                _block_provenance(stats)
                return
            upsert_payload['source_published_at'] = bound_value
            incoming_matches = (
                isinstance(canonical_ts, str)
                and canonical_ts == bound_value
                and basis == bound_basis
            )
            if incoming_matches:
                recorded = record_source_time_provenance(
                    sighting_id=sighting_id,
                    source_time_value=bound_value,
                    source_time_basis=bound_basis,
                )
                status = str(recorded.get('status') or '')
                if status == STATUS_IDEMPOTENT:
                    stats['provenance_idempotent'] = int(stats['provenance_idempotent']) + 1
                    allow_upsert = True
                elif status == STATUS_CONFLICT:
                    stats['provenance_conflict'] = int(stats['provenance_conflict']) + 1
                    allow_upsert = True
                elif status in (STATUS_LOCK_CONTENDED, STATUS_STORE_UNHEALTHY, STATUS_FAILED):
                    upsert_payload['source_published_at'] = existing_ts
                    allow_upsert = True
                else:
                    allow_upsert = True
            else:
                stats['provenance_conflict'] = int(stats['provenance_conflict']) + 1
                allow_upsert = True
        else:
            # Historical: A1 exists, sidecar missing. Never create a sidecar row.
            allow_upsert = True

    if not allow_upsert:
        _block_provenance(stats)
        return

    try:
        result = upsert_sighting(upsert_payload)
    except BrokerDiscoveryError:
        stats['errors'] = int(stats['errors']) + 1
        stats['skipped'] = int(stats['skipped']) + 1
        stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
        return
    except (TypeError, ValueError, UnicodeError, OverflowError):
        stats['errors'] = int(stats['errors']) + 1
        stats['skipped'] = int(stats['skipped']) + 1
        stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
        return
    _apply_upsert_result(stats, result)


def ingest_registry_articles(articles: Optional[list[dict]]) -> dict[str, Any]:
    """
    Persist eligible registry articles as DISCOVERY_ONLY sightings.

    Empty/None/all-ineligible batches perform zero writes and do not create
    the discovery store. Unhealthy stores are left byte-identical.
    """
    if articles is None:
        return _empty_stats(received=0, skipped=0)
    if not isinstance(articles, list):
        return _empty_stats(received=0, skipped=1, skipped_malformed=1, errors=1)

    stats = _empty_stats(received=len(articles))
    eligible: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for article in articles:
        try:
            reason, payload = evaluate_registry_article(article)
        except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError, OverflowError):
            _apply_skip(stats, _SKIP_MALFORMED)
            continue
        if reason is not None:
            _apply_skip(stats, reason)
            continue
        if not isinstance(article, dict) or payload is None:
            _apply_skip(stats, _SKIP_MALFORMED)
            continue
        eligible.append((article, payload))

    stats['eligible'] = len(eligible)
    if not eligible:
        return stats

    lock = _BatchLock(discovery_lock_path())
    acquired = False
    try:
        acquired = lock.try_acquire()
        stats['lock_stale_cleared'] = bool(lock.stale_cleared)
        if not acquired:
            stats['lock_contended'] = True
            print('lock_contended=True', flush=True)
            return stats

        health_info = get_store_health()
        health = str(health_info.get('health') or '')
        stats['store_health'] = health
        if health in UNHEALTHY_SKIP:
            stats['store_unhealthy'] = True
            return stats
        if health not in (HEALTH_MISSING, HEALTH_OK):
            stats['store_unhealthy'] = True
            return stats

        for article, payload in eligible:
            _ingest_eligible_article(article, payload, stats)
        return stats
    finally:
        if acquired:
            lock.release()
