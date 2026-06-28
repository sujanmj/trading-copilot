"""
Alert deduplication — suppress only exact duplicates within cooldown.

Allows material changes: confidence delta, sector rotation, post-market updates,
overnight macro changes.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

DEDUP_FILE = DATA_DIR / 'alert_dedup_state.json'
COOLDOWN_SEC = int(os.environ.get('ALERT_DEDUP_COOLDOWN_SEC', '3600'))
CONFIDENCE_DELTA_MIN = float(os.environ.get('ALERT_DEDUP_CONF_DELTA', '0.08'))
MATERIAL_CHANGE_TAGS = frozenset({
    'sector_rotation', 'post_market', 'overnight_macro', 'confidence_bump',
})


def _normalize(text: str) -> str:
    return ' '.join(str(text or '').lower().split())[:240]


def dedupe_fingerprint(
    ticker: str,
    headline: str,
    sentiment: str = 'NEUTRAL',
    *,
    confidence: float = 0.0,
    sector_tag: str = '',
    context_tag: str = '',
) -> str:
    """Fingerprint includes material dimensions — not ticker+headline alone."""
    conf_bucket = f'{int(round(float(confidence or 0) * 20))}'
    raw = (
        f"{ticker.upper()}|{_normalize(headline)}|{_normalize(sentiment)}|"
        f"{conf_bucket}|{_normalize(sector_tag)}|{_normalize(context_tag)}"
    )
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def _load_state() -> dict:
    default = {'records': {}, 'updated_at': None}
    if not DEDUP_FILE.exists():
        return default
    try:
        import json
        data = json.loads(DEDUP_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _save_state(data: dict) -> None:
    data['updated_at'] = datetime.now().isoformat()
    atomic_write_json(DEDUP_FILE, data)


def _confidence_materially_changed(prev: float, new: float) -> bool:
    return abs(float(new or 0) - float(prev or 0)) >= CONFIDENCE_DELTA_MIN


def _is_material_change(
    existing: dict,
    *,
    confidence: float,
    sector_tag: str,
    context_tag: str,
) -> bool:
    if context_tag and context_tag in MATERIAL_CHANGE_TAGS:
        return True
    if sector_tag and sector_tag != (existing.get('sector_tag') or ''):
        return True
    if _confidence_materially_changed(float(existing.get('confidence') or 0), confidence):
        return True
    return False


def check_duplicate(
    ticker: str,
    headline: str,
    sentiment: str = 'NEUTRAL',
    *,
    confidence: float = 0.0,
    cooldown_sec: Optional[int] = None,
    sector_tag: str = '',
    context_tag: str = '',
) -> Tuple[bool, str, Optional[dict]]:
    """
    Returns (should_send, reason, existing_record).
    should_send=False only for exact duplicate within cooldown.
    """
    if not ticker and not headline:
        return True, 'no_fingerprint', None

    cooldown = cooldown_sec if cooldown_sec is not None else COOLDOWN_SEC
    fp = dedupe_fingerprint(
        ticker, headline, sentiment,
        confidence=confidence, sector_tag=sector_tag, context_tag=context_tag,
    )
    state = _load_state()
    records = state.setdefault('records', {})
    now = datetime.now().timestamp()
    existing = records.get(fp)

    if existing:
        last = float(existing.get('last_sent_at') or 0)
        elapsed = now - last
        if elapsed < cooldown:
            if _is_material_change(
                existing,
                confidence=confidence,
                sector_tag=sector_tag,
                context_tag=context_tag,
            ):
                return True, 'material_change', existing
            prev_conf = float(existing.get('confidence') or 0)
            existing['confidence'] = round(max(prev_conf, float(confidence or 0)), 3)
            existing['duplicate_count'] = int(existing.get('duplicate_count') or 0) + 1
            existing['last_duplicate_at'] = datetime.now().isoformat()
            records[fp] = existing
            _save_state(state)
            try:
                from backend.orchestration.alert_suppression_log import log_suppression
                log_suppression(
                    reason='dedupe',
                    category='alert',
                    ticker=ticker,
                    detail=headline[:120],
                    stage='dedupe',
                    extra={'elapsed_sec': int(elapsed)},
                )
            except Exception:
                pass
            return False, 'duplicate_cooldown', existing

    return True, 'ok', existing


def record_sent(
    ticker: str,
    headline: str,
    sentiment: str = 'NEUTRAL',
    *,
    confidence: float = 0.0,
    category: str = '',
    channel: str = 'telegram',
    sector_tag: str = '',
    context_tag: str = '',
) -> dict:
    """Persist alert after successful send."""
    fp = dedupe_fingerprint(
        ticker, headline, sentiment,
        confidence=confidence, sector_tag=sector_tag, context_tag=context_tag,
    )
    state = _load_state()
    records = state.setdefault('records', {})
    now = datetime.now().isoformat()
    records[fp] = {
        'fingerprint': fp,
        'ticker': ticker.upper(),
        'headline': _normalize(headline)[:120],
        'sentiment': _normalize(sentiment),
        'confidence': round(float(confidence or 0), 3),
        'category': category,
        'channel': channel,
        'sector_tag': sector_tag,
        'context_tag': context_tag,
        'last_sent_at': datetime.now().timestamp(),
        'sent_at': now,
        'duplicate_count': 0,
    }
    if len(records) > 500:
        sorted_keys = sorted(
            records.keys(),
            key=lambda k: float(records[k].get('last_sent_at') or 0),
        )
        for key in sorted_keys[: len(records) - 500]:
            records.pop(key, None)
    _save_state(state)
    return records[fp]


def should_send_telegram_alert(
    ticker: str,
    headline: str,
    sentiment: str = 'NEUTRAL',
    *,
    confidence: float = 0.0,
    sector_tag: str = '',
    context_tag: str = '',
) -> Tuple[bool, str]:
    """High-level gate for outbound Telegram alert paths."""
    ok, reason, _ = check_duplicate(
        ticker, headline, sentiment,
        confidence=confidence,
        sector_tag=sector_tag,
        context_tag=context_tag,
    )
    return ok, reason


def get_dedup_summary() -> Dict[str, Any]:
    state = _load_state()
    records = state.get('records') or {}
    return {
        'cooldown_sec': COOLDOWN_SEC,
        'confidence_delta_min': CONFIDENCE_DELTA_MIN,
        'active_records': len(records),
        'updated_at': state.get('updated_at'),
    }
