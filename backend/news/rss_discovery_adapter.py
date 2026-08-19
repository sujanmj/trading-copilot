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

import json
import os
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
    get_store_health,
    normalize_aware_datetime,
    normalize_headline,
    normalize_symbols,
    normalize_url,
    upsert_sighting,
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
_SKIP_MALFORMED = 'skip_malformed'
_SKIP_NOT_DICT = 'skip_not_dict'


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
        'skipped_malformed': 0,
        'store_health': None,
        'store_unhealthy': False,
        'lock_contended': False,
        'lock_stale_cleared': False,
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

    published = article.get('published_at')
    if published in (None, ''):
        published = article.get('published')
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
    elif reason in (_SKIP_MALFORMED, _SKIP_NOT_DICT):
        stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
        stats['errors'] = int(stats['errors']) + 1


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
    eligible: list[dict[str, Any]] = []
    for article in articles:
        try:
            reason, payload = evaluate_registry_article(article)
        except (BrokerDiscoveryError, TypeError, ValueError, UnicodeError, OverflowError):
            _apply_skip(stats, _SKIP_MALFORMED)
            continue
        if reason is not None:
            _apply_skip(stats, reason)
            continue
        eligible.append(payload)  # type: ignore[arg-type]

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

        for payload in eligible:
            try:
                result = upsert_sighting(payload)
            except BrokerDiscoveryError:
                stats['errors'] = int(stats['errors']) + 1
                stats['skipped'] = int(stats['skipped']) + 1
                stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
                continue
            except (TypeError, ValueError, UnicodeError, OverflowError):
                stats['errors'] = int(stats['errors']) + 1
                stats['skipped'] = int(stats['skipped']) + 1
                stats['skipped_malformed'] = int(stats['skipped_malformed']) + 1
                continue
            if result.get('inserted'):
                stats['inserted'] = int(stats['inserted']) + 1
            elif result.get('deduplicated'):
                stats['deduplicated'] = int(stats['deduplicated']) + 1
        return stats
    finally:
        if acquired:
            lock.release()
