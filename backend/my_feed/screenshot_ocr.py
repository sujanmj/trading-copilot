"""
Temporary screenshot OCR for My Feed — delegates to shared image extraction (Stage 50B).
"""

from __future__ import annotations

from typing import Any

from backend.my_feed.image_extraction import extract_market_text_from_image_bytes as _extract_bytes


def extract_text_from_image_bytes(image_bytes: bytes, *, suffix: str = '.png') -> dict[str, Any]:
    result = _extract_bytes(image_bytes, suffix=suffix)
    return {
        'ok': bool(result.get('ok')),
        'text': str(result.get('text') or ''),
        'confidence': float(result.get('confidence') or 0.0),
        'error': str(result.get('error') or ''),
        'extracted': result.get('extracted') or {},
    }
