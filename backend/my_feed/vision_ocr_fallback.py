"""
Safe vision OCR fallback for My Feed screenshots (Stage 50E).

Uses in-memory image bytes only — never stores screenshots or filenames.
Provider names must not appear in Telegram/GUI output.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

_VISION_PROMPT = (
    'Extract only the visible text from this phone notification screenshot. '
    'Return plain text lines only. Do not invent text. '
    'If unreadable, return an empty response.'
)


def is_vision_ocr_fallback_available() -> bool:
    """True when a vision extraction path can be attempted (Railway-safe check)."""
    try:
        from backend.ai.provider_manager import get_gemini_pool

        pool = get_gemini_pool()
        return not pool.is_degraded()
    except Exception:
        return False


def _image_to_png_b64(image: Any) -> str:
    buf = BytesIO()
    if getattr(image, 'mode', '') not in ('RGB', 'L'):
        image = image.convert('RGB')
    image.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('ascii')


def _call_vision_extract(api_key: str, model_name: str, image_b64: str, *, max_tokens: int = 1200) -> str:
    import requests

    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/'
        f'{model_name}:generateContent?key={api_key}'
    )
    payload = {
        'contents': [{
            'parts': [
                {'text': _VISION_PROMPT},
                {'inline_data': {'mime_type': 'image/png', 'data': image_b64}},
            ],
        }],
        'generationConfig': {
            'maxOutputTokens': max_tokens,
            'temperature': 0.1,
        },
    }
    response = requests.post(url, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()
    parts = (
        ((data.get('candidates') or [{}])[0].get('content') or {}).get('parts')
        or []
    )
    chunks: list[str] = []
    for part in parts:
        text = str(part.get('text') or '').strip()
        if text:
            chunks.append(text)
    return '\n'.join(chunks).strip()


def extract_text(image: Any) -> str:
    """Extract raw OCR text from a PIL image via safe vision fallback."""
    try:
        from backend.ai.provider_manager import get_gemini_pool

        pool = get_gemini_pool()
        if pool.is_degraded():
            return ''

        image_b64 = _image_to_png_b64(image)

        def _invoke(api_key: str, slot_id: str) -> tuple[str, float]:
            try:
                text = _call_vision_extract(api_key, 'gemini-2.0-flash-lite', image_b64)
                if text:
                    return text, 0.0
                text = _call_vision_extract(api_key, 'gemini-2.0-flash', image_b64)
                return text, 0.0
            except Exception:
                return '', 0.0

        result, _meta = pool.execute_with_failover(_invoke, model_label='gemini-2.0-flash-lite')
        return str(result or '').strip()
    except Exception:
        return ''
