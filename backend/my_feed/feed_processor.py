"""
My Feed ingest, classify, and reply formatting (Stage 50A / 50W verified intake).
"""

from __future__ import annotations

import re
from typing import Any

from backend.my_feed.my_feed_db import (
    archive_item,
    find_recent_duplicate,
    insert_feed_item,
    list_items,
)
from backend.my_feed.text_extractor import extract_tickers, filter_market_text
from backend.my_feed.suggested_actions import (
    MYFEED_ACTIONS_REQUIRING_CONFIRMATION,
    normalize_myfeed_suggested_action,
)

PUBLIC_ITEM_KEYS = frozenset({
    'feed_id', 'created_at', 'source', 'cleaned_summary', 'detected_source_app',
    'tickers', 'themes', 'impact_score', 'urgency', 'suggested_action', 'status',
    'verification_status', 'verified_headline', 'source_name', 'side', 'confidence',
    'raw_user_text', 'normalized_claim', 'catalyst_eligible', 'archive_reason', 'archived',
})


def sanitize_item_for_api(item: dict[str, Any]) -> dict[str, Any]:
    clean = {k: item.get(k) for k in PUBLIC_ITEM_KEYS if k in item}
    clean.pop('image_path', None)
    return clean


def _classify_item(extracted: dict[str, Any]) -> dict[str, Any]:
    summary = str(extracted.get('cleaned_summary') or '')
    lower = summary.lower()
    sentiment = 'neutral'
    if any(w in lower for w in ('surge', 'surges', 'rally', 'gain', 'upgrade', 'beat', 'strong')):
        sentiment = 'bullish'
    elif any(w in lower for w in ('fall', 'drop', 'crash', 'downgrade', 'miss', 'weak', 'risk')):
        sentiment = 'bearish'

    event_type = 'news'
    themes: list[str] = []
    tickers = extracted.get('tickers') or extract_tickers(summary)

    geo_attack = any(w in lower for w in (
        'attack', 'attacks', 'missile', 'war', 'conflict', 'sanction', 'ceasefire', 'base', 'bases',
    ))
    geo_country = any(w in lower for w in ('iran', 'kuwait', 'jordan', 'bahrain', 'israel', 'ukraine'))
    if geo_attack or geo_country or any(w in lower for w in ('geopolitical', 'inshorts:')):
        event_type = 'geopolitical'
        for theme in ('Geopolitical', 'Oil', 'Gold', 'Defence', 'Airlines'):
            if theme not in themes:
                themes.append(theme)
    elif any(w in lower for w in ('results', 'earnings', 'q1', 'q2', 'q3', 'q4')):
        event_type = 'results'
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
        35.0 + extracted.get('items_found', 0) * 8.0 + len(tickers) * 5.0,
    )
    if geo_attack or geo_country:
        impact_score = max(impact_score, 75.0)
    if tickers and re.search(r'\bsurges?\s+\d', lower):
        impact_score = max(impact_score, 72.0)

    urgency = 'medium'
    if impact_score >= 70:
        urgency = 'high'
    elif impact_score < 45:
        urgency = 'low'

    suggested_action = 'NEWS ONLY'
    if event_type == 'geopolitical':
        suggested_action = 'MARKET RISK ALERT'
    elif event_type == 'commodity':
        if 'silver' in lower:
            suggested_action = 'SILVER WATCH'
            if 'Precious Metals' not in themes:
                themes.append('Precious Metals')
        elif 'gold' in lower:
            suggested_action = 'GOLD WATCH'
            if 'Precious Metals' not in themes:
                themes.append('Precious Metals')
        elif any(w in lower for w in ('crude', 'oil')):
            suggested_action = 'OIL RISK WATCH'
        else:
            suggested_action = 'COMMODITY RISK ALERT'
        if 'Commodity Risk' not in themes:
            themes.append('Commodity Risk')
    elif sentiment == 'bearish' or any(w in lower for w in ('avoid', 'fraud', 'default', 'downgrade', 'breakdown')):
        suggested_action = 'AVOID / RISK WATCH'
    elif any(w in lower for w in ('fall', 'drop', 'weak', 'risk', 'volatility', 'uncertain')):
        suggested_action = 'AVOID / RISK WATCH'
    elif tickers and re.search(r'\bsurges?\s+\d', lower):
        suggested_action = 'WATCH FOR CONFIRMATION'
    elif sentiment == 'bullish' and impact_score >= 45:
        suggested_action = 'WATCH FOR CONFIRMATION'
    elif impact_score < 45:
        suggested_action = 'NEWS ONLY'
    else:
        suggested_action = 'WATCH FOR CONFIRMATION'

    suggested_action = normalize_myfeed_suggested_action(suggested_action)

    return {
        'sentiment': sentiment,
        'event_type': event_type,
        'impact_score': round(impact_score, 1),
        'urgency': urgency,
        'suggested_action': suggested_action,
        'confirmation_required': suggested_action in MYFEED_ACTIONS_REQUIRING_CONFIRMATION,
        'themes': themes,
        'sectors': [],
    }


