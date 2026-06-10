"""
My Feed ingest, classify, and reply formatting (Stage 50A).
"""

from __future__ import annotations

from typing import Any

from backend.my_feed.my_feed_db import (
    archive_item,
    find_recent_duplicate,
    insert_feed_item,
    list_items,
)
from backend.my_feed.text_extractor import extract_tickers, filter_market_text

PUBLIC_ITEM_KEYS = frozenset({
    'feed_id', 'created_at', 'source', 'cleaned_summary', 'detected_source_app',
    'tickers', 'themes', 'impact_score', 'urgency', 'suggested_action', 'status',
})


def sanitize_item_for_api(item: dict[str, Any]) -> dict[str, Any]:
    clean = {k: item.get(k) for k in PUBLIC_ITEM_KEYS if k in item}
    clean.pop('image_path', None)
    return clean


def _classify_item(extracted: dict[str, Any]) -> dict[str, Any]:
    summary = str(extracted.get('cleaned_summary') or '')
    lower = summary.lower()
    sentiment = 'neutral'
    if any(w in lower for w in ('surge', 'rally', 'gain', 'upgrade', 'beat', 'strong')):
        sentiment = 'bullish'
    elif any(w in lower for w in ('fall', 'drop', 'crash', 'downgrade', 'miss', 'weak', 'risk')):
        sentiment = 'bearish'

    event_type = 'news'
    themes: list[str] = []
    if any(w in lower for w in ('results', 'earnings', 'q1', 'q2', 'q3', 'q4')):
        event_type = 'results'
    elif any(w in lower for w in ('geopolitical', 'war', 'conflict', 'sanction', 'ceasefire')):
        event_type = 'geopolitical'
        themes.append('geopolitical')
    elif any(w in lower for w in ('rbi', 'sebi', 'policy', 'budget', 'rate')):
        event_type = 'macro'
    elif any(w in lower for w in ('block deal', 'insider', 'stake', 'jv')):
        event_type = 'corporate_action'
    elif any(w in lower for w in ('crude', 'gold', 'silver', 'commodity', 'oil')):
        event_type = 'commodity'
        if any(w in lower for w in ('gold', 'silver')):
            themes.append('Precious Metals')
        themes.append('Commodity Risk')

    impact_score = min(
        100.0,
        35.0 + extracted.get('items_found', 0) * 8.0 + len(extracted.get('tickers') or []) * 5.0,
    )
    urgency = 'medium'
    if impact_score >= 70:
        urgency = 'high'
    elif impact_score < 45:
        urgency = 'low'

    suggested_action = 'NEWS ONLY'
    if event_type == 'geopolitical':
        suggested_action = 'MARKET RISK ALERT'
    elif event_type == 'commodity':
        if 'gold' in lower:
            suggested_action = 'GOLD WATCH'
            if 'Precious Metals' not in themes:
                themes.append('Precious Metals')
            if 'Commodity Risk' not in themes:
                themes.append('Commodity Risk')
        else:
            suggested_action = 'COMMODITY RISK ALERT'
            if 'Commodity Risk' not in themes:
                themes.append('Commodity Risk')
    elif sentiment == 'bearish' or any(w in lower for w in ('avoid', 'fraud', 'default', 'downgrade', 'breakdown')):
        suggested_action = 'AVOID'
    elif any(w in lower for w in ('fall', 'drop', 'weak')):
        suggested_action = 'RISK WATCH'
    elif any(w in lower for w in ('risk', 'volatility', 'uncertain')):
        suggested_action = 'RISK ALERT'
    elif sentiment == 'bullish' and impact_score >= 45:
        suggested_action = 'WATCH FOR CONFIRMATION'
    elif impact_score < 45:
        suggested_action = 'NEWS ONLY'
    else:
        suggested_action = 'WATCH FOR CONFIRMATION'

    return {
        'sentiment': sentiment,
        'event_type': event_type,
        'impact_score': round(impact_score, 1),
        'urgency': urgency,
        'suggested_action': suggested_action,
        'confirmation_required': suggested_action in {
            'WATCH FOR CONFIRMATION', 'RISK ALERT', 'MARKET RISK ALERT', 'RISK WATCH',
            'COMMODITY RISK ALERT', 'GOLD WATCH',
        },
        'themes': themes,
        'sectors': [],
    }


