"""
My Feed metadata reprocessor — refresh tickers/themes/actions without changing text (Stage 50C hotfix).
"""

from __future__ import annotations

from typing import Any

from backend.my_feed.feed_processor import recompute_item_metadata_from_text
from backend.my_feed.my_feed_db import list_items, update_feed_item_metadata

REJECT_TICKER_WORDS = frozenset({
    'FALLS', 'BELOW', 'ABOVE', 'RS', 'LAKH', 'CRORE', 'AMID', 'GLOBAL', 'SELL', 'BUY',
    'CHECK', 'CITY', 'TODAY', 'PRICE', 'PRICES', 'MARKET', 'NEWS', 'UPDATE', 'ALERT',
})


def _metadata_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = (
        'tickers', 'themes', 'event_type', 'sentiment', 'impact_score', 'urgency',
        'suggested_action', 'confirmation_required', 'sectors',
    )
    for key in keys:
        if before.get(key) != after.get(key):
            return True
    return False


def reprocess_my_feed_items(*, apply: bool = False, limit: int = 500) -> dict[str, Any]:
    items = list_items(limit=limit, status=None)
    updated = 0
    unchanged = 0
    errors: list[str] = []

    for item in items:
        feed_id = str(item.get('feed_id') or '')
        if not feed_id:
            errors.append('missing feed_id')
            continue
        try:
            fresh = recompute_item_metadata_from_text(
                str(item.get('cleaned_summary') or ''),
                str(item.get('raw_market_text') or ''),
            )
            patch = {
                'tickers': fresh.get('tickers') or [],
                'themes': fresh.get('themes') or [],
                'sectors': fresh.get('sectors') or [],
                'event_type': fresh.get('event_type') or '',
                'sentiment': fresh.get('sentiment') or '',
                'impact_score': fresh.get('impact_score') or 0,
                'urgency': fresh.get('urgency') or '',
                'suggested_action': fresh.get('suggested_action') or '',
                'confirmation_required': bool(fresh.get('confirmation_required')),
            }
            if not _metadata_changed(item, patch):
                unchanged += 1
                continue
            if apply:
                if not update_feed_item_metadata(feed_id, patch):
                    errors.append(f'update failed: {feed_id}')
                    continue
            updated += 1
        except Exception as exc:
            errors.append(f'{feed_id}: {str(exc)[:80]}')

    result = {
        'ok': not errors,
        'apply': apply,
        'total': len(items),
        'updated': updated,
        'unchanged': unchanged,
        'errors': errors,
    }
    if apply and updated > 0:
        try:
            from backend.my_feed.cache_invalidation import invalidate_myfeed_caches

            invalidate_myfeed_caches()
        except Exception:
            pass
    return result


def format_reprocess_reply(result: dict[str, Any]) -> str:
    return '\n'.join([
        'MYFEED_REPROCESS_OK',
        f"updated={result.get('updated', 0)}",
        f"unchanged={result.get('unchanged', 0)}",
        f"errors={len(result.get('errors') or [])}",
    ])
