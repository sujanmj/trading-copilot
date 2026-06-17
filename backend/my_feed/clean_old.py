"""
My Feed clean-old — archive pre-50G image/OCR dirty rows (Stage 50H).

Soft-archive only by default; no hard delete unless MYFEED_CLEAN_OLD_HARD_DELETE=1.
"""

from __future__ import annotations

import os
import re
from typing import Any

from backend.my_feed.my_feed_db import archive_item, list_items

CLEAN_OLD_ARCHIVE_REASON = 'dirty_legacy_ocr_or_unverified_noise'

_DIRTY_SOURCE_TOKENS = (
    'screenshot',
    'image',
    'ocr',
    'vision',
    'temp',
    'groq',
)

_COUNTRY_TICKERS = frozenset({
    'INDIA', 'USA', 'US', 'UK', 'CHINA', 'JAPAN', 'EUROPE', 'EU', 'GLOBAL',
    'WORLD', 'ASIA', 'PAKISTAN', 'BANGLADESH', 'NEPAL', 'SRILANKA', 'SRI', 'LANKA',
})

_OCR_TICKER_TYPOS = frozenset({'CHAMBLERT', 'CHAMBLFERTT', 'CHAMBLFRT'})

_CLEAN_ACTIONS = frozenset({
    'GOLD WATCH', 'COMMODITY RISK ALERT', 'OIL RISK WATCH', 'NEWS ONLY',
    'WATCH FOR CONFIRMATION', 'WAIT FOR CONFIRMATION', 'RISK ALERT', 'RISK WATCH',
})


def _hard_delete_enabled() -> bool:
    return str(os.getenv('MYFEED_CLEAN_OLD_HARD_DELETE', '0')).strip().lower() in {
        '1', 'true', 'yes', 'on',
    }


def _source_is_dirty(source: str) -> bool:
    token = str(source or '').lower()
    return any(part in token for part in _DIRTY_SOURCE_TOKENS)


def _tickers_are_dirty(tickers: list[Any]) -> bool:
    normalized = [str(t or '').strip().upper() for t in tickers if str(t or '').strip()]
    if not normalized:
        return False
    if any(t in _OCR_TICKER_TYPOS for t in normalized):
        return True
    if all(t in _COUNTRY_TICKERS for t in normalized):
        return True
    if len(normalized) >= 4 and sum(1 for t in normalized if t in _COUNTRY_TICKERS) >= 2:
        return True
    return False


def _text_has_currency_noise(text: str) -> bool:
    blob = str(text or '')
    if not blob:
        return False
    if re.search(r'[$€£¥₹][\d,]+', blob):
        return True
    if re.search(r'[\u20ac\u00a3\u20b9]', blob):
        return True
    return False


def _legacy_unverified_noise(item: dict[str, Any]) -> bool:
    """Pre-50W rows without verification metadata and OCR-ish noise."""
    if str(item.get('verification_status') or '').strip():
        return False
    source = str(item.get('source') or '').lower()
    if _source_is_dirty(source):
        return True
    tickers = item.get('tickers') or []
    if _tickers_are_dirty(tickers if isinstance(tickers, list) else []):
        return True
    text = ' '.join([
        str(item.get('cleaned_summary') or ''),
        str(item.get('raw_market_text') or ''),
    ])
    if _text_has_ocr_noise(text) or _text_has_currency_noise(text):
        return True
    if 'CHAMBLERT' in text.upper():
        return True
    return False


def _text_has_ocr_noise(text: str) -> bool:
    blob = str(text or '')
    if not blob:
        return False
    if re.search(r'\bCHAMBLERT\b', blob, flags=re.IGNORECASE):
        return True
    if 'screenshot' in blob.lower() and 'temp' in blob.lower():
        return True
    return False


def is_dirty_feed_item(item: dict[str, Any]) -> tuple[bool, str]:
    """Return (is_dirty, reason_token)."""
    if not isinstance(item, dict):
        return False, ''
    if str(item.get('status') or '').lower() == 'archived':
        return False, ''

    source = str(item.get('source') or '')
    if _source_is_dirty(source):
        return True, 'image_ocr_source'

    action = str(item.get('suggested_action') or '').strip().upper()
    if action in _CLEAN_ACTIONS:
        return False, ''

    tickers = item.get('tickers') or []
    if _tickers_are_dirty(tickers if isinstance(tickers, list) else []):
        return True, 'dirty_tickers'

    text = ' '.join([
        str(item.get('cleaned_summary') or ''),
        str(item.get('raw_market_text') or ''),
    ])
    if _text_has_ocr_noise(text):
        return True, 'ocr_noise'

    if _text_has_currency_noise(text):
        return True, 'currency_noise'

    if _legacy_unverified_noise(item):
        return True, 'legacy_unverified_noise'

    return False, ''


def clean_old_my_feed_items(*, apply: bool = True, limit: int = 500) -> dict[str, Any]:
    items = list_items(limit=limit, status='active')
    archived_count = 0
    skipped_clean = 0
    errors: list[str] = []
    reasons: dict[str, int] = {}

    for item in items:
        dirty, reason = is_dirty_feed_item(item)
        if not dirty:
            skipped_clean += 1
            continue
        reasons[reason] = reasons.get(reason, 0) + 1
        feed_id = str(item.get('feed_id') or '')
        if not feed_id:
            errors.append('missing feed_id')
            continue
        if not apply:
            archived_count += 1
            continue
        try:
            if archive_item(feed_id, reason=CLEAN_OLD_ARCHIVE_REASON):
                archived_count += 1
            else:
                errors.append(f'archive failed: {feed_id}')
        except Exception as exc:
            errors.append(f'{feed_id}: {str(exc)[:80]}')

    if apply and archived_count > 0:
        try:
            from backend.my_feed.cache_invalidation import invalidate_myfeed_caches

            invalidate_myfeed_caches()
        except Exception:
            pass

    return {
        'ok': not errors,
        'apply': apply,
        'archived_count': archived_count,
        'skipped_clean': skipped_clean,
        'total_scanned': len(items),
        'reasons': reasons,
        'hard_delete': _hard_delete_enabled(),
        'errors': errors,
    }


def format_clean_old_reply(result: dict[str, Any]) -> str:
    count = int(result.get('archived_count') or 0)
    apply = bool(result.get('apply'))
    mode = 'archived' if apply else 'would archive'
    reasons = result.get('reasons') or {}
    reason_text = ', '.join(f'{k}={v}' for k, v in sorted(reasons.items())) or 'none'
    prefix = 'MYFEED_CLEAN_OLD_OK'
    if not apply:
        prefix = 'MYFEED_CLEAN_OLD_PREVIEW'
    return (
        f'{prefix} — {mode} {count} dirty row(s) '
        f'(scanned {int(result.get("total_scanned") or 0)}, '
        f'kept clean {int(result.get("skipped_clean") or 0)}; {reason_text})'
    )
