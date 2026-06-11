"""
Telegram My Feed intake — text-only (Stage 50G).
"""

from __future__ import annotations

from typing import Any

FEED_TEXT_ONLY_USAGE = (
    'Send market news as text:\n'
    '/feed <market news text>'
)

FEED_TEXT_ONLY_IMAGE_REPLY = (
    'My Feed is text-only now. Please type or paste the news:\n'
    '/feed <market news text>'
)

MYFEED_SUBCOMMAND_USAGE = (
    'Use /myfeed list · /myfeed today · /myfeed scan'
)

MYFEED_CLEAN_OLD_USAGE = (
    'Usage: /myfeed clean-old — archive pre-50G image/OCR dirty rows (admin only)'
)


def message_has_image(message: dict[str, Any]) -> bool:
    if message.get('photo'):
        return True
    doc = message.get('document') or {}
    mime = str(doc.get('mime_type') or '').lower()
    if mime.startswith('image/'):
        return True
    fname = str(doc.get('file_name') or '').lower()
    return fname.endswith(('.png', '.jpg', '.jpeg', '.webp', '.heic', '.gif'))


def format_feed_text_only_image_reply() -> str:
    return FEED_TEXT_ONLY_IMAGE_REPLY


def handle_telegram_feed_message(message: dict[str, Any], *, dry_run: bool = False) -> str | None:
    """Legacy hook — images only; returns text-only guidance."""
    if message_has_image(message):
        return format_feed_text_only_image_reply()
    return None
