"""
Telegram Screener file intake — Phase 4B.14A.

Download CSV/XLSX attachments and import into Screener memory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

STAGE = '4B.14A'
SCREENER_IMPORT_CAPTION = '/screener import longterm'
_SUPPORTED_EXTENSIONS = ('.csv', '.xlsx')


def _normalize_caption(text: str) -> str:
    from backend.telegram.telegram_command_normalize import normalize_slash_command

    return normalize_slash_command(str(text or '').strip()).lower()


def is_screener_import_caption(text: str) -> bool:
    return _normalize_caption(text) == 'screener import longterm'


def is_supported_screener_filename(name: str) -> bool:
    return str(name or '').lower().endswith(_SUPPORTED_EXTENSIONS)


def download_telegram_file(file_id: str, *, bot_token: str = '') -> bytes:
    token = str(bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')).strip()
    if not token or not file_id:
        return b''
    api = f'https://api.telegram.org/bot{token}'
    try:
        meta = requests.get(f'{api}/getFile', params={'file_id': file_id}, timeout=15).json()
        file_path = str((meta.get('result') or {}).get('file_path') or '')
        if not file_path:
            return b''
        resp = requests.get(f'https://api.telegram.org/file/bot{token}/{file_path}', timeout=60)
        if resp.status_code != 200:
            return b''
        return resp.content
    except Exception:
        return b''


def try_handle_screener_document(message: dict[str, Any], *, caption: str = '') -> str | None:
    """
    Handle Telegram document with /screener import longterm caption.

    Returns reply text, or None if not a Screener import message.
    """
    cap = str(caption or message.get('caption') or message.get('text') or '').strip()
    if not is_screener_import_caption(cap):
        return None

    doc = message.get('document') or {}
    if not doc:
        return None

    fname = str(doc.get('file_name') or 'screener_import.csv')
    if not is_supported_screener_filename(fname):
        return 'Unsupported file type. Upload CSV or XLSX.'

    file_id = str(doc.get('file_id') or '')
    payload = download_telegram_file(file_id)
    if not payload:
        return 'Could not download Telegram attachment. Retry upload.'

    from backend.trading.screener_memory import save_import_bytes, import_screener_file
    from backend.telegram.response_format import format_screener_import_success_telegram

    try:
        saved = save_import_bytes(payload, fname)
        result = import_screener_file(saved, screen_name=saved.stem, query_text=saved.stem)
        return format_screener_import_success_telegram(result)
    except Exception as exc:
        return f'Screener import failed: {str(exc)[:160]}'