def recompute_item_metadata_from_text(
    cleaned_summary: str,
    raw_market_text: str = '',
) -> dict[str, Any]:
    """Recompute tickers/themes/action from stored text without altering summary body."""
    text = str(cleaned_summary or raw_market_text or '').strip()
    extracted = {
        'cleaned_summary': text,
        'items_found': 1,
        'tickers': extract_tickers(text),
    }
    classified = _classify_item(extracted)
    return {
        'tickers': extracted['tickers'],
        'themes': classified['themes'],
        'sectors': classified['sectors'],
        'event_type': classified['event_type'],
        'sentiment': classified['sentiment'],
        'impact_score': classified['impact_score'],
        'urgency': classified['urgency'],
        'suggested_action': classified['suggested_action'],
        'confirmation_required': classified['confirmation_required'],
    }


def format_saved_reply(
    record: dict[str, Any],
    *,
    ignored_private_items: int = 0,
    items_found: int = 0,
    all_entities: list[str] | None = None,
    ticker_list: list[str] | None = None,
    suggested_actions: list[str] | None = None,
) -> str:
    tickers = [str(t).strip() for t in (ticker_list or record.get('tickers') or []) if str(t).strip()]
    entities = [str(e).strip() for e in (all_entities or tickers) if str(e).strip()]
    entities_disp = ', '.join(dict.fromkeys(entities)) or '—'
    tickers_disp = ', '.join(dict.fromkeys(tickers)) or '—'
    actions = [str(a).strip() for a in (suggested_actions or []) if str(a).strip()]
    if not actions:
        actions = [str(record.get('suggested_action') or 'WAIT')]
    action_disp = ' / '.join(dict.fromkeys(actions))
    return '\n'.join([
        'MY_FEED_SAVED',
        f'items_found={items_found or 1}',
        f'ignored_private_items={ignored_private_items}',
        f'entities={entities_disp}',
        f'tickers={tickers_disp}',
        f"impact_score={record.get('impact_score') or 0}",
        f'suggested_action={action_disp}',
    ])


def format_needs_text_reply() -> str:
    return '\n'.join([
        'MY_FEED_NEEDS_TEXT',
        'Could not read market news text. Please send:',
        '/feed <market news text>',
    ])


