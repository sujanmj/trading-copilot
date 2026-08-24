#!/usr/bin/env python3
"""AstraEdge 52R-B2N — NSE authoritative announcements RSS ingest alignment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')
PUB = datetime(2099, 7, 31, 10, 15, 0, tzinfo=IST)
PASS_MARKERS: list[str] = []

ADAPTER_PATH = PROJECT_ROOT / 'backend' / 'news' / 'rss_discovery_adapter.py'
REGISTRY_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'news_provider_registry.py'
VERIFIER_PATH = PROJECT_ROOT / 'backend' / 'news' / 'primary_source_verifier.py'
NSE_WAF_PATH = PROJECT_ROOT / 'backend' / 'collectors' / 'nse_announcements.py'

NSE_ANNOUNCEMENTS_XML = 'https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml'
NSE_DIRECTORY_HTML = 'https://www.nseindia.com/rss-feed'
NSE_STATIC_DIRECTORY = 'https://www.nseindia.com/static/rss-feed'
BSE_NOTICES_XML = 'https://www.bseindia.com/data/xml/notices.xml'
CORPORATE_PDF = 'https://nsearchives.nseindia.com/corporate/VALID1.pdf'
DEBT_PDF = 'https://nsearchives.nseindia.com/content/debt/WDM/DEBT1.pdf'

PRODUCTION_SCAN_SKIP = {VERIFIER_PATH.resolve()}


def _fail(msg: str) -> int:
    print(f'NSE_AUTHORITATIVE_RSS_INGEST_52R_B2N_FAIL: {msg}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


def _git_data_status() -> str:
    proc = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or '').strip()


@contextmanager
def _isolated_discovery():
    from scripts._test_runtime_isolation import isolated_premarket_data_root

    with tempfile.TemporaryDirectory() as td:
        lock_path = Path(td) / 'rss_discovery_ingest.lock'
        with isolated_premarket_data_root() as iso:
            def _temp_data_path(relative: str) -> Path:
                rel = str(relative or '').replace('\\', '/').lstrip('/')
                path = iso['temp_root'] / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                return path

            with patch.dict(os.environ, {'RSS_DISCOVERY_LOCK_PATH': str(lock_path)}, clear=False), patch(
                'backend.news.broker_discovery_foundation.get_data_path',
                side_effect=_temp_data_path,
            ), patch(
                'backend.news.rss_discovery_adapter.get_data_path',
                side_effect=_temp_data_path,
            ):
                yield {
                    'iso': iso,
                    'lock_path': lock_path,
                    'store_path': iso['temp_root'] / 'broker_news_discovery_store.json',
                }


def _reset(ctx: dict) -> None:
    store = ctx['store_path']
    if store.exists():
        store.unlink()
    lock = ctx['lock_path']
    if lock.exists():
        lock.unlink()


def _nse_article(**extra):
    row = {
        'provider_id': 'nse_rss',
        'source_id': 'nse_rss',
        'source_name': 'NSE Corporate Information',
        'url': CORPORATE_PDF,
        'link': CORPORATE_PDF,
        'title': 'Example Industries Limited',
        'headline': 'Example Industries Limited',
        'description': 'Corporate announcement |SUBJECT: Board Meeting Intimation',
        'summary': 'Corporate announcement |SUBJECT: Board Meeting Intimation',
        'published_at': PUB.isoformat(),
        'symbols': ['EXAMP'],
    }
    row.update(extra)
    if 'discovery_headline' not in extra:
        from backend.news.rss_discovery_adapter import build_nse_discovery_headline

        row['discovery_headline'] = build_nse_discovery_headline(
            row.get('title'),
            row.get('description') or row.get('summary') or '',
        )
    return row


def test_build_identity() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    allowed = {('52R-B2N', 'AstraEdge 52R-B2N'), ('52R-B2', 'AstraEdge 52R-B2'), ('52R-C1A', 'AstraEdge 52R-C1A')}
    mismatches = (
        ('52R-B2N', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-B2'),
        ('52R-B2', 'AstraEdge 52R-C1A'),
    )
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed:
        return _fail(
            f'expected exact pair 52R-B2N / AstraEdge 52R-B2N or successor '
            f'52R-B2 / AstraEdge 52R-B2 or 52R-C1A / AstraEdge 52R-C1A, '
            f'got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    print(f'BUILD_PAIR {BUILD_STAGE} / {TELEGRAM_BUILD}')
    return 0


def test_nse_feed_config() -> int:
    from backend.collectors.news_provider_registry import PROVIDER_DEFS

    nse = next((p for p in PROVIDER_DEFS if p.get('source_id') == 'nse_rss'), None)
    if nse is None:
        return _fail('nse_rss provider missing')
    feeds = [str(url) for url, _category in (nse.get('feeds') or [])]
    print(f'NSE_RSS_FEEDS {feeds}')
    if feeds != [NSE_ANNOUNCEMENTS_XML]:
        return _fail(f'nse_rss feeds must be exactly the announcements XML, got {feeds}')
    if NSE_DIRECTORY_HTML in feeds:
        return _fail('nse_rss must not use the HTML RSS directory')
    if NSE_STATIC_DIRECTORY in feeds:
        return _fail('nse_rss must not fetch the static RSS directory at runtime')
    _pass('NSE_AUTHORITATIVE_RSS_CONFIG_OK')
    return 0


def test_bse_unchanged() -> int:
    from backend.collectors.news_provider_registry import PROVIDER_DEFS

    bse = next((p for p in PROVIDER_DEFS if p.get('source_id') == 'bse_rss'), None)
    if bse is None:
        return _fail('bse_rss provider missing')
    feeds = [str(url) for url, _category in (bse.get('feeds') or [])]
    print(f'BSE_RSS_FEEDS {feeds}')
    if feeds != [BSE_NOTICES_XML]:
        return _fail(f'bse_rss must remain notices.xml, got {feeds}')
    _pass('BSE_PRIMARY_BOUNDARY_UNCHANGED_OK')
    return 0


def test_subject_extraction() -> int:
    from backend.news.rss_discovery_adapter import (
        build_nse_discovery_headline,
        extract_nse_filing_subject,
        resolve_nse_discovery_headline,
    )

    company = 'Tata Power Company Limited'
    cases = (
        ('plain', 'Corporate announcement |SUBJECT: Press Release'),
        ('lower', 'Corporate announcement |subject: Press Release'),
        ('upper', 'Corporate announcement |SUBJECT: Press Release'),
        ('spaces', 'Corporate announcement | SUBJECT :   Press Release'),
        ('html', '<p>Corporate announcement |SUBJECT: Press Release</p>'),
    )
    print('SUBJECT_EXTRACTION_TABLE')
    for label, summary in cases:
        subject = extract_nse_filing_subject(summary)
        headline = build_nse_discovery_headline(company, summary)
        print(f'  {label} subject={subject!r} headline={headline!r}')
        if subject != 'Press Release':
            return _fail(f'{label} subject {subject!r}')
        if headline is None or company not in headline or 'Press Release' not in headline:
            return _fail(f'{label} discovery headline {headline!r}')
        if headline == company:
            return _fail(f'{label} used bare company name')

    long_subject = 'X' * 250
    bounded = extract_nse_filing_subject(f'SUBJECT: {long_subject}')
    if bounded is None or len(bounded) > 200:
        return _fail(f'long subject was not bounded: {bounded!r}')
    print(f'BOUNDED_SUBJECT_LEN {len(bounded)}')

    if extract_nse_filing_subject('Corporate announcement |SUBJECT:   ') is not None:
        return _fail('empty subject must fail closed')
    if extract_nse_filing_subject('Corporate announcement without marker') is not None:
        return _fail('missing marker must fail closed')
    if build_nse_discovery_headline(company, 'no marker here') is not None:
        return _fail('missing subject must not compose a headline')

    resolved_bare = resolve_nse_discovery_headline({
        'title': company,
        'discovery_headline': company,
        'description': 'no marker',
    })
    if resolved_bare is not None:
        return _fail('bare-company discovery_headline must fail closed')

    canonical = build_nse_discovery_headline(company, 'Corporate announcement |SUBJECT: Press Release')
    resolved_ok = resolve_nse_discovery_headline({
        'title': company,
        'discovery_headline': canonical,
        'description': 'should be ignored |SUBJECT: Other Subject',
    })
    if resolved_ok != canonical:
        return _fail(f'canonical preset must be accepted, got {resolved_ok!r}')

    resolved_no_field = resolve_nse_discovery_headline({
        'title': company,
        'description': 'Corporate announcement |SUBJECT: Press Release',
        'summary': 'Corporate announcement |SUBJECT: Press Release',
    })
    if resolved_no_field is not None:
        return _fail('missing discovery_headline must not parse truncated description')

    resolved_none = resolve_nse_discovery_headline({
        'title': company,
        'discovery_headline': None,
        'description': 'Corporate announcement |SUBJECT: Press Release',
        'summary': 'Corporate announcement |SUBJECT: Press Release',
    })
    if resolved_none is not None:
        return _fail('explicit None discovery_headline must be terminal')

    resolved_arbitrary = resolve_nse_discovery_headline({
        'title': company,
        'discovery_headline': 'A completely unrelated headline',
    })
    if resolved_arbitrary is not None:
        return _fail('arbitrary discovery_headline must be rejected')
    _pass('NSE_ANNOUNCEMENT_SUBJECT_IDENTITY_OK')
    return 0


def test_same_day_distinct_filings(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY, get_event
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    a = _nse_article(
        url='https://nsearchives.nseindia.com/corporate/EXAMP_BOARD.pdf',
        link='https://nsearchives.nseindia.com/corporate/EXAMP_BOARD.pdf',
        description='Filing |SUBJECT: Board Meeting Intimation',
        summary='Filing |SUBJECT: Board Meeting Intimation',
    )
    b = _nse_article(
        url='https://nsearchives.nseindia.com/corporate/EXAMP_INVESTOR.pdf',
        link='https://nsearchives.nseindia.com/corporate/EXAMP_INVESTOR.pdf',
        description='Filing |SUBJECT: Investor Presentation',
        summary='Filing |SUBJECT: Investor Presentation',
    )
    stats = ingest_registry_articles([a, b])
    if stats.get('inserted') != 2:
        return _fail(f'expected two inserts, got {stats}')
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    sightings = list(store['sightings'].values())
    events = list(store['events'].values())
    headlines = {row['source_headline'] for row in sightings}
    event_ids = {row['event_id'] for row in sightings}
    sighting_ids = set(store['sightings'])
    print(
        'DISTINCT_FILING_EVIDENCE '
        f'sightings={len(sighting_ids)} events={len(event_ids)} headlines={sorted(headlines)}'
    )
    if len(sighting_ids) != 2 or len(event_ids) != 2:
        return _fail('same-company same-day distinct subjects must create two events')
    if len(headlines) != 2:
        return _fail(f'headlines were not distinct: {headlines}')
    joined = ' '.join(headlines)
    if 'Board Meeting Intimation' not in joined or 'Investor Presentation' not in joined:
        return _fail(f'missing filing subjects in {headlines}')
    for ev in events:
        if ev.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail('B2N ingest must not create PRIMARY')
        if ev.get('primary_source_url'):
            return _fail('B2N ingest must not write primary_source_url')
        live = get_event(ev['event_id'])
        if live and live.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail('live event became PRIMARY')
    _pass('NSE_SAME_DAY_DISTINCT_FILINGS_OK')
    return 0


def test_exact_duplicate_idempotent(ctx: dict) -> int:
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    art = _nse_article()
    first = ingest_registry_articles([art])
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    sid = next(iter(store['sightings']))
    eid = next(iter(store['events']))
    second = ingest_registry_articles([art])
    store2 = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    print(
        'DUPLICATE_EVIDENCE '
        f'inserted={first.get("inserted")} deduplicated={second.get("deduplicated")} '
        f'sightings={len(store2["sightings"])} events={len(store2["events"])}'
    )
    if first.get('inserted') != 1:
        return _fail(f'first ingest should insert, got {first}')
    if second.get('deduplicated') != 1 or second.get('inserted') != 0:
        return _fail(f'second ingest should dedupe, got {second}')
    if len(store2['sightings']) != 1 or next(iter(store2['sightings'])) != sid:
        return _fail('duplicate created a new sighting')
    if len(store2['events']) != 1 or next(iter(store2['events'])) != eid:
        return _fail('duplicate created a new event')
    _pass('NSE_EXACT_DUPLICATE_IDEMPOTENT_OK')
    return 0


def test_missing_subject_skipped(ctx: dict) -> int:
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    art = _nse_article(
        description='Corporate announcement without a filing marker',
        summary='Corporate announcement without a filing marker',
    )
    art.pop('discovery_headline', None)
    stats = ingest_registry_articles([art])
    print(
        'MISSING_SUBJECT_EVIDENCE '
        f'inserted={stats.get("inserted")} skipped={stats.get("skipped")} '
        f'reason_count={stats.get("skipped_missing_discovery_headline")}'
    )
    if stats.get('inserted'):
        return _fail('missing SUBJECT must not create a discovery sighting')
    if stats.get('skipped_missing_discovery_headline', 0) < 1:
        return _fail(f'expected skip_missing_discovery_headline, got {stats}')
    if ctx['store_path'].exists():
        return _fail('missing-subject skip must not create a discovery store')
    _pass('NSE_MISSING_SUBJECT_DISCOVERY_SKIPPED_OK')
    return 0


def test_b1_eligible_url_preserved(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY, normalize_url
    from backend.news.primary_source_verifier import classify_exchange_primary_url
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    stats = ingest_registry_articles([_nse_article(url=CORPORATE_PDF, link=CORPORATE_PDF)])
    if stats.get('inserted') != 1:
        return _fail(f'expected insert, got {stats}')
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    sighting = next(iter(store['sightings'].values()))
    event = next(iter(store['events'].values()))
    stored = sighting.get('source_url')
    canonical = normalize_url(CORPORATE_PDF)
    info = classify_exchange_primary_url(stored)
    print(
        f'URL_PRESERVE stored={stored!r} canonical={canonical!r} '
        f'ok={info.get("ok")} reason={info.get("reason")} path={info.get("path")}'
    )
    if stored != canonical:
        return _fail(f'stored source_url {stored!r} != canonical {canonical!r}')
    if info.get('ok') is not True:
        return _fail(f'classifier must accept preserved URL, got {info}')
    if event.get('verification_status') == VERIFICATION_PRIMARY:
        return _fail('URL preservation must not promote PRIMARY')
    _pass('NSE_B1_ELIGIBLE_URL_PRESERVED_OK')
    return 0


def test_debt_path_ineligible(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY
    from backend.news.primary_source_verifier import classify_exchange_primary_url
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    stats = ingest_registry_articles([_nse_article(url=DEBT_PDF, link=DEBT_PDF)])
    if stats.get('inserted') != 1:
        return _fail(f'debt path may be stored as discovery, got {stats}')
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    sighting = next(iter(store['sightings'].values()))
    event = next(iter(store['events'].values()))
    info = classify_exchange_primary_url(sighting.get('source_url'))
    print(
        f'DEBT_PATH stored={sighting.get("source_url")!r} '
        f'ok={info.get("ok")} reason={info.get("reason")} '
        f'status={event.get("verification_status")}'
    )
    if info.get('ok'):
        return _fail('debt path must remain B1-ineligible')
    if info.get('reason') != 'event_path_not_authoritative':
        return _fail(f'expected event_path_not_authoritative, got {info}')
    if event.get('verification_status') == VERIFICATION_PRIMARY:
        return _fail('debt path must not become PRIMARY')
    _pass('NSE_DEBT_PATH_STILL_INELIGIBLE_OK')
    return 0


def _recording_nse_fetch(xml: bytes):
    from backend.collectors.news_provider_registry import PROVIDER_DEFS, fetch_provider_rss

    nse = next(p for p in PROVIDER_DEFS if p.get('source_id') == 'nse_rss')

    class _FakeResponse:
        def __init__(self, url: str):
            self.status_code = 200
            self.content = xml
            self.headers = {'Content-Type': 'application/xml'}
            self.url = url
            self.history = []

    class _RecordingSession:
        def __init__(self):
            self.urls: list[str] = []

        def get(self, url, headers=None, timeout=None):
            self.urls.append(str(url))
            return _FakeResponse(str(url))

    session = _RecordingSession()
    articles, status = fetch_provider_rss(nse, hours_back=24 * 400, max_per_feed=10, session=session)
    return session, articles, status


def test_full_summary_fail_closed_terminal(ctx: dict) -> int:
    from backend.collectors.news_provider_registry import _strip_html
    from backend.news.rss_discovery_adapter import (
        build_nse_discovery_headline,
        ingest_registry_articles,
        resolve_nse_discovery_headline,
    )

    company = 'Example Industries Limited'
    raw_summary = (
        'Corporate announcement |SUBJECT: '
        + ('Safe filing text ' * 24)
        + ' https://example.invalid/document'
    )
    full_headline = build_nse_discovery_headline(company, raw_summary)
    truncated = _strip_html(raw_summary)[:300]
    print(
        f'FULL_SUMMARY_LEN={len(raw_summary)} truncated_len={len(truncated)} '
        f'url_in_full={("://" in raw_summary)} url_in_truncated={("://" in truncated)} '
        f'full_headline={full_headline!r}'
    )
    if full_headline is not None:
        return _fail('full raw summary with URL-like subject must fail closed')
    if '://' not in raw_summary:
        return _fail('fixture must place an unsafe URL in the full summary')
    if '://' in truncated:
        return _fail('truncated description must omit the unsafe URL')
    truncated_rebuild = build_nse_discovery_headline(company, truncated)
    if truncated_rebuild is None:
        return _fail('truncated description would not demonstrate the reviewed fallback bug')

    article = _nse_article(
        title=company,
        headline=company,
        description=truncated,
        summary=truncated,
        discovery_headline=None,
        url=CORPORATE_PDF,
        link=CORPORATE_PDF,
    )
    resolved = resolve_nse_discovery_headline(article)
    if resolved is not None:
        return _fail(f'adapter reconstructed truncated identity: {resolved!r}')

    stats = ingest_registry_articles([article])
    print(
        'TERMINAL_NONE_EVIDENCE '
        f'inserted={stats.get("inserted")} skipped={stats.get("skipped")} '
        f'missing_discovery={stats.get("skipped_missing_discovery_headline")}'
    )
    if stats.get('inserted'):
        return _fail('explicit None discovery_headline must not insert a sighting')
    if stats.get('skipped_missing_discovery_headline', 0) < 1:
        return _fail(f'expected skip_missing_discovery_headline, got {stats}')
    if ctx['store_path'].exists():
        return _fail('terminal fail-closed skip must not create a discovery store')

    parseable = _nse_article(
        discovery_headline=None,
        description='Corporate announcement |SUBJECT: Press Release',
        summary='Corporate announcement |SUBJECT: Press Release',
    )
    stats2 = ingest_registry_articles([parseable])
    if stats2.get('inserted'):
        return _fail('explicit None must remain terminal even when description is parseable')
    if stats2.get('skipped_missing_discovery_headline', 0) < 1:
        return _fail(f'parseable description with None headline must skip, got {stats2}')
    _pass('NSE_FULL_SUMMARY_FAIL_CLOSED_TERMINAL_OK')
    return 0


def test_rss_to_a2_identity_contract(ctx: dict) -> int:
    from backend.collectors.news_provider_registry import dedupe_articles
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY, normalize_url
    from backend.news.primary_source_verifier import classify_exchange_primary_url
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel>'
        '<title>NSE News - Latest Announcements</title>'
        '<item>'
        '<title>Infosys Limited</title>'
        '<link>https://nsearchives.nseindia.com/corporate/INFY1.pdf</link>'
        '<description>Infosys Limited has informed the Exchange |SUBJECT: Board Meeting Intimation</description>'
        '<pubDate>Sun, 24 Aug 2026 06:30:00 GMT</pubDate>'
        '</item>'
        '</channel></rss>'
    ).encode('utf-8')
    session, articles, _status = _recording_nse_fetch(xml)
    if session.urls != [NSE_ANNOUNCEMENTS_XML]:
        return _fail(f'expected one announcements XML GET, got {session.urls}')
    if any('/corporate/' in url or '/api/' in url for url in session.urls):
        return _fail(f'item/document GET occurred: {session.urls}')
    if not articles:
        return _fail('fetch_provider_rss returned no articles')
    fetched = articles[0]
    if fetched.get('url') != 'https://nsearchives.nseindia.com/corporate/INFY1.pdf':
        return _fail(f'entry.link not preserved: {fetched.get("url")!r}')
    discovery = fetched.get('discovery_headline')
    if not isinstance(discovery, str) or 'Board Meeting Intimation' not in discovery:
        return _fail(f'fetch did not set filing-specific discovery_headline: {discovery!r}')
    if fetched.get('title') != 'Infosys Limited':
        return _fail(f'title must remain company name, got {fetched.get("title")!r}')
    if 'INFY' not in [str(s).upper() for s in (fetched.get('symbols') or [])]:
        return _fail(f'production RSS row missing valid ticker, got {fetched.get("symbols")!r}')

    deduped = dedupe_articles(list(articles) + [dict(fetched)])
    if len(deduped) != 1:
        return _fail(f'dedupe_articles should keep one row, got {len(deduped)}')
    if deduped[0].get('discovery_headline') != discovery:
        return _fail('dedupe_articles dropped discovery_headline')
    print(f'DEDUPE_PRESERVED discovery_headline={deduped[0].get("discovery_headline")!r}')

    stats = ingest_registry_articles(deduped)
    if stats.get('inserted') != 1:
        return _fail(f'A2 ingest should insert the production-shaped row, got {stats}')
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    sighting = next(iter(store['sightings'].values()))
    event = next(iter(store['events'].values()))
    canonical = normalize_url('https://nsearchives.nseindia.com/corporate/INFY1.pdf')
    info = classify_exchange_primary_url(sighting.get('source_url'))
    print(
        'RSS_TO_A2_EVIDENCE '
        f'source_url={sighting.get("source_url")!r} headline={sighting.get("source_headline")!r} '
        f'status={event.get("verification_status")} classifier_ok={info.get("ok")}'
    )
    if sighting.get('source_url') != canonical:
        return _fail(f'stored source_url mismatch {sighting.get("source_url")!r}')
    if sighting.get('source_headline') != discovery:
        return _fail(f'stored headline {sighting.get("source_headline")!r} != {discovery!r}')
    if event.get('canonical_headline') != discovery:
        return _fail(f'event canonical_headline {event.get("canonical_headline")!r} != {discovery!r}')
    if info.get('ok') is not True:
        return _fail(f'B1 classifier should accept corporate URL, got {info}')
    if event.get('verification_status') == VERIFICATION_PRIMARY or event.get('primary_source_url'):
        return _fail('e2e ingest must remain non-PRIMARY')
    _pass('NSE_RSS_TO_A2_IDENTITY_CONTRACT_OK')
    return 0


def test_no_item_follow_http() -> int:
    from backend.collectors.news_provider_registry import PROVIDER_DEFS, fetch_provider_rss

    nse = next(p for p in PROVIDER_DEFS if p.get('source_id') == 'nse_rss')
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel>'
        '<title>NSE News - Latest Announcements</title>'
        '<item>'
        '<title>Example Industries Limited</title>'
        '<link>https://nsearchives.nseindia.com/corporate/EXAMP1.pdf</link>'
        '<description>Example Industries Limited has informed the Exchange |SUBJECT: Board Meeting Intimation</description>'
        '<pubDate>Sun, 24 Aug 2026 06:30:00 GMT</pubDate>'
        '</item>'
        '</channel></rss>'
    ).encode('utf-8')

    class _FakeResponse:
        def __init__(self, url: str):
            self.status_code = 200
            self.content = xml
            self.headers = {'Content-Type': 'application/xml'}
            self.url = url
            self.history = []

    class _RecordingSession:
        def __init__(self):
            self.urls: list[str] = []

        def get(self, url, headers=None, timeout=None):
            self.urls.append(str(url))
            return _FakeResponse(str(url))

    session = _RecordingSession()
    articles, status = fetch_provider_rss(nse, hours_back=24 * 400, max_per_feed=10, session=session)
    print(f'NSE_FEED_GETS {session.urls} items={len(articles)} status={status.get("freshness_status")}')
    if session.urls != [NSE_ANNOUNCEMENTS_XML]:
        return _fail(f'expected one announcements XML GET, got {session.urls}')
    forbidden_gets = [
        url for url in session.urls
        if url.rstrip('/') in {
            NSE_DIRECTORY_HTML.rstrip('/'),
            NSE_STATIC_DIRECTORY.rstrip('/'),
        }
        or '/api/' in url
        or '/corporate/' in url
    ]
    if forbidden_gets:
        return _fail(f'unexpected extra GET: {forbidden_gets}')
    if not articles:
        return _fail('mocked announcements XML produced no articles')
    row = articles[0]
    if row.get('url') != 'https://nsearchives.nseindia.com/corporate/EXAMP1.pdf':
        return _fail(f'entry.link was not preserved, got {row.get("url")!r}')
    if row.get('title') != 'Example Industries Limited':
        return _fail(f'user-facing title should remain company name, got {row.get("title")!r}')
    if not row.get('discovery_headline') or 'Board Meeting Intimation' not in str(row.get('discovery_headline')):
        return _fail(f'discovery_headline missing subject: {row.get("discovery_headline")!r}')

    registry_src = REGISTRY_PATH.read_text(encoding='utf-8')
    if NSE_STATIC_DIRECTORY in registry_src:
        return _fail('registry must not fetch the static RSS directory')
    if '/api/corporate-announcements' in registry_src:
        return _fail('registry must not use the hidden NSE announcements API')
    if 'run_nse_tracker' in registry_src:
        return _fail('registry must not call the legacy NSE WAF collector')
    if 'from backend.collectors.nse_announcements' in registry_src:
        return _fail('registry must not import nse_announcements')
    if not NSE_WAF_PATH.is_file():
        return _fail('legacy NSE collector must remain present and unmodified by this test')
    _pass('NSE_RSS_NO_ITEM_FOLLOW_HTTP_OK')
    return 0


def test_primary_promotion_dormant(ctx: dict) -> int:
    from backend.news.broker_discovery_foundation import VERIFICATION_PRIMARY
    from backend.news.rss_discovery_adapter import ingest_registry_articles

    ingest_registry_articles([_nse_article()])
    store = json.loads(ctx['store_path'].read_text(encoding='utf-8'))
    for event in store['events'].values():
        if event.get('verification_status') == VERIFICATION_PRIMARY:
            return _fail('B2N ingest created PRIMARY')
        if event.get('primary_source_url'):
            return _fail('B2N ingest wrote primary_source_url')

    for path in (ADAPTER_PATH, REGISTRY_PATH):
        src = path.read_text(encoding='utf-8')
        if 'verify_linked_primary_sighting' in src or 'mark_primary_source_verified' in src:
            return _fail(f'{path.name} must not call B1 mutation APIs')
        if 'PRIMARY_SOURCE_VERIFIED' in src:
            return _fail(f'{path.name} must not write PRIMARY_SOURCE_VERIFIED')

    hits: list[str] = []
    for path in (PROJECT_ROOT / 'backend').rglob('*.py'):
        if path.resolve() in PRODUCTION_SCAN_SKIP:
            continue
        text = path.read_text(encoding='utf-8')
        if 'verify_linked_primary_sighting' in text:
            hits.append(str(path.relative_to(PROJECT_ROOT)).replace('\\', '/'))
    allowed_successor = ['backend/news/automatic_primary_verification.py']
    if hits != allowed_successor:
        return _fail(f'unexpected production callers of B1 verifier: {hits}')
    print('B2N_PRODUCTION_B1_CALLERS successor=backend/news/automatic_primary_verification.py')
    _pass('B2N_PRIMARY_PROMOTION_DORMANT_OK')
    return 0


def test_repo_data_safe() -> int:
    status = _git_data_status()
    if status:
        return _fail(f'repository data/ is dirty: {status}')
    _pass('B2N_REPO_DATA_SAFE_OK')
    return 0


def main() -> int:
    tests_no_ctx = (
        test_build_identity,
        test_nse_feed_config,
        test_bse_unchanged,
        test_subject_extraction,
        test_no_item_follow_http,
        test_repo_data_safe,
    )
    for fn in tests_no_ctx:
        rc = fn()
        if rc:
            return rc

    ctx_tests = (
        test_same_day_distinct_filings,
        test_exact_duplicate_idempotent,
        test_missing_subject_skipped,
        test_full_summary_fail_closed_terminal,
        test_b1_eligible_url_preserved,
        test_debt_path_ineligible,
        test_rss_to_a2_identity_contract,
        test_primary_promotion_dormant,
    )
    with _isolated_discovery() as ctx:
        for fn in ctx_tests:
            _reset(ctx)
            rc = fn(ctx)
            if rc:
                return rc

    required = (
        'NSE_AUTHORITATIVE_RSS_CONFIG_OK',
        'BSE_PRIMARY_BOUNDARY_UNCHANGED_OK',
        'NSE_ANNOUNCEMENT_SUBJECT_IDENTITY_OK',
        'NSE_SAME_DAY_DISTINCT_FILINGS_OK',
        'NSE_EXACT_DUPLICATE_IDEMPOTENT_OK',
        'NSE_MISSING_SUBJECT_DISCOVERY_SKIPPED_OK',
        'NSE_B1_ELIGIBLE_URL_PRESERVED_OK',
        'NSE_DEBT_PATH_STILL_INELIGIBLE_OK',
        'NSE_RSS_NO_ITEM_FOLLOW_HTTP_OK',
        'NSE_FULL_SUMMARY_FAIL_CLOSED_TERMINAL_OK',
        'NSE_RSS_TO_A2_IDENTITY_CONTRACT_OK',
        'B2N_PRIMARY_PROMOTION_DORMANT_OK',
    )
    missing = [m for m in required if m not in PASS_MARKERS]
    if missing:
        return _fail(f'missing markers: {missing}')
    print('NSE_AUTHORITATIVE_RSS_INGEST_52R_B2N_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
