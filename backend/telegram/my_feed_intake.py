"""
Telegram My Feed intake — single /feed command with pending input (Stage 50B final).
"""

from __future__ import annotations

import os
from typing import Any

import requests

from backend.telegram.feed_pending_state import (
    chat_key_from_message,
    clear_feed_pending,
    is_feed_pending,
)

FEED_PENDING_REPLY = 'Send market news text or screenshot now.'


def is_feed_caption(text: str) -> bool:
    raw = str(text or '').strip().lower()
    if raw in ('/feed news', '/myfeed add', '/myfeed news'):
        return False
    if raw.startswith('/feed news ') or raw.startswith('/myfeed add ') or raw.startswith('/myfeed news '):
        return False
    return raw == '/feed' or raw.startswith('/feed ')


def extract_feed_caption_text(text: str) -> str:
    raw = str(text or '').strip()
    lower = raw.lower()
    if lower == '/feed':
        return ''
    if lower.startswith('/feed '):
        return raw[6:].strip()
    return ''


def download_telegram_file(file_id: str, *, bot_token: str | None = None) -> bytes:
    token = str(bot_token or os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip()
    if not token or not file_id:
        return b''
    api = f'https://api.telegram.org/bot{token}'
    try:
        meta = requests.get(f'{api}/getFile', params={'file_id': file_id}, timeout=20).json()
        file_path = ((meta.get('result') or {}).get('file_path') or '').strip()
        if not file_path:
            return b''
        resp = requests.get(f'https://api.telegram.org/file/bot{token}/{file_path}', timeout=30)
        if resp.status_code == 200:
            return resp.content or b''
    except Exception:
        return b''
    return b''


def pick_largest_photo_file_id(message: dict[str, Any]) -> str:
    photos = message.get('photo') or []
    if not photos:
        doc = message.get('document') or {}
        mime = str(doc.get('mime_type') or '').lower()
        if mime.startswith('image/'):
            return str(doc.get('file_id') or '')
        return ''
    best = max(photos, key=lambda row: int((row or {}).get('file_size') or 0))
    return str((best or {}).get('file_id') or '')


def message_has_image(message: dict[str, Any]) -> bool:
    return bool(pick_largest_photo_file_id(message))


def ingest_telegram_feed(
    *,
    text: str = '',
    image_bytes: bytes | None = None,
    source: str = 'telegram_text',
) -> dict[str, Any]:
    from backend.my_feed.feed_processor import ingest_feed_content

    text_blob = str(text or '').strip()
    if image_bytes:
        return ingest_feed_content(text=text_blob, image_bytes=image_bytes, source=source)
    if not text_blob:
        return {'ok': False, 'reply': FEED_PENDING_REPLY, 'record': None}
    return ingest_feed_content(text=text_blob, source='telegram_text')


def _ingest_photo_message(message: dict[str, Any], *, dry_run: bool = False) -> str:
    from backend.my_feed.feed_processor import format_needs_text_reply

    caption = str(message.get('caption') or '').strip()
    extra_text = extract_feed_caption_text(caption) if is_feed_caption(caption) else ''
    file_id = pick_largest_photo_file_id(message)
    if not file_id:
        return format_needs_text_reply()

    if dry_run:
        from backend.my_feed.feed_processor import ingest_text

        result = ingest_text(
            extra_text or 'NIFTY gains on banking sector rally today',
            source='telegram_screenshot',
        )
        return str(result.get('reply') or format_needs_text_reply())

    image_bytes = download_telegram_file(file_id)
    if not image_bytes:
        return format_needs_text_reply()

    result = ingest_telegram_feed(
        text=extra_text,
        image_bytes=image_bytes,
        source='telegram_screenshot',
    )
    return str(result.get('reply') or format_needs_text_reply())


def _ingest_text_message(text: str, *, dry_run: bool = False) -> str:
    from backend.my_feed.feed_processor import format_needs_text_reply, ingest_text

    blob = str(text or '').strip()
    if not blob:
        return format_needs_text_reply()
    if dry_run:
        result = ingest_text(blob, source='telegram_text')
    else:
        result = ingest_text(blob, source='telegram_text')
    return str(result.get('reply') or format_needs_text_reply())


def process_feed_message(message: dict[str, Any], *, dry_run: bool = False) -> str | None:
    """Return feed reply when message is consumed by My Feed intake, else None."""
    chat_id = chat_key_from_message(message)
    caption = str(message.get('caption') or '').strip()
    text = str(message.get('text') or '').strip()
    has_image = message_has_image(message)

    if has_image and is_feed_caption(caption):
        return _ingest_photo_message(message, dry_run=dry_run)

    if has_image and is_feed_pending(chat_id):
        clear_feed_pending(chat_id)
        return _ingest_photo_message(message, dry_run=dry_run)

    if text and is_feed_pending(chat_id) and not text.startswith('/'):
        clear_feed_pending(chat_id)
        return _ingest_text_message(text, dry_run=dry_run)

    return None


def handle_telegram_feed_message(message: dict[str, Any], *, dry_run: bool = False) -> str | None:
    return process_feed_message(message, dry_run=dry_run)
