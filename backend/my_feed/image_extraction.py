"""
Shared My Feed image → market text extraction (Stage 50B).

Temp files only; never persists images. No hallucination on OCR failure.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.my_feed.text_extractor import filter_market_text


def extract_market_text_from_image_temp(image_path: str | Path) -> dict[str, Any]:
    path = Path(image_path)
    if not path.is_file():
        return {'ok': False, 'text': '', 'error': 'missing_file', 'extracted': {}}

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return {'ok': False, 'text': '', 'error': 'pil_unavailable', 'extracted': {}}

    try:
        import pytesseract  # type: ignore
    except ImportError:
        return {'ok': False, 'text': '', 'error': 'tesseract_unavailable', 'extracted': {}}

    try:
        image = Image.open(path)
        raw_text = str(pytesseract.image_to_string(image) or '').strip()
    except Exception as exc:
        return {'ok': False, 'text': '', 'error': str(exc)[:120], 'extracted': {}}

    if len(raw_text) < 12:
        return {'ok': False, 'text': raw_text, 'error': 'low_confidence', 'extracted': {}}

    extracted = filter_market_text(raw_text)
    cleaned = str(extracted.get('cleaned_summary') or '').strip()
    if not cleaned:
        return {
            'ok': False,
            'text': raw_text,
            'error': 'no_market_lines',
            'extracted': extracted,
        }

    confidence = 0.85 if len(cleaned) >= 40 else 0.55
    return {
        'ok': True,
        'text': raw_text,
        'cleaned_summary': cleaned,
        'confidence': confidence,
        'extracted': extracted,
        'error': '',
    }


def extract_market_text_from_image_bytes(image_bytes: bytes, *, suffix: str = '.png') -> dict[str, Any]:
    import tempfile

    if not image_bytes:
        return {'ok': False, 'text': '', 'error': 'empty_image', 'extracted': {}}

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(image_bytes)
            temp_path = Path(tmp.name)
        return extract_market_text_from_image_temp(temp_path)
    finally:
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass
