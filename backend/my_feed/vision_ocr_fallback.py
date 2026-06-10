"""
Vision OCR fallback shim — Groq vision for My Feed (Stage 50F).
"""

from __future__ import annotations

from typing import Any

from backend.my_feed.groq_vision_fallback import (
    extract_market_items,
    extract_text,
    get_myfeed_vision_model,
    is_groq_vision_available,
    is_vision_ocr_fallback_available,
)

__all__ = [
    'extract_market_items',
    'extract_text',
    'get_myfeed_vision_model',
    'is_groq_vision_available',
    'is_vision_ocr_fallback_available',
]
