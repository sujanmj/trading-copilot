"""
Alert deduplication — suppress duplicate Telegram pushes for same ticker + headline + sentiment.

On duplicate within cooldown: bump confidence on existing alert record; do not send again.
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


def _normalize(text: str) -> str:
    return ' '.join(str(text or '').lower().split())[:240]


def dedupe_fingerprint(
    ticker: str,
    headline: str,
    sentiment: str = 'NEUTRAL',
) -> str:
    raw = f"{ticker.upper()}|{_normalize(headline)}|{_normalize(sentiment)}"
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


def check_duplicate(
    ticker: str,
    headline: str,
    sentiment: str = 'NEUTRAL',
    *,
    confidence: float = 0.0,
    cooldown_sec: Optional[int] = None,
) -> Tuple[bool, str, Optional[dict]]:
    """
    Returns (should_send, reason, existing_record).
    should_send=False when duplicate within cooldown.
    """
    if not ticker and not headline:
        return True, 'no_fingerprint', None

    cooldown = cooldown_sec if cooldown_sec is not None else COOLDOWN_SEC
    fp = dedupe_fingerprint(ticker, headline, sentiment)
    state = _load_state()
    records = state.setdefault('records', {})
    now = datetime.now().timestamp()
    existing = records.get(fp)

    if existing:
        last = float(existing.get('last_sent_at') or 0)
        elapsed = now - last
        if elapsed < cooldown:
            prev_conf = float(existing.get('confidence') or 0)
            existing['confidence'] = round(max(prev_conf, float(confidence or 0)), 3)
            existing['duplicate_count'] = int(existing.get('duplicate_count') or 0) + 1
            existing['last_duplicate_at'] = datetime.now().isoformat()
            records[fp] = existing
            _save_state(state)
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
) -> dict:
    """Persist alert after successful send."""
    fp = dedupe_fingerprint(ticker, headline, sentiment)
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
        'last_sent_at': datetime.now().timestamp(),
        'sent_at': now,
        'duplicate_count': 0,
    }
    # Prune old records (keep last 500)
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
) -> Tuple[bool, str]:
    """High-level gate for outbound Telegram alert paths."""
    ok, reason, _ = check_duplicate(ticker, headline, sentiment, confidence=confidence)
    return ok, reason


def get_dedup_summary() -> Dict[str, Any]:
    state = _load_state()
    records = state.get('records') or {}
    return {
        'cooldown_sec': COOLDOWN_SEC,
        'active_records': len(records),
        'updated_at': state.get('updated_at'),
    }
