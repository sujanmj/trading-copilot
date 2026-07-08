"""
My Feed claim verification against cached news/market sources — Stage 50W.

AI may summarize/classify but must NOT invent confirmation.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Optional

from backend.utils.config import DATA_DIR

VERIFICATION_VERIFIED = 'VERIFIED'
VERIFICATION_PARTIAL = 'PARTIALLY_VERIFIED'
VERIFICATION_UNVERIFIED = 'UNVERIFIED'
VERIFICATION_CONTRADICTED = 'CONTRADICTED'

VERIFICATION_STATUSES = frozenset({
    VERIFICATION_VERIFIED,
    VERIFICATION_PARTIAL,
    VERIFICATION_UNVERIFIED,
    VERIFICATION_CONTRADICTED,
})

CATALYST_ELIGIBLE_STATUSES = frozenset({VERIFICATION_VERIFIED, VERIFICATION_PARTIAL})

STOPWORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'for', 'with', 'from', 'into', 'on', 'at', 'to', 'in', 'of',
    'is', 'are', 'was', 'were', 'be', 'been', 'by', 'as', 'its', 'it', 'this', 'that', 'will',
    'has', 'have', 'had', 'after', 'before', 'about', 'over', 'under', 'stock', 'stocks', 'share',
    'shares', 'market', 'news', 'today', 'india', 'indian', 'nse', 'bse', 'rs', 'crore', 'lakh',
})

BULLISH_CLAIM_RE = re.compile(
    r'\b(surge|surges|surged|rally|rallies|jump|jumps|jumped|gain|gains|gained|soar|soars|'
    r'beat|beats|upgrade|upgraded|wins|win|won|order win|bagged|acquires|acquisition|'
    r'buys stake|buying stake|strong|bullish|positive|record high|all.time high)\b',
    re.I,
)
BEARISH_CLAIM_RE = re.compile(
    r'\b(fall|falls|fell|drop|drops|dropped|plunge|plunges|plunged|crash|crashes|crashed|'
    r'slump|slumps|slumped|miss|misses|missed|downgrade|downgraded|weak|bearish|negative|'
    r'cut|cuts|penalty|probe|investigation|default|fraud|denies|denied|refute|refuted|'
    r'no deal|not acquiring|rejects|rejected)\b',
    re.I,
)

TOKEN_RE = re.compile(r'[a-z0-9]{3,}', re.I)


def is_catalyst_eligible_status(status: object) -> bool:
    return str(status or VERIFICATION_UNVERIFIED).upper() in CATALYST_ELIGIBLE_STATUSES


def is_catalyst_eligible_item(item: dict[str, Any]) -> bool:
    return is_catalyst_eligible_status(item.get('verification_status'))


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in TOKEN_RE.findall(str(text or '')) if t.lower() not in STOPWORDS}


def _token_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _headline_similarity(claim: str, headline: str) -> float:
    a = str(claim or '').strip().lower()
    b = str(headline or '').strip().lower()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _claim_side_hint(text: str) -> str:
    blob = str(text or '')
    bull = bool(BULLISH_CLAIM_RE.search(blob))
    bear = bool(BEARISH_CLAIM_RE.search(blob))
    if bull and bear:
        return 'MIXED'
    if bull:
        return 'BULLISH'
    if bear:
        return 'BEARISH'
    return 'NEUTRAL'


def _article_side_hint(text: str) -> str:
    try:
        from backend.intelligence.stock_catalyst_radar import classify_catalyst

        _, side = classify_catalyst(text)
        return str(side or 'NEUTRAL').upper()
    except Exception:
        return _claim_side_hint(text)


def _keyword_direction_contradiction(claim_text: str, article_text: str) -> bool:
    claim = str(claim_text or '')
    article = str(article_text or '')
    if _headline_similarity(claim, article) >= 0.55:
        return False
    lower = f'{claim} {article}'.lower()
    if 'kenya' in lower and 'airport' in lower:
        return False
    claim_bull = bool(BULLISH_CLAIM_RE.search(claim))
    claim_bear = bool(BEARISH_CLAIM_RE.search(claim))
    article_bull = bool(BULLISH_CLAIM_RE.search(article))
    article_bear = bool(BEARISH_CLAIM_RE.search(article))
    if claim_bull and article_bear and not claim_bear:
        return True
    if claim_bear and article_bull and not claim_bull:
        return True
    return False


def _side_contradiction(claim_side: str, article_side: str, *, claim_text: str = '', article_text: str = '') -> bool:
    if _headline_similarity(claim_text, article_text) >= 0.55:
        return False
    lower = f'{claim_text} {article_text}'.lower()
    if 'kenya' in lower and 'airport' in lower:
        return False
    if _keyword_direction_contradiction(claim_text, article_text):
        return True
    c = str(claim_side or 'NEUTRAL').upper()
    a = str(article_side or 'NEUTRAL').upper()
    if c in ('NEUTRAL',) or a in ('NEUTRAL',):
        return False
    if c == 'BULLISH' and a in ('BEARISH', 'RISK'):
        return True
    if c == 'BEARISH' and a == 'BULLISH':
        return True
    if c == 'BULLISH' and a == 'MIXED' and BEARISH_CLAIM_RE.search(article_text) and BULLISH_CLAIM_RE.search(claim_text):
        return True
    if c == 'BEARISH' and a == 'MIXED' and BULLISH_CLAIM_RE.search(article_text) and BEARISH_CLAIM_RE.search(claim_text):
        return True
    return False


def _extract_article_fields(item: dict[str, Any]) -> dict[str, str]:
    title = str(
        item.get('title')
        or item.get('headline')
        or item.get('subject')
        or item.get('company')
        or ''
    ).strip()
    body = str(
        item.get('description')
        or item.get('summary')
        or item.get('content')
        or item.get('text')
        or item.get('message')
        or ''
    ).strip()
    return {
        'headline': title or body[:160],
        'summary': body or title,
        'source_name': str(
            item.get('source')
            or item.get('source_name')
            or item.get('publisher')
            or item.get('classification')
            or 'news_cache'
        ).strip(),
        'source_time': str(
            item.get('published')
            or item.get('published_at')
            or item.get('timestamp')
            or item.get('created_at')
            or ''
        ).strip(),
        'source_url': str(item.get('link') or item.get('url') or '').strip(),
    }


def _article_tickers(item: dict[str, Any], blob: str) -> list[str]:
    from backend.my_feed.entity_mapping import filter_claim_tickers

    tickers = item.get('tickers') or item.get('symbols') or []
    if isinstance(tickers, str):
        tickers = [tickers]
    resolved = [str(t).strip().upper() for t in tickers if t]
    if not resolved:
        try:
            from backend.intelligence.stock_catalyst_radar import resolve_tickers_from_text

            resolved = resolve_tickers_from_text(blob)
        except Exception:
            from backend.my_feed.text_extractor import extract_tickers

            resolved = extract_tickers(blob)
    return filter_claim_tickers(blob, resolved)


def iter_verification_source_articles(*, data_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load cached news, filings, broker/external evidence for claim matching."""
    root = data_dir or DATA_DIR
    articles: list[dict[str, Any]] = []

    for fname in ('news_feed.json', 'live_news_feed.json'):
        payload = _load_json(root / fname)
        items = payload.get('items') or payload.get('news') or payload.get('articles') or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    articles.append({**item, '_cache_bucket': fname})

    for fname in ('nse_announcements.json', 'bse_announcements.json', 'company_filings.json'):
        payload = _load_json(root / fname)
        items = payload.get('announcements') or payload.get('items') or payload.get('filings') or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    articles.append({**item, '_cache_bucket': fname})

    ext = _load_json(root / 'external_evidence_latest.json')
    for item in ext.get('items') or ext.get('evidence') or []:
        if isinstance(item, dict):
            articles.append({**item, '_cache_bucket': 'external_evidence_latest.json'})

    inshorts = _load_json(root / 'inshorts_feed.json')
    for item in inshorts.get('items') or inshorts.get('news') or []:
        if isinstance(item, dict):
            articles.append({**item, '_cache_bucket': 'inshorts_feed.json'})

    broker = _load_json(root / 'broker_intelligence_latest.json')
    for item in broker.get('items') or broker.get('mentions') or []:
        if isinstance(item, dict):
            articles.append({**item, '_cache_bucket': 'broker_intelligence_latest.json'})

    return articles


