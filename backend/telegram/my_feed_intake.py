"""
Telegram My Feed intake — single /feed command with pending input (Stage 50B final).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import requests

from backend.telegram.feed_pending_state import (
    clear_feed_pending,
    is_feed_pending,
    set_feed_pending,
)

FEED_PENDING_REPLY = 'Send market news text or screenshot now.'


def _myfeed_photo_log(tag: str) -> None:
    try:
        from backend.telegram.telegram_analysis_bot import safe_print

        safe_print(f'[{tag}]')
    except Exception:
        print(f'[{tag}]', flush=True)


def resolve_message_caption(message: dict[str, Any]) -> str:
    """Caption for photo/document messages; fall back to slash text on media."""
    caption = str(message.get('caption') or '').strip()
    if caption:
        return caption
    text = str(message.get('text') or '').strip()
    if text.startswith('/'):
        return text
    return ''


def is_feed_caption(text: str) -> bool:
    from backend.telegram.telegram_command_normalize import normalize_slash_command

    raw = str(text or '').strip()
    if not raw:
        return False
    if not raw.startswith('/'):
        return False
    inner = normalize_slash_command(raw).lower()
    if inner in ('feed news', 'myfeed add', 'myfeed news'):
        return False
    if inner.startswith('feed news ') or inner.startswith('myfeed add ') or inner.startswith('myfeed news '):
        return False
    if inner == 'feed':
        return True
    if inner.startswith('feed '):
        remainder = inner[5:].strip()
        return bool(remainder)
    return False


def is_feed_caption_only(text: str) -> bool:
    """True when caption is /feed, / feed, or /feed@bot with optional whitespace."""
    from backend.telegram.telegram_command_normalize import normalize_slash_command

    raw = str(text or '').strip()
    if not raw.startswith('/'):
        return False
    inner = normalize_slash_command(raw).lower()
    return inner == 'feed'


def extract_feed_caption_text(text: str) -> str:
    from backend.telegram.telegram_command_normalize import normalize_slash_command

    raw = str(text or '').strip()
    if not raw.startswith('/'):
        return raw
    inner = normalize_slash_command(raw)
    lower = inner.lower()
    if lower == 'feed':
        return ''
    if lower.startswith('feed '):
        return inner[5:].strip()
    return ''


def resolve_feed_chat_id(message: dict[str, Any], chat_id: str | None = None) -> str:
    if chat_id:
        return str(chat_id)
    chat = message.get('chat') or {}
    return str(chat.get('id') or 'default')


def message_has_image(message: dict[str, Any]) -> bool:
    if message.get('photo'):
        return True
    doc = message.get('document') or {}
    mime = str(doc.get('mime_type') or '').lower()
    if mime.startswith('image/'):
        return True
    fname = str(doc.get('file_name') or '').lower()
    return fname.endswith(('.png', '.jpg', '.jpeg', '.webp', '.heic', '.gif'))


def should_process_feed_photo(message: dict[str, Any], chat_id: str) -> bool:
    if not message_has_image(message):
        return False
    caption = resolve_message_caption(message)
    if is_feed_caption(caption) or is_feed_pending(chat_id):
        return True
    return is_feed_caption_only(caption)


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
        fname = str(doc.get('file_name') or '').lower()
        if mime.startswith('image/') or fname.endswith(('.png', '.jpg', '.jpeg', '.webp', '.heic', '.gif')):
            return str(doc.get('file_id') or '')
        return ''
    best = max(photos, key=lambda row: int((row or {}).get('file_size') or 0))
    return str((best or {}).get('file_id') or '')


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


def _ingest_from_ocr_result(ocr: dict[str, Any], *, extra_text: str = '', source: str) -> dict[str, Any]:
    from backend.my_feed.feed_processor import (
        format_needs_text_reply,
        ingest_notifications,
        ingest_text,
    )

    if ocr.get('needs_text') or not ocr.get('ok'):
        return {'ok': False, 'reply': format_needs_text_reply(), 'record': None}

    notifications = list(ocr.get('notifications') or [])
    ignored_private = int(ocr.get('ignored_private_count') or 0)
    if extra_text:
        notifications = notifications + [extra_text] if notifications else [extra_text]
    if len(notifications) > 1:
        return ingest_notifications(notifications, source=source, ignored_private_items=ignored_private)
    if notifications:
        return ingest_text(notifications[0], source=source)
    combined = str(ocr.get('text') or '').strip()
    if combined:
        return ingest_text(combined, source=source)
    return {'ok': False, 'reply': format_needs_text_reply(), 'record': None}


def _ingest_photo_message(message: dict[str, Any], *, dry_run: bool = False) -> str:
    from backend.my_feed.feed_processor import format_needs_text_reply

    _myfeed_photo_log('MYFEED_PHOTO_RECEIVED')
    caption = resolve_message_caption(message)
    extra_text = extract_feed_caption_text(caption) if is_feed_caption(caption) else ''
    file_id = pick_largest_photo_file_id(message)
    if not file_id:
        _myfeed_photo_log('MYFEED_PHOTO_OCR_FAIL')
        reply = format_needs_text_reply()
        _myfeed_photo_log('MYFEED_PHOTO_REPLY_SENT')
        return reply

    if dry_run:
        from backend.my_feed.feed_processor import ingest_text

        result = ingest_text(
            extra_text or 'NIFTY gains on banking sector rally today',
            source='telegram_screenshot',
        )
        _myfeed_photo_log('MYFEED_PHOTO_DOWNLOAD_OK')
        _myfeed_photo_log('MYFEED_PHOTO_OCR_OK')
        reply = str(result.get('reply') or format_needs_text_reply())
        _myfeed_photo_log('MYFEED_PHOTO_REPLY_SENT')
        return reply

    image_bytes = download_telegram_file(file_id)
    if not image_bytes:
        _myfeed_photo_log('MYFEED_PHOTO_OCR_FAIL')
        reply = format_needs_text_reply()
        _myfeed_photo_log('MYFEED_PHOTO_REPLY_SENT')
        return reply
    _myfeed_photo_log('MYFEED_PHOTO_DOWNLOAD_OK')

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp.write(image_bytes)
            temp_path = Path(tmp.name)

        from backend.my_feed.image_extraction import extract_market_text_from_image_temp

        ocr = extract_market_text_from_image_temp(temp_path)
        if ocr.get('ok') and not ocr.get('needs_text'):
            _myfeed_photo_log('MYFEED_PHOTO_OCR_OK')
            result = _ingest_from_ocr_result(
                ocr,
                extra_text=extra_text,
                source='telegram_screenshot',
            )
        else:
            _myfeed_photo_log('MYFEED_PHOTO_OCR_FAIL')
            result = {'ok': False, 'reply': format_needs_text_reply(), 'record': None}

        reply = str(result.get('reply') or '')
        if reply.startswith('MY_FEED_'):
            _myfeed_photo_log('MYFEED_PHOTO_REPLY_SENT')
            return reply
    except Exception:
        _myfeed_photo_log('MYFEED_PHOTO_OCR_FAIL')
        reply = format_needs_text_reply()
        _myfeed_photo_log('MYFEED_PHOTO_REPLY_SENT')
        return reply
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            _myfeed_photo_log('MYFEED_PHOTO_TEMP_DELETED')

    reply = format_needs_text_reply()
    _myfeed_photo_log('MYFEED_PHOTO_REPLY_SENT')
    return reply


def _ingest_text_message(text: str, *, dry_run: bool = False) -> str:
    from backend.my_feed.feed_processor import format_needs_text_reply, ingest_text

    blob = str(text or '').strip()
    if not blob:
        return format_needs_text_reply()
    result = ingest_text(blob, source='telegram_text')
    return str(result.get('reply') or format_needs_text_reply())


def process_feed_message(
    message: dict[str, Any],
    *,
    dry_run: bool = False,
    chat_id: str | None = None,
) -> str | None:
    """Return feed reply when message is consumed by My Feed intake, else None."""
    from backend.my_feed.feed_processor import format_needs_text_reply

    resolved_chat_id = resolve_feed_chat_id(message, chat_id)
    caption = resolve_message_caption(message)
    text = str(message.get('text') or '').strip()
    has_image = message_has_image(message)

    if has_image and should_process_feed_photo(message, resolved_chat_id):
        if is_feed_pending(resolved_chat_id):
            clear_feed_pending(resolved_chat_id)
        reply = _ingest_photo_message(message, dry_run=dry_run)
        if reply.startswith('MY_FEED_'):
            return reply
        return format_needs_text_reply()

    if text and is_feed_pending(resolved_chat_id) and not text.startswith('/'):
        clear_feed_pending(resolved_chat_id)
        reply = _ingest_text_message(text, dry_run=dry_run)
        if reply.startswith('MY_FEED_'):
            return reply
        return format_needs_text_reply()

    return None


def handle_feed_photo_or_fail(
    message: dict[str, Any],
    *,
    dry_run: bool = False,
    chat_id: str | None = None,
) -> str:
    """Process pending/caption feed photos; never return None for eligible photos."""
    from backend.my_feed.feed_processor import format_needs_text_reply

    resolved_chat_id = resolve_feed_chat_id(message, chat_id)
    if not should_process_feed_photo(message, resolved_chat_id):
        return format_needs_text_reply()
    reply = process_feed_message(message, dry_run=dry_run, chat_id=resolved_chat_id)
    return reply or format_needs_text_reply()


def route_my_feed_telegram_media_first(
    message: dict[str, Any],
    *,
    dry_run: bool = False,
    chat_id: str | None = None,
) -> str | None:
    """
    Media-first My Feed router for live Telegram updates.
    Returns MY_FEED_* reply when this message is a feed photo/document, else None.
    """
    if not message_has_image(message):
        return None
    resolved_chat_id = resolve_feed_chat_id(message, chat_id)
    if not should_process_feed_photo(message, resolved_chat_id):
        return None
    if is_feed_pending(resolved_chat_id):
        clear_feed_pending(resolved_chat_id)
    return _ingest_photo_message(message, dry_run=dry_run)


def handle_telegram_feed_message(message: dict[str, Any], *, dry_run: bool = False) -> str | None:
    return process_feed_message(message, dry_run=dry_run)
