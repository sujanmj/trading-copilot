"""
Temporary screenshot OCR for My Feed — delegates to shared image extraction (Stage 50D).
"""

from __future__ import annotations

from typing import Any

from backend.my_feed.image_extraction import extract_market_text_from_image_bytes as _extract_bytes


def extract_text_from_image_bytes(image_bytes: bytes, *, suffix: str = '.png') -> dict[str, Any]:
    result = _extract_bytes(image_bytes, suffix=suffix)
    return {
        'ok': bool(result.get('ok')),
        'text': str(result.get('text') or ''),
        'notifications': list(result.get('notifications') or []),
        'ignored_private_count': int(result.get('ignored_private_count') or 0),
        'needs_text': bool(result.get('needs_text')),
        'confidence': float(result.get('confidence') or 0.0),
        'error': str(result.get('error') or ''),
        'extracted': result.get('extracted') or {},
    }