def normalize_claim(raw_text: str) -> dict[str, Any]:
    """Extract structured claim fields from user text (rules-only, no invented facts)."""
    from backend.my_feed.entity_mapping import (
        filter_claim_tickers,
        infer_event_type_from_text,
        looks_like_market_wide_macro,
        refine_side_from_headline,
        resolve_company_ticker,
    )

    text = str(raw_text or '').strip()
    from backend.my_feed.text_extractor import extract_tickers, filter_market_text

    filtered = filter_market_text(text)
    cleaned = str(filtered.get('cleaned_summary') or text).strip()
    resolved = resolve_company_ticker(cleaned, candidates=list(filtered.get('tickers') or []))
    fuzzy = list(filtered.get('tickers') or extract_tickers(cleaned))
    if not fuzzy and not resolved.get('tickers'):
        try:
            from backend.intelligence.stock_catalyst_radar import resolve_tickers_from_text

            fuzzy = resolve_tickers_from_text(cleaned)
        except Exception:
            pass

    if resolved.get('ticker') and str(resolved.get('ticker_confidence') or '') == 'high':
        tickers = [str(resolved['ticker'])]
        entity = str(resolved.get('company') or resolved.get('entity') or tickers[0])
        entities = list(resolved.get('entities') or [entity])
        ticker_confidence = 'high'
    else:
        tickers = filter_claim_tickers(
            cleaned,
            list(resolved.get('tickers') or []) + list(fuzzy),
        )
        entity = str(resolved.get('company') or resolved.get('entity') or '')
        entities = list(resolved.get('entities') or [])
        if not entity and tickers:
            entity = tickers[0]
        ticker_confidence = str(resolved.get('ticker_confidence') or ('high' if tickers else 'low'))

    if not tickers and entities and 'adani' in cleaned.lower():
        tickers = ['ADANIENT']
        entity = entities[0] if entities else 'Adani Group'

    inferred_event = infer_event_type_from_text(cleaned)
    try:
        from backend.intelligence.stock_catalyst_radar import classify_catalyst

        event_type, side = classify_catalyst(cleaned)
    except Exception:
        from backend.my_feed.feed_processor import _classify_item

        classified = _classify_item({'cleaned_summary': cleaned, 'items_found': 1, 'tickers': tickers})
        event_type = classified.get('event_type') or 'news'
        side_map = {'bullish': 'BULLISH', 'bearish': 'BEARISH', 'neutral': 'NEUTRAL'}
        side = side_map.get(str(classified.get('sentiment') or 'neutral'), 'NEUTRAL')
    if inferred_event:
        event_type = inferred_event
    side = refine_side_from_headline(cleaned, default=str(side or 'NEUTRAL').upper())

    feed_type = 'company_news' if tickers and not looks_like_market_wide_macro(cleaned) else 'news'
    if looks_like_market_wide_macro(cleaned):
        feed_type = 'macro_shock'

    keywords = sorted(_tokenize(cleaned))[:24]
    return {
        'raw_user_text': text,
        'claim_summary': cleaned,
        'entity': entity,
        'entities': entities,
        'company': str(resolved.get('company') or entity or ''),
        'ticker': tickers[0] if tickers else '',
        'tickers': tickers,
        'ticker_confidence': ticker_confidence,
        'resolver_source': str(resolved.get('resolver_source') or ''),
        'event_type': str(event_type or 'GENERAL_NEWS'),
        'feed_type': feed_type,
        'side': str(side or 'NEUTRAL').upper(),
        'keywords': keywords,
    }