def _verify_and_build_text_record(
    extracted: dict[str, Any],
    *,
    source: str,
    raw_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from backend.my_feed.feed_verification import (
        format_verification_telegram_reply,
        is_catalyst_eligible_status,
        normalize_claim,
        verification_payload_fields,
        verify_claim_against_sources,
    )

    claim = normalize_claim(raw_text)
    verification = verify_claim_against_sources(claim)
    classified = _classify_item(extracted)
    tickers = extracted.get('tickers') or extract_tickers(extracted['cleaned_summary'])
    verify_ticker = str(verification.get('ticker') or '').strip().upper()
    if verify_ticker:
        tickers = [verify_ticker, *[t for t in tickers if str(t).upper() != verify_ticker]]

    status = str(verification.get('verification_status') or 'UNVERIFIED').upper()
    cleaned_summary = extracted['cleaned_summary']
    if is_catalyst_eligible_status(status) and verification.get('verified_headline'):
        cleaned_summary = str(verification.get('verified_headline') or cleaned_summary)

    payload = verification_payload_fields(verification, normalized_claim=claim)
    payload['raw_user_text'] = str(raw_text or '').strip()
    record = insert_feed_item({
        'source': source,
        'raw_market_text': extracted['raw_market_text'],
        'cleaned_summary': cleaned_summary,
        'detected_source_app': extracted.get('detected_source_app') or '',
        'tickers': tickers,
        'sectors': classified['sectors'],
        'themes': classified['themes'],
        'event_type': str(verification.get('event_type') or classified['event_type']),
        'sentiment': classified['sentiment'],
        'impact_score': classified['impact_score'],
        'urgency': classified['urgency'],
        'suggested_action': classified['suggested_action'],
        'confirmation_required': classified['confirmation_required'],
        'status': 'active',
        'payload': payload,
    })
    return record, verification


def ingest_text(text: str, *, source: str = 'telegram_text') -> dict[str, Any]:
    from backend.my_feed.feed_verification import (
        format_feed_save_failed_reply,
        format_verification_telegram_reply,
        item_verification_status,
    )

    raw = str(text or '').strip()
    if not raw:
        return {
            'ok': False,
            'reply': format_needs_text_reply(),
            'record': None,
            'saved_count': 0,
            'message': 'Empty feed text.',
        }

    try:
        extracted = filter_market_text(raw)
        if not extracted.get('cleaned_summary') and raw and source in ('telegram_text', 'gui_text'):
            extracted = {
                **extracted,
                'cleaned_summary': raw,
                'items_found': 1,
                'tickers': extract_tickers(raw),
            }
        if not extracted.get('cleaned_summary'):
            return {
                'ok': False,
                'reply': format_needs_text_reply(),
                'record': None,
                'saved_count': 0,
                'message': 'Could not read market news clearly. Paste text instead.',
            }

        duplicate = find_recent_duplicate(extracted['cleaned_summary'])
        if duplicate:
            dup_status = item_verification_status(duplicate)
            verification = {
                'verification_status': dup_status,
                'raw_user_text': duplicate.get('raw_user_text') or raw,
                'claim_summary': duplicate.get('cleaned_summary') or extracted['cleaned_summary'],
                'verified_headline': duplicate.get('verified_headline') or '',
                'ticker': (duplicate.get('tickers') or [''])[0] if duplicate.get('tickers') else duplicate.get('ticker', ''),
                'entity': duplicate.get('entity') or '',
                'event_type': duplicate.get('event_type') or '',
                'side': duplicate.get('side') or 'NEUTRAL',
                'source_name': duplicate.get('source_name') or '',
            }
            return {
                'ok': True,
                'reply': format_verification_telegram_reply(
                    duplicate,
                    verification,
                    ignored_private_items=extracted['ignored_private_items'],
                    items_found=0,
                ),
                'record': duplicate,
                'duplicate': True,
                'saved_count': 0,
                'message': 'Duplicate item — already saved recently.',
                'verification_status': dup_status,
            }

        record, verification = _verify_and_build_text_record(
            extracted,
            source=source,
            raw_text=raw,
        )
        try:
            from backend.my_feed.cache_invalidation import invalidate_myfeed_caches

            invalidate_myfeed_caches()
        except Exception:
            pass
        return {
            'ok': True,
            'reply': format_verification_telegram_reply(
                record,
                verification,
                ignored_private_items=extracted['ignored_private_items'],
                items_found=extracted['items_found'],
            ),
            'record': record,
            'duplicate': False,
            'saved_count': 1,
            'message': 'Saved 1 item',
            'verification_status': verification.get('verification_status'),
        }
    except Exception as exc:
        return {
            'ok': False,
            'reply': format_feed_save_failed_reply(reason=str(exc)),
            'record': None,
            'saved_count': 0,
            'message': str(exc)[:200],
        }


def ingest_notifications(
    notifications: list[str],
    *,
    source: str = 'gui_screenshot',
    ignored_private_items: int = 0,
) -> dict[str, Any]:
    saved_records: list[dict[str, Any]] = []
    duplicate_count = 0
    total_ignored = ignored_private_items

    for note in notifications:
        blob = str(note or '').strip()
        if not blob:
            continue
        extracted = filter_market_text(blob)
        total_ignored += int(extracted.get('ignored_private_items') or 0)
        cleaned = str(extracted.get('cleaned_summary') or '').strip()
        if not cleaned:
            continue

        duplicate = find_recent_duplicate(cleaned)
        if duplicate:
            duplicate_count += 1
            continue

        classified = _classify_item(extracted)
        record = insert_feed_item({
            'source': source,
            'raw_market_text': extracted['raw_market_text'],
            'cleaned_summary': cleaned,
            'detected_source_app': extracted.get('detected_source_app') or '',
            'tickers': extracted.get('tickers') or extract_tickers(cleaned),
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
        saved_records.append(record)

    if saved_records:
        try:
            from backend.my_feed.cache_invalidation import invalidate_myfeed_caches

            invalidate_myfeed_caches()
        except Exception:
            pass

    saved_count = len(saved_records)
    if saved_count == 0:
        return {
            'ok': False,
            'reply': format_needs_text_reply(),
            'record': None,
            'saved_count': 0,
            'duplicate': duplicate_count > 0,
            'message': 'Could not read market news clearly. Paste text instead.',
        }

    primary = saved_records[-1]
    return {
        'ok': True,
        'reply': format_saved_reply(
            primary,
            ignored_private_items=total_ignored,
            items_found=saved_count,
        ),
        'record': primary,
        'records': saved_records,
        'duplicate': duplicate_count > 0 and saved_count == 0,
        'saved_count': saved_count,
        'message': f'Saved {saved_count} item{"s" if saved_count != 1 else ""}',
    }


def _merge_classification(vision_item: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    classified = _classify_item(extracted)
    themes = list(vision_item.get('themes') or []) or classified['themes']
    for theme in classified['themes']:
        if theme not in themes:
            themes.append(theme)
    suggested = normalize_myfeed_suggested_action(
        str(vision_item.get('suggested_action') or classified['suggested_action']),
        fallback=str(classified['suggested_action'] or 'NEWS ONLY'),
    )
    impact = float(vision_item.get('impact_score') or 0) or classified['impact_score']
    urgency = str(vision_item.get('urgency') or classified['urgency'])
    return {
        'themes': themes,
        'sectors': classified['sectors'],
        'event_type': str(vision_item.get('event_type') or classified['event_type']),
        'sentiment': str(vision_item.get('sentiment') or classified['sentiment']),
        'impact_score': round(max(float(classified['impact_score']), impact), 1),
        'urgency': urgency,
        'suggested_action': suggested,
        'confirmation_required': bool(vision_item.get('confirmation_required')) or classified['confirmation_required'],
    }


def ingest_vision_items(
    items: list[dict[str, Any]],
    *,
    source: str = 'gui_screenshot',
    ignored_private_items: int = 0,
) -> dict[str, Any]:
    from backend.my_feed.text_extractor import correct_fuzzy_tickers, extract_tickers, split_entity_tokens

    saved_records: list[dict[str, Any]] = []
    duplicate_count = 0
    total_ignored = ignored_private_items
    all_entities: list[str] = []
    all_tickers: list[str] = []
    all_actions: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned = str(item.get('cleaned_summary') or item.get('raw_market_text') or '').strip()
        if not cleaned:
            continue
        extracted = {
            'raw_market_text': str(item.get('raw_market_text') or cleaned),
            'cleaned_summary': cleaned,
            'items_found': 1,
            'ignored_private_items': 0,
            'detected_source_app': str(item.get('detected_source_app') or ''),
            'tickers': correct_fuzzy_tickers(item.get('tickers') or extract_tickers(cleaned), cleaned),
        }
        entities = split_entity_tokens(item.get('entities') or [], cleaned)
        for ticker in extracted['tickers']:
            if ticker not in entities and ticker not in all_entities:
                pass
            if ticker not in entities:
                entities.append(ticker)

        duplicate = find_recent_duplicate(cleaned)
        if duplicate:
            duplicate_count += 1
            continue

        classified = _merge_classification(item, extracted)
        record = insert_feed_item({
            'source': source,
            'raw_market_text': extracted['raw_market_text'],
            'cleaned_summary': cleaned,
            'detected_source_app': extracted.get('detected_source_app') or '',
            'tickers': extracted['tickers'],
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
        saved_records.append(record)
        action = str(classified['suggested_action'] or '')
        if action and action not in all_actions:
            all_actions.append(action)
        for entity in entities:
            if entity not in all_entities:
                all_entities.append(entity)
        for ticker in extracted['tickers']:
            if ticker not in all_tickers:
                all_tickers.append(ticker)

    if saved_records:
        try:
            from backend.my_feed.cache_invalidation import invalidate_myfeed_caches

            invalidate_myfeed_caches()
        except Exception:
            pass

    saved_count = len(saved_records)
    if saved_count == 0:
        return {
            'ok': False,
            'reply': format_needs_text_reply(),
            'record': None,
            'saved_count': 0,
            'duplicate': duplicate_count > 0,
            'message': 'Could not read market news clearly. Paste text instead.',
        }

    primary = saved_records[-1]
    return {
        'ok': True,
        'reply': format_saved_reply(
            primary,
            ignored_private_items=total_ignored,
            items_found=saved_count,
            all_entities=all_entities,
            ticker_list=all_tickers,
            suggested_actions=all_actions,
        ),
        'record': primary,
        'records': saved_records,
        'duplicate': duplicate_count > 0 and saved_count == 0,
        'saved_count': saved_count,
        'message': f'Saved {saved_count} item{"s" if saved_count != 1 else ""}',
    }


def _ingest_ocr_payload(ocr: dict[str, Any], *, source: str) -> dict[str, Any]:
    if ocr.get('needs_text') or not ocr.get('ok'):
        return {
            'ok': False,
            'reply': format_needs_text_reply(),
            'record': None,
            'saved_count': 0,
            'message': 'Could not read market news clearly. Paste text instead.',
        }

    vision_items = list(ocr.get('vision_items') or [])
    ignored_private = int(ocr.get('ignored_private_count') or 0)
    if vision_items:
        return ingest_vision_items(vision_items, source=source, ignored_private_items=ignored_private)

    notifications = list(ocr.get('notifications') or [])
    if len(notifications) > 1:
        return ingest_notifications(
            notifications,
            source=source,
            ignored_private_items=ignored_private,
        )
    if notifications:
        return ingest_text(notifications[0], source=source)
    combined = str(ocr.get('text') or '').strip()
    if combined:
        return ingest_text(combined, source=source)
    return {
        'ok': False,
        'reply': format_needs_text_reply(),
        'record': None,
        'saved_count': 0,
        'message': 'Could not read market news clearly. Paste text instead.',
    }


def ingest_screenshot_bytes(image_bytes: bytes, *, source: str = 'gui_screenshot') -> dict[str, Any]:
    from backend.my_feed.image_extraction import extract_market_text_from_image_bytes

    ocr = extract_market_text_from_image_bytes(image_bytes)
    return _ingest_ocr_payload(ocr, source=source)


def ingest_feed_content(
    *,
    text: str = '',
    image_bytes: bytes | None = None,
    source: str = 'telegram_text',
) -> dict[str, Any]:
    caption = str(text or '').strip()
    if image_bytes:
        from backend.my_feed.image_extraction import extract_market_text_from_image_bytes

        ocr = extract_market_text_from_image_bytes(image_bytes)
        if ocr.get('needs_text') or not ocr.get('ok'):
            return {
                'ok': False,
                'reply': format_needs_text_reply(),
                'record': None,
                'saved_count': 0,
                'message': 'Could not read market news clearly. Paste text instead.',
            }
        resolved_source = 'telegram_screenshot' if source.startswith('telegram') else 'gui_screenshot'
        if caption and not list(ocr.get('vision_items') or []):
            notifications = list(ocr.get('notifications') or [])
            if caption:
                notifications = notifications + [caption] if notifications else [caption]
            ocr = dict(ocr)
            ocr['notifications'] = notifications
        return _ingest_ocr_payload(ocr, source=resolved_source)
    if not caption:
        return {
            'ok': False,
            'reply': format_needs_text_reply(),
            'record': None,
            'saved_count': 0,
            'message': 'Could not read market news clearly. Paste text instead.',
        }
    return ingest_text(caption, source=source)


def list_feed_items(
    *,
    limit: int = 20,
    today_only: bool = False,
    status: str | None = 'active',
    include_archived: bool = False,
    verification_filter: str | None = None,
) -> list[dict[str, Any]]:
    from backend.my_feed.feed_verification import (
        CATALYST_ELIGIBLE_STATUSES,
        VERIFICATION_CONTRADICTED,
        VERIFICATION_UNVERIFIED,
        item_verification_status,
    )

    filt = str(verification_filter or '').strip().lower()
    if filt == 'archived':
        rows = list_items(limit=max(limit * 3, 50), today_only=today_only, status='archived')
    elif include_archived:
        rows = list_items(
            limit=max(limit * 3, 50),
            today_only=today_only,
            status=None,
            include_archived=True,
        )
    else:
        rows = list_items(limit=max(limit * 3, 50), today_only=today_only, status='active')

    filtered: list[dict[str, Any]] = []
    for row in rows:
        vstatus = item_verification_status(row)
        row_status = str(row.get('status') or 'active').lower()
        if filt == 'verified' and vstatus not in CATALYST_ELIGIBLE_STATUSES:
            continue
        if filt == 'unverified' and vstatus != VERIFICATION_UNVERIFIED:
            continue
        if filt == 'contradicted' and vstatus != VERIFICATION_CONTRADICTED:
            continue
        if filt == 'archived' and row_status != 'archived':
            continue
        if not include_archived and filt != 'archived' and row_status == 'archived':
            continue
        filtered.append(row)
        if len(filtered) >= limit:
            break
    return filtered


def scan_feed_summary(*, today_only: bool = False) -> dict[str, Any]:
    from backend.my_feed.feed_verification import (
        CATALYST_ELIGIBLE_STATUSES,
        VERIFICATION_CONTRADICTED,
        VERIFICATION_UNVERIFIED,
        is_catalyst_eligible_item,
        item_verification_status,
    )

    active_items = list_feed_items(limit=200, today_only=today_only, status='active')
    archived_items = list_items(limit=200, status='archived', include_archived=True)
    archived_dirty = sum(
        1 for i in archived_items
        if 'dirty' in str(i.get('archive_reason') or '').lower()
        or str(i.get('archive_reason') or '') == 'dirty_legacy_ocr_or_unverified_noise'
    )
    return {
        'total': len(active_items),
        'verified': sum(1 for i in active_items if is_catalyst_eligible_item(i)),
        'partial': sum(
            1 for i in active_items
            if item_verification_status(i) == 'PARTIALLY_VERIFIED'
        ),
        'unverified': sum(
            1 for i in active_items
            if item_verification_status(i) == VERIFICATION_UNVERIFIED
        ),
        'contradicted': sum(
            1 for i in active_items
            if item_verification_status(i) == VERIFICATION_CONTRADICTED
        ),
        'archived_dirty': archived_dirty,
        'high_impact': sum(1 for i in active_items if float(i.get('impact_score') or 0) >= 70),
        'risk_alerts': sum(
            1 for i in active_items
            if str(i.get('suggested_action') or '') in {'MARKET RISK ALERT', 'AVOID / RISK WATCH', 'COMMODITY RISK ALERT'}
        ),
        'watch_items': sum(1 for i in active_items if i.get('suggested_action') == 'WATCH FOR CONFIRMATION'),
        'items': active_items,
    }


def archive_feed_item(feed_id: str, *, reason: str = '') -> bool:
    return archive_item(feed_id, reason=reason)


def public_feed_items(limit: int = 20) -> list[dict[str, Any]]:
    return [sanitize_item_for_api(item) for item in list_feed_items(limit=limit)]