def format_saved_reply(record: dict[str, Any], *, ignored_private_items: int = 0, items_found: int = 0) -> str:
    tickers = ', '.join(record.get('tickers') or []) or '—'
    return '\n'.join([
        'MY_FEED_SAVED',
        f'items_found={items_found or 1}',
        f'ignored_private_items={ignored_private_items}',
        f'tickers={tickers}',
        f"impact_score={record.get('impact_score') or 0}",
        f"suggested_action={record.get('suggested_action') or 'WAIT'}",
    ])


def format_needs_text_reply() -> str:
    return '\n'.join([
        'MY_FEED_NEEDS_TEXT',
        'Could not read screenshot clearly. Please send:',
        '/feed <market news text>',
    ])


def ingest_text(text: str, *, source: str = 'telegram_text') -> dict[str, Any]:
    extracted = filter_market_text(text)
    if not extracted.get('cleaned_summary'):
        return {'ok': False, 'reply': format_needs_text_reply(), 'record': None}

    duplicate = find_recent_duplicate(extracted['cleaned_summary'])
    if duplicate:
        return {
            'ok': True,
            'reply': format_saved_reply(
                duplicate,
                ignored_private_items=extracted['ignored_private_items'],
                items_found=0,
            ),
            'record': duplicate,
            'duplicate': True,
        }

    classified = _classify_item(extracted)
    record = insert_feed_item({
        'source': source,
        'raw_market_text': extracted['raw_market_text'],
        'cleaned_summary': extracted['cleaned_summary'],
        'detected_source_app': extracted.get('detected_source_app') or '',
        'tickers': extracted.get('tickers') or extract_tickers(extracted['cleaned_summary']),
        'sectors': classified['sectors'],
        'themes': classified['themes'],
        'event_type': classified['event_type'],
        'sentiment': classified['sentiment'],
        'impact_score': classified['impact_score'],
        'urgency': classified['urgency'],
        'suggested_action': classified['suggested_action'],
        'confirmation_required': classified['confirmation_required'],
        'status': 'active',
    })
    return {
        'ok': True,
        'reply': format_saved_reply(
            record,
            ignored_private_items=extracted['ignored_private_items'],
            items_found=extracted['items_found'],
        ),
        'record': record,
        'duplicate': False,
    }


def ingest_screenshot_bytes(image_bytes: bytes, *, source: str = 'gui_screenshot') -> dict[str, Any]:
    from backend.my_feed.image_extraction import extract_market_text_from_image_bytes

    ocr = extract_market_text_from_image_bytes(image_bytes)
    if not ocr.get('ok') or not str(ocr.get('text') or '').strip():
        return {'ok': False, 'reply': format_needs_text_reply(), 'record': None}
    return ingest_text(str(ocr.get('text') or ''), source=source)


def ingest_feed_content(
    *,
    text: str = '',
    image_bytes: bytes | None = None,
    source: str = 'telegram_text',
) -> dict[str, Any]:
    parts: list[str] = []
    if image_bytes:
        from backend.my_feed.image_extraction import extract_market_text_from_image_bytes

        ocr = extract_market_text_from_image_bytes(image_bytes)
        if not ocr.get('ok'):
            return {'ok': False, 'reply': format_needs_text_reply(), 'record': None}
        if str(ocr.get('text') or '').strip():
            parts.append(str(ocr['text']))
    caption = str(text or '').strip()
    if caption:
        parts.append(caption)
    combined = '\n'.join(p for p in parts if p).strip()
    if not combined:
        return {'ok': False, 'reply': format_needs_text_reply(), 'record': None}
    resolved_source = source
    if image_bytes:
        resolved_source = 'telegram_screenshot' if source.startswith('telegram') else 'gui_screenshot'
    return ingest_text(combined, source=resolved_source)


def list_feed_items(*, limit: int = 20, today_only: bool = False, status: str = 'active') -> list[dict[str, Any]]:
    return list_items(limit=limit, today_only=today_only, status=status)


def archive_feed_item(feed_id: str) -> bool:
    return archive_item(feed_id)


def scan_feed_summary(*, today_only: bool = False) -> dict[str, Any]:
    items = list_feed_items(limit=50, today_only=today_only, status='active')
    return {
        'total': len(items),
        'high_impact': sum(1 for i in items if float(i.get('impact_score') or 0) >= 70),
        'risk_alerts': sum(1 for i in items if i.get('suggested_action') == 'RISK ALERT'),
        'watch_items': sum(1 for i in items if i.get('suggested_action') == 'WATCH FOR CONFIRMATION'),
        'items': items,
    }


def public_feed_items(limit: int = 20) -> list[dict[str, Any]]:
    return [sanitize_item_for_api(item) for item in list_feed_items(limit=limit)]