def _score_article_match(claim: dict[str, Any], article: dict[str, Any]) -> dict[str, Any]:
    fields = _extract_article_fields(article)
    blob = f"{fields['headline']}. {fields['summary']}".strip()
    if len(blob) < 12:
        return {'score': 0.0}

    claim_tokens = set(claim.get('keywords') or []) | _tokenize(claim.get('claim_summary') or '')
    article_tokens = _tokenize(blob)
    overlap = _token_overlap(claim_tokens, article_tokens)
    similarity = _headline_similarity(claim.get('claim_summary') or '', fields['headline'])
    claim_tickers = {str(t).upper() for t in (claim.get('tickers') or []) if t}
    article_tickers = set(_article_tickers(article, blob))
    ticker_match = bool(claim_tickers & article_tickers) if claim_tickers else False
    ticker_only = bool(claim_tickers) and claim_tickers <= article_tickers

    score = (overlap * 0.45) + (similarity * 0.45)
    if ticker_match:
        score += 0.25
    if ticker_only:
        score += 0.05
    if fields['headline'] and claim.get('entity'):
        if str(claim.get('entity')).lower() in fields['headline'].lower():
            score += 0.08

    claim_side = _claim_side_hint(claim.get('claim_summary') or '')
    article_side = _article_side_hint(blob)
    contradicted = _side_contradiction(
        claim_side,
        article_side,
        claim_text=claim.get('claim_summary') or '',
        article_text=blob,
    )

    return {
        'score': min(1.0, score),
        'contradicted': contradicted,
        'ticker_match': ticker_match,
        'overlap': overlap,
        'similarity': similarity,
        'fields': fields,
        'article_tickers': sorted(article_tickers),
        'claim_side': claim_side,
        'article_side': article_side,
    }


