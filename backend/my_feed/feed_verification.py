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
    tickers = item.get('tickers') or item.get('symbols') or []
    if isinstance(tickers, str):
        tickers = [tickers]
    resolved = [str(t).strip().upper() for t in tickers if t]
    if resolved:
        return resolved
    try:
        from backend.intelligence.stock_catalyst_radar import resolve_tickers_from_text

        return resolve_tickers_from_text(blob)
    except Exception:
        from backend.my_feed.text_extractor import extract_tickers

        return extract_tickers(blob)


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
    text = str(raw_text or '').strip()
    from backend.my_feed.text_extractor import extract_tickers, filter_market_text

    filtered = filter_market_text(text)
    cleaned = str(filtered.get('cleaned_summary') or text).strip()
    tickers = list(filtered.get('tickers') or extract_tickers(cleaned))
    entity = ''
    if tickers:
        entity = tickers[0]
    else:
        try:
            from backend.intelligence.stock_catalyst_radar import resolve_tickers_from_text

            resolved = resolve_tickers_from_text(cleaned)
            if resolved:
                tickers = resolved
                entity = resolved[0]
        except Exception:
            pass

    try:
        from backend.intelligence.stock_catalyst_radar import classify_catalyst

        event_type, side = classify_catalyst(cleaned)
    except Exception:
        from backend.my_feed.feed_processor import _classify_item

        classified = _classify_item({'cleaned_summary': cleaned, 'items_found': 1, 'tickers': tickers})
        event_type = classified.get('event_type') or 'news'
        side_map = {'bullish': 'BULLISH', 'bearish': 'BEARISH', 'neutral': 'NEUTRAL'}
        side = side_map.get(str(classified.get('sentiment') or 'neutral'), 'NEUTRAL')

    keywords = sorted(_tokenize(cleaned))[:24]
    lower = cleaned.lower()
    if not tickers and 'adani' in lower:
        tickers = ['ADANIENT']
        entity = 'Adani Group'
    return {
        'raw_user_text': text,
        'claim_summary': cleaned,
        'entity': entity,
        'ticker': tickers[0] if tickers else '',
        'tickers': tickers,
        'event_type': str(event_type or 'GENERAL_NEWS'),
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
) -> dict[str, Any]:
    """Match claim to cached sources; never invent confirmation."""
    loader = source_loader or (lambda: iter_verification_source_articles(data_dir=data_dir))
    articles = loader()
    if not articles:
        return {
            'verification_status': VERIFICATION_UNVERIFIED,
            'confidence': 0.0,
            'source_name': 'user_feed_unverified',
            'raw_user_text': claim.get('raw_user_text') or claim.get('claim_summary') or '',
        }

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
            'verification_status': VERIFICATION_UNVERIFIED,
            'confidence': 0.0,
            'source_name': 'user_feed_unverified',
            'raw_user_text': claim.get('raw_user_text') or claim.get('claim_summary') or '',
        }

    best_score, best_match, _best_article = ranked[0]
    fields = best_match['fields']
    article_tickers = list(best_match.get('article_tickers') or [])
    ticker = str(claim.get('ticker') or '').strip().upper()
    if article_tickers and (best_match.get('ticker_match') or best_match.get('similarity', 0) >= 0.65):
        ticker = article_tickers[0]
    elif not ticker and article_tickers:
        ticker = article_tickers[0]

    if best_match.get('contradicted') and best_score >= 0.25:
        status = VERIFICATION_CONTRADICTED
        confidence = round(best_score, 2)
    elif (
        best_match.get('similarity', 0) >= 0.72
        or (best_match.get('overlap', 0) >= 0.45 and best_match.get('similarity', 0) >= 0.65)
        or (best_score >= 0.58 and best_match.get('ticker_match'))
    ):
        status = VERIFICATION_VERIFIED
        confidence = round(min(0.98, max(best_score, best_match.get('similarity', 0)) + 0.1), 2)
    elif best_score >= 0.38:
        status = VERIFICATION_PARTIAL
        confidence = round(best_score, 2)
    else:
        status = VERIFICATION_UNVERIFIED
        confidence = round(best_score, 2)

    side = str(best_match.get('article_side') or claim.get('side') or 'NEUTRAL').upper()
    if status == VERIFICATION_UNVERIFIED:
        return {
            'verification_status': status,
            'confidence': confidence,
            'source_name': 'user_feed_unverified',
            'raw_user_text': claim.get('raw_user_text') or claim.get('claim_summary') or '',
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
        'entity': claim.get('entity') or ticker,
        'event_type': claim.get('event_type') or 'GENERAL_NEWS',
        'side': side,
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
    entity = str(verification.get('entity') or ticker or '').strip()
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

    lines = [
        'MY_FEED_SAVED',
        f'verification_status={status}',
        f'feed_id={feed_id}',
        f'items_found={items_found or 1}',
        f'ignored_private_items={ignored_private_items}',
        f'tickers={tickers_disp}',
        f'impact_score={impact}',
        f'suggested_action={action}',
        f'catalyst_eligible={catalyst_yes}',
    ]

    if status == VERIFICATION_VERIFIED:
        lines.extend([
            '✅ Feed verified',
            f'Feed ID: {feed_id}',
            f'Claim: {claim or "—"}',
            f'Ticker/entity: {ticker_entity}',
            f'Used as catalyst evidence: {catalyst_yes}',
        ])
        headline = str(verification.get('verified_headline') or '').strip()
        if headline:
            lines.append(f'Headline: {headline[:180]}')
        event = str(verification.get('event_type') or record.get('event_type') or '—')
        side = str(verification.get('side') or 'NEUTRAL').upper()
        lines.append(f'Event: {event}')
        lines.append(f'Side: {side}')
        source = str(verification.get('source_name') or 'news_cache')
        if source and source != 'user_feed_unverified':
            lines.append(f'Source: {source}')
    elif status == VERIFICATION_PARTIAL:
        lines.extend([
            '🟡 Feed partially verified',
            f'Feed ID: {feed_id}',
            f'Claim: {claim or "—"}',
            f'Ticker/entity: {ticker_entity}',
            'Matched company/event but exact claim unclear.',
            f'Used as catalyst evidence: {catalyst_yes} (low weight only)',
        ])
        headline = str(verification.get('verified_headline') or '').strip()
        if headline:
            lines.append(f'Closest match: {headline[:160]}')
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
        lines.extend([
            '⚠️ Feed saved as UNVERIFIED',
            f'Feed ID: {feed_id}',
            f'Claim: {claim or "—"}',
            f'Ticker/entity: {ticker_entity}',
            'Used as catalyst evidence: no',
            'Reason: could not confirm from trusted sources yet.',
            'Not used for catalyst/tradecard boost until verified.',
        ])

    return '\n'.join(lines)


def verification_payload_fields(
    verification: dict[str, Any],
    *,
    normalized_claim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fields stored in feed_items.payload for verification metadata."""
    keys = (
        'verification_status', 'raw_user_text', 'verified_headline', 'verified_summary',
        'source_name', 'source_time', 'source_url', 'ticker', 'entity', 'event_type',
        'side', 'confidence',
    )
    out: dict[str, Any] = {}
    for key in keys:
        val = verification.get(key)
        if val not in (None, ''):
            out[key] = val
    if normalized_claim:
        out['normalized_claim'] = normalized_claim
    status = str(out.get('verification_status') or VERIFICATION_UNVERIFIED).upper()
    out['verification_status'] = status
    out['catalyst_eligible'] = is_catalyst_eligible_status(status)
    return out