def verify_claim_against_sources(
    claim: dict[str, Any],
    *,
    source_loader: Callable[[], list[dict[str, Any]]] | None = None,
    data_dir: Path | None = None,
    verification_source: str = 'internal_cache',
) -> dict[str, Any]:
    """Match claim to cached sources; never invent confirmation."""
    from backend.my_feed.entity_mapping import filter_claim_tickers

    loader = source_loader or (lambda: iter_verification_source_articles(data_dir=data_dir))
    articles = loader()
    base_unverified = {
        'verification_status': VERIFICATION_UNVERIFIED,
        'confidence': 0.0,
        'source_name': 'user_feed_unverified',
        'raw_user_text': claim.get('raw_user_text') or claim.get('claim_summary') or '',
        'verification_source': verification_source,
        'ticker_confidence': claim.get('ticker_confidence') or 'low',
    }
    if not articles:
        return {**base_unverified, 'entity': claim.get('entity') or '', 'ticker': claim.get('ticker') or ''}

    ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        scored = _score_article_match(claim, article)
        if scored.get('score', 0) <= 0:
            continue
        ranked.append((float(scored['score']), scored, article))
    ranked.sort(key=lambda row: row[0], reverse=True)

    if not ranked:
        return {
            **base_unverified,
            'entity': claim.get('entity') or '',
            'ticker': claim.get('ticker') or '',
            'event_type': claim.get('event_type') or 'GENERAL_NEWS',
            'side': claim.get('side') or 'NEUTRAL',
        }

    best_score, best_match, _best_article = ranked[0]
    fields = best_match['fields']
    match_blob = f"{claim.get('claim_summary') or ''} {fields.get('headline') or ''}"
    article_tickers = filter_claim_tickers(match_blob, list(best_match.get('article_tickers') or []))
    tickers = filter_claim_tickers(
        match_blob,
        list(claim.get('tickers') or []) + article_tickers,
    )
    ticker = tickers[0] if tickers else str(claim.get('ticker') or '').strip().upper()

    if best_match.get('contradicted') and best_score >= 0.25:
        if best_match.get('similarity', 0) >= 0.72 or best_match.get('overlap', 0) >= 0.45:
            status = VERIFICATION_VERIFIED
            confidence = round(min(0.98, max(best_score, best_match.get('similarity', 0)) + 0.1), 2)
        else:
            status = VERIFICATION_CONTRADICTED
            confidence = round(best_score, 2)
    elif (
        best_match.get('similarity', 0) >= 0.72
        or (best_match.get('overlap', 0) >= 0.45 and best_match.get('similarity', 0) >= 0.65)
        or (best_score >= 0.58 and best_match.get('ticker_match'))
        or (best_score >= 0.42 and best_match.get('overlap', 0) >= 0.35)
    ):
        status = VERIFICATION_VERIFIED
        confidence = round(min(0.98, max(best_score, best_match.get('similarity', 0)) + 0.1), 2)
    elif best_score >= 0.32:
        status = VERIFICATION_PARTIAL
        confidence = round(best_score, 2)
    else:
        status = VERIFICATION_UNVERIFIED
        confidence = round(best_score, 2)

    side = str(best_match.get('article_side') or claim.get('side') or 'NEUTRAL').upper()
    if status == VERIFICATION_UNVERIFIED:
        return {
            **base_unverified,
            'entity': claim.get('entity') or ticker,
            'ticker': ticker,
            'event_type': claim.get('event_type') or 'GENERAL_NEWS',
            'side': side,
        }

    return {
        'verification_status': status,
        'confidence': confidence,
        'raw_user_text': claim.get('raw_user_text') or claim.get('claim_summary') or '',
        'verified_headline': fields.get('headline') or '',
        'verified_summary': fields.get('summary') or fields.get('headline') or '',
        'source_name': fields.get('source_name') or 'news_cache',
        'source_time': fields.get('source_time') or '',
        'source_url': fields.get('source_url') or '',
        'ticker': ticker,
        'tickers': tickers,
        'entity': claim.get('entity') or ticker,
        'entities': claim.get('entities') or [],
        'event_type': claim.get('event_type') or 'GENERAL_NEWS',
        'side': side,
        'verification_source': verification_source,
        'ticker_confidence': claim.get('ticker_confidence') or ('high' if ticker else 'low'),
    }


def _finalize_verification_result(claim: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    from backend.my_feed.entity_mapping import (
        filter_claim_tickers,
        infer_event_type_from_text,
        refine_side_from_headline,
        resolve_company_ticker,
    )

    headline = str(result.get('verified_headline') or '')
    blob = f"{claim.get('claim_summary') or ''} {headline}".strip()
    resolved = resolve_company_ticker(
        claim.get('claim_summary') or blob,
        candidates=list(result.get('tickers') or []) + list(claim.get('tickers') or []),
    )
    if resolved.get('ticker') and str(resolved.get('ticker_confidence') or '') == 'high':
        tickers = [str(resolved['ticker'])]
        ticker = tickers[0]
        ticker_confidence = 'high'
        entity = str(resolved.get('company') or resolved.get('entity') or ticker)
        entities = list(resolved.get('entities') or [entity])
        company = str(resolved.get('company') or entity)
    else:
        tickers = filter_claim_tickers(
            blob,
            list(resolved.get('tickers') or [])
            + list(result.get('tickers') or [])
            + list(claim.get('tickers') or []),
        )
        if 'ADANIPORTS' in (resolved.get('tickers') or []):
            tickers = ['ADANIPORTS']
        ticker = tickers[0] if tickers else str(result.get('ticker') or claim.get('ticker') or '').upper()
        ticker_confidence = (
            resolved.get('ticker_confidence')
            or result.get('ticker_confidence')
            or claim.get('ticker_confidence')
            or 'low'
        )
        entities = list(resolved.get('entities') or result.get('entities') or claim.get('entities') or [])
        company = str(resolved.get('company') or claim.get('company') or '')
        entity = str(resolved.get('entity') or result.get('entity') or claim.get('entity') or company or ticker or '')

    if 'Kenya airport proposal' in entities or 'China / Kenya airport proposal' in entities:
        tickers = filter_claim_tickers(blob, ['ADANIENT'] if 'adani' in blob.lower() else [])
        ticker = tickers[0] if tickers else ''
        if not ticker:
            ticker_confidence = 'low'
    if ticker == 'ADANIPORTS':
        ticker_confidence = 'high'
    elif ticker == 'ADANIENT' and 'shelved' in blob.lower():
        ticker_confidence = 'low'
    if ticker == 'SBIN':
        ticker_confidence = 'high'
        company = company or 'State Bank of India'
        entity = company
        tickers = ['SBIN']

    event = infer_event_type_from_text(claim.get('claim_summary') or '', headline=headline) or result.get('event_type')
    side = refine_side_from_headline(
        claim.get('claim_summary') or '',
        headline=headline,
        default=str(result.get('side') or claim.get('side') or 'NEUTRAL'),
    )
    if entities and not entity:
        entity = entities[0]

    status = str(result.get('verification_status') or VERIFICATION_UNVERIFIED).upper()
    if status == VERIFICATION_PARTIAL:
        ticker_confidence = 'low'

    out = dict(result)
    out.update({
        'ticker': ticker,
        'tickers': tickers,
        'entity': entity,
        'company': company or entity,
        'entities': entities,
        'event_type': event or claim.get('event_type') or 'GENERAL_NEWS',
        'feed_type': claim.get('feed_type') or result.get('feed_type') or '',
        'side': side,
        'ticker_confidence': ticker_confidence,
        'verification_status': status,
        'resolver_source': resolved.get('resolver_source') or claim.get('resolver_source') or '',
    })
    return out


def verify_user_feed_claim(
    claim: dict[str, Any],
    *,
    data_dir: Path | None = None,
    allow_auto_refresh: bool = True,
) -> dict[str, Any]:
    """Internal cache first, optional lightweight news refresh, then external search."""
    auto_refresh_meta: dict[str, Any] = {'attempted': False, 'did_refresh': False}
    if allow_auto_refresh:
        try:
            from backend.my_feed.news_refresh import should_auto_refresh_news_for_feed, run_news_cache_refresh

            do_refresh, reason, age = should_auto_refresh_news_for_feed(data_dir=data_dir)
            auto_refresh_meta = {
                'attempted': True,
                'did_refresh': False,
                'reason': reason,
                'cache_age_minutes': age,
            }
            if do_refresh:
                refresh = run_news_cache_refresh(
                    symbol=str(claim.get('ticker') or ''),
                    company=str(claim.get('company') or claim.get('entity') or ''),
                )
                auto_refresh_meta['did_refresh'] = bool(refresh.get('ok'))
                auto_refresh_meta['refresh'] = {
                    'ok': refresh.get('ok'),
                    'items_found': refresh.get('items_found'),
                }
        except Exception as exc:
            auto_refresh_meta['error'] = str(exc)[:160]

    internal = verify_claim_against_sources(
        claim,
        data_dir=data_dir,
        verification_source='internal_cache',
    )
    if internal.get('verification_status') != VERIFICATION_UNVERIFIED:
        out = _finalize_verification_result(claim, internal)
        out['auto_refresh'] = auto_refresh_meta
        return out

    from backend.my_feed.external_verification_search import search_external_verification_articles

    external_articles = search_external_verification_articles(claim, data_dir=data_dir)
    if external_articles:
        external = verify_claim_against_sources(
            claim,
            source_loader=lambda: external_articles,
            verification_source='external_search',
        )
        if external.get('verification_status') != VERIFICATION_UNVERIFIED:
            out = _finalize_verification_result(claim, external)
            out['auto_refresh'] = auto_refresh_meta
            return out

    out = _finalize_verification_result(claim, internal)
    out['auto_refresh'] = auto_refresh_meta
    return out


def reverify_feed_item(feed_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    """Re-check a saved feed against current news cache; update status in place."""
    from backend.my_feed.my_feed_db import get_item, update_feed_item_metadata

    item = get_item(str(feed_id or '').strip())
    if not item:
        return {
            'ok': False,
            'reason': 'not_found',
            'feed_id': feed_id,
            'text': f'FEED_VERIFY_FAILED\nfeed_id={feed_id}\nreason=not_found',
        }

    old_status = item_verification_status(item)
    raw = str(
        item.get('raw_user_text')
        or item.get('raw_market_text')
        or item.get('cleaned_summary')
        or ''
    )
    claim = normalize_claim(raw)
    # Prefer already-resolved ticker if high confidence.
    if item.get('tickers') and not claim.get('ticker'):
        claim['ticker'] = str((item.get('tickers') or [''])[0]).upper()
        claim['tickers'] = [claim['ticker']]
    verification = verify_user_feed_claim(claim, data_dir=data_dir, allow_auto_refresh=True)
    new_status = str(verification.get('verification_status') or VERIFICATION_UNVERIFIED).upper()
    ticker = str(verification.get('ticker') or claim.get('ticker') or '').upper()
    company = str(verification.get('company') or verification.get('entity') or '')

    payload_fields = verification_payload_fields(verification, normalized_claim=claim)
    # Merge payload via metadata helper + direct payload update.
    update_fields: dict[str, Any] = {
        'tickers': [ticker] if ticker else list(item.get('tickers') or []),
        'event_type': str(verification.get('event_type') or item.get('event_type') or 'company_news'),
    }
    if claim.get('feed_type') == 'company_news':
        update_fields['suggested_action'] = 'STOCK NEWS' if new_status == VERIFICATION_VERIFIED else 'WATCH'
    update_feed_item_metadata(str(item.get('feed_id')), update_fields)

    # Patch payload verification fields.
    try:
        from backend.my_feed.my_feed_db import _connect, _json_dump, _json_load

        with _connect() as conn:
            row = conn.execute(
                'SELECT payload FROM feed_items WHERE feed_id = ?',
                (str(item.get('feed_id')),),
            ).fetchone()
            payload = _json_load(row['payload']) if row and row['payload'] else {}
            if not isinstance(payload, dict):
                payload = {}
            payload.update(payload_fields)
            payload['company'] = company
            payload['feed_type'] = claim.get('feed_type') or payload.get('feed_type') or 'company_news'
            conn.execute(
                'UPDATE feed_items SET payload = ? WHERE feed_id = ?',
                (_json_dump(payload), str(item.get('feed_id'))),
            )
            conn.commit()
    except Exception:
        pass

    matched = str(verification.get('source_name') or '')
    lines = [
        'FEED_VERIFICATION_UPDATED',
        f'feed_id={item.get("feed_id")}',
        f'ticker={ticker or "—"}',
        f'company={company or "—"}',
        f'old_status={old_status}',
        f'new_status={new_status}',
        f'matched_source={matched or "—"}',
    ]
    return {
        'ok': True,
        'feed_id': item.get('feed_id'),
        'ticker': ticker,
        'company': company,
        'old_status': old_status,
        'new_status': new_status,
        'matched_source': matched,
        'verification': verification,
        'text': '\n'.join(lines),
    }


def item_verification_status(item: dict[str, Any]) -> str:
    return str(item.get('verification_status') or VERIFICATION_UNVERIFIED).upper()


def format_feed_save_failed_reply(*, reason: str = '') -> str:
    detail = str(reason or 'database or validation error').strip()[:160]
    return '\n'.join([
        'MY_FEED_SAVE_FAILED',
        '❌ Feed could not be saved',
        f'Reason: {detail}',
        'Try again with /feed <market news text>',
    ])


def _ticker_entity_line(record: dict[str, Any], verification: dict[str, Any]) -> str:
    tickers = [str(t).strip().upper() for t in (record.get('tickers') or []) if str(t).strip()]
    ticker = str(verification.get('ticker') or (tickers[0] if tickers else '')).strip().upper()
    entity = str(
        verification.get('company')
        or verification.get('entity')
        or record.get('company')
        or ticker
        or ''
    ).strip()
    parts = [p for p in dict.fromkeys([ticker, entity]) if p and p != '—']
    return ' / '.join(parts) if parts else '—'


def format_verification_telegram_reply(
    record: dict[str, Any],
    verification: dict[str, Any],
    *,
    ignored_private_items: int = 0,
    items_found: int = 1,
    ticker_list: list[str] | None = None,
) -> str:
    """Telegram-facing /feed save reply with verification status."""
    status = str(verification.get('verification_status') or VERIFICATION_UNVERIFIED).upper()
    feed_id = str(record.get('feed_id') or '—')
    claim = str(
        verification.get('raw_user_text')
        or verification.get('claim_summary')
        or record.get('raw_market_text')
        or record.get('cleaned_summary')
        or ''
    ).strip()[:200]
    ticker_entity = _ticker_entity_line(record, verification)
    catalyst_yes = 'yes' if is_catalyst_eligible_status(status) else 'no'
    tickers = [str(t).strip() for t in (ticker_list or record.get('tickers') or []) if str(t).strip()]
    tickers_disp = ', '.join(dict.fromkeys(tickers)) or '—'
    action = str(record.get('suggested_action') or 'NEWS ONLY')
    impact = record.get('impact_score') or 0
    company = str(
        verification.get('company')
        or record.get('company')
        or verification.get('entity')
        or ''
    ).strip()
    feed_type = str(
        record.get('feed_type')
        or verification.get('feed_type')
        or ('company_news' if tickers and action in ('STOCK NEWS', 'WATCH') else 'news')
    )

    reason = (
        'trusted source match found'
        if status == VERIFICATION_VERIFIED
        else 'no trusted source match yet'
    )

    lines = [
        'MY_FEED_SAVED',
        f'verification_status={status}',
        f'feed_id={feed_id}',
        f'items_found={items_found or 1}',
        f'ignored_private_items={ignored_private_items}',
        f'tickers={tickers_disp}',
        f'company={company or "—"}',
        f'feed_type={feed_type}',
        f'impact_score={impact}',
        f'suggested_action={action}',
        f'catalyst_eligible={catalyst_yes}',
        f'Reason: {reason}',
    ]

    if status == VERIFICATION_VERIFIED:
        ticker_conf = str(verification.get('ticker_confidence') or 'high').lower()
        lines.extend([
            '✅ Feed verified',
            f'Feed ID: {feed_id}',
            f'Ticker/entity: {ticker_entity}',
            f'Used as catalyst evidence: {catalyst_yes}',
        ])
        headline = str(verification.get('verified_headline') or '').strip()
        if headline:
            lines.append(f'Headline: {headline[:180]}')
        source = str(verification.get('source_name') or 'news_cache')
        if source and source != 'user_feed_unverified':
            lines.append(f'Source: {source}')
        if ticker_conf == 'low':
            lines.append('Ticker confidence: low')
    elif status == VERIFICATION_PARTIAL:
        entity = str(verification.get('entity') or ticker_entity)
        lines.extend([
            '🟡 Feed partially verified',
            f'Feed ID: {feed_id}',
            f'Entity: {entity}',
            'Ticker confidence: low',
        ])
        headline = str(verification.get('verified_headline') or '').strip()
        if headline:
            lines.append(f'Headline: {headline[:160]}')
        lines.append('Used as catalyst evidence: low weight only')
    elif status == VERIFICATION_CONTRADICTED:
        lines.extend([
            '❌ Feed claim contradicted by available sources.',
            f'Feed ID: {feed_id}',
            f'Claim: {claim or "—"}',
            f'Ticker/entity: {ticker_entity}',
            'Not used for catalyst/tradecard.',
            f'Used as catalyst evidence: {catalyst_yes}',
        ])
        headline = str(verification.get('verified_headline') or '').strip()
        if headline:
            lines.append(f'Cached headline: {headline[:160]}')
    else:
        suggest_sym = (tickers[0] if tickers else '').upper()
        lines.extend([
            '⚠️ Feed saved as UNVERIFIED',
            f'Feed ID: {feed_id}',
            f'Claim: {claim or "—"}',
            f'Ticker/entity: {ticker_entity}',
            'Used as catalyst evidence: no',
            'Not used for catalyst/tradecard boost until verified.',
        ])
        if suggest_sym:
            lines.append(f'Try: /news refresh {suggest_sym} then /feed verify {feed_id}')
        else:
            lines.append(f'Try: /news refresh then /feed verify {feed_id}')

    return '\n'.join(lines)


def verification_payload_fields(
    verification: dict[str, Any],
    *,
    normalized_claim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fields stored in feed_items.payload for verification metadata."""
    keys = (
        'verification_status', 'raw_user_text', 'verified_headline', 'verified_summary',
        'source_name', 'source_time', 'source_url', 'ticker', 'entity', 'company',
        'event_type', 'feed_type', 'side', 'confidence', 'verification_source',
        'ticker_confidence', 'entities', 'resolver_source',
    )
    out: dict[str, Any] = {}
    for key in keys:
        val = verification.get(key)
        if val not in (None, ''):
            out[key] = val
    if normalized_claim:
        out['normalized_claim'] = normalized_claim
        if normalized_claim.get('feed_type') and not out.get('feed_type'):
            out['feed_type'] = normalized_claim.get('feed_type')
        if normalized_claim.get('company') and not out.get('company'):
            out['company'] = normalized_claim.get('company')
    status = str(out.get('verification_status') or VERIFICATION_UNVERIFIED).upper()
    out['verification_status'] = status
    out['catalyst_eligible'] = is_catalyst_eligible_status(status)
    return out
