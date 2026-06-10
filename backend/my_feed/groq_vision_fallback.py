"""
Groq vision fallback for My Feed screenshot extraction (Stage 50F).

In-memory image only — never persists base64, paths, or filenames.
Provider names must not appear in Telegram/GUI output.
"""

from __future__ import annotations

import base64
import json
import os
import re
from io import BytesIO
from typing import Any

from backend.my_feed.suggested_actions import (
    myfeed_action_options_for_prompt,
    normalize_myfeed_suggested_action,
)

_MIN_CONFIDENCE = 0.55
_MAX_OUTPUT_TOKENS = 900
_REQUEST_TIMEOUT = 15
_MAX_IMAGE_WIDTH = 1024
_DEFAULT_MODEL = 'meta-llama/llama-4-scout-17b-16e-instruct'

_VISION_JSON_PROMPT = f"""You extract market/news/finance notifications from a phone screenshot.
Return ONLY valid JSON (no markdown) in this exact shape:
{{
  "items": [
    {{
      "raw_market_text": "...",
      "cleaned_summary": "...",
      "detected_source_app": "Inshorts|INDmoney|unknown",
      "tickers": [],
      "entities": [],
      "themes": [],
      "event_type": "...",
      "sentiment": "bullish|bearish|neutral|geopolitical|macro|commodity|unknown",
      "impact_score": 0,
      "urgency": "low|medium|high",
      "suggested_action": "{myfeed_action_options_for_prompt()}",
      "confirmation_required": "price + volume confirmation"
    }}
  ],
  "ignored_private_items": 0,
  "confidence": 0.0
}}

Rules:
- Ignore Instagram, Snapchat, Facebook, Reddit social, personal chats, location widgets,
  payment widgets, battery/time/date/home text, unrelated ads.
- Keep only market movement, stock alerts, commodity alerts, geopolitical/macro market news,
  broker/analyst/earnings/order/JV/corporate action news.
- Do not invent text not visible in the screenshot.
- If unreadable or only private content, return {{"items": [], "ignored_private_items": 0, "confidence": 0.0}}
- Use only the allowed suggested_action values listed above; never output direct trade instructions.
- confidence is 0.0-1.0 for overall extraction quality.
"""


def get_myfeed_vision_model() -> str:
    return str(os.environ.get('MYFEED_VISION_MODEL') or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def is_groq_vision_available() -> bool:
    try:
        from backend.ai.provider_manager import get_groq_pool

        pool = get_groq_pool()
        return bool(pool._keys) and not pool.is_degraded()
    except Exception:
        return False


def is_vision_ocr_fallback_available() -> bool:
    """Backward-compatible alias used by image_extraction."""
    return is_groq_vision_available()


def _compress_image_for_request(image: Any) -> tuple[bytes, str]:
    from PIL import Image  # type: ignore

    img = image
    if getattr(img, 'mode', '') not in ('RGB', 'L'):
        img = img.convert('RGB')
    width, height = img.size
    if width > _MAX_IMAGE_WIDTH and width > 0:
        scale = _MAX_IMAGE_WIDTH / float(width)
        img = img.resize((int(width * scale), int(height * scale)))
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=82, optimize=True)
    return buf.getvalue(), 'image/jpeg'


def _image_to_data_url(image: Any) -> str:
    raw, mime = _compress_image_for_request(image)
    encoded = base64.b64encode(raw).decode('ascii')
    return f'data:{mime};base64,{encoded}'


def _call_groq_vision_rest(api_key: str, model_name: str, data_url: str) -> str:
    import requests

    url = 'https://api.groq.com/openai/v1/chat/completions'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': model_name,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': _VISION_JSON_PROMPT},
                {'type': 'image_url', 'image_url': {'url': data_url}},
            ],
        }],
        'max_tokens': _MAX_OUTPUT_TOKENS,
        'temperature': 0.1,
        'response_format': {'type': 'json_object'},
    }
    response = requests.post(url, json=payload, headers=headers, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return str(((data.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()


def _parse_json_payload(raw: str) -> dict[str, Any]:
    text = str(raw or '').strip()
    if not text:
        return {}
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, flags=re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group(0))
                return payload if isinstance(payload, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _sanitize_suggested_action(value: str) -> str:
    return normalize_myfeed_suggested_action(value, fallback='NEWS ONLY')


def _normalize_vision_items(payload: dict[str, Any]) -> dict[str, Any]:
    from backend.my_feed.text_extractor import (
        correct_fuzzy_tickers,
        filter_market_text,
        split_entity_tokens,
    )

    items_in = payload.get('items') or []
    if not isinstance(items_in, list):
        items_in = []

    normalized: list[dict[str, Any]] = []
    ignored = int(payload.get('ignored_private_items') or 0)

    for row in items_in:
        if not isinstance(row, dict):
            continue
        raw_text = str(row.get('raw_market_text') or row.get('cleaned_summary') or '').strip()
        cleaned = str(row.get('cleaned_summary') or raw_text).strip()
        if not cleaned:
            continue
        filtered = filter_market_text(cleaned)
        cleaned_final = str(filtered.get('cleaned_summary') or '').strip()
        if not cleaned_final:
            ignored += 1
            continue
        ignored += int(filtered.get('ignored_private_items') or 0)

        tickers = correct_fuzzy_tickers(list(row.get('tickers') or []), cleaned_final)
        if not tickers:
            tickers = correct_fuzzy_tickers(filtered.get('tickers') or [], cleaned_final)
        entities = split_entity_tokens(list(row.get('entities') or []), cleaned_final)
        for ticker in tickers:
            if ticker not in entities:
                entities.append(ticker)

        normalized.append({
            'raw_market_text': raw_text or cleaned_final,
            'cleaned_summary': cleaned_final,
            'detected_source_app': str(row.get('detected_source_app') or filtered.get('detected_source_app') or 'unknown'),
            'tickers': tickers,
            'entities': entities,
            'themes': [str(t).strip() for t in (row.get('themes') or []) if str(t).strip()],
            'event_type': str(row.get('event_type') or 'news'),
            'sentiment': str(row.get('sentiment') or 'neutral'),
            'impact_score': float(row.get('impact_score') or 0),
            'urgency': str(row.get('urgency') or 'medium'),
            'suggested_action': _sanitize_suggested_action(str(row.get('suggested_action') or '')),
            'confirmation_required': bool(row.get('confirmation_required')),
        })

    confidence = float(payload.get('confidence') or 0.0)
    return {
        'items': normalized,
        'ignored_private_items': ignored,
        'confidence': confidence,
    }


def extract_market_items(image: Any) -> dict[str, Any]:
    """Extract structured My Feed items from screenshot via Groq vision."""
    empty = {
        'ok': False,
        'items': [],
        'ignored_private_items': 0,
        'confidence': 0.0,
        'needs_text': True,
    }
    if not is_groq_vision_available():
        return empty

    try:
        data_url = _image_to_data_url(image)
        model = get_myfeed_vision_model()

        from backend.ai.provider_manager import get_groq_pool

        pool = get_groq_pool()

        def _invoke(api_key: str, slot_id: str) -> tuple[dict[str, Any], float]:
            try:
                raw = _call_groq_vision_rest(api_key, model, data_url)
                parsed = _parse_json_payload(raw)
                normalized = _normalize_vision_items(parsed)
                return normalized, 0.0
            except Exception:
                return {}, 0.0

        result, _meta = pool.execute_with_failover(_invoke, model_label=model)
        if not isinstance(result, dict):
            return empty

        items = list(result.get('items') or [])
        confidence = float(result.get('confidence') or 0.0)
        ignored = int(result.get('ignored_private_items') or 0)

        if not items or confidence < _MIN_CONFIDENCE:
            return {
                'ok': False,
                'items': [],
                'ignored_private_items': ignored,
                'confidence': confidence,
                'needs_text': True,
            }

        return {
            'ok': True,
            'items': items,
            'ignored_private_items': ignored,
            'confidence': confidence,
            'needs_text': False,
        }
    except Exception:
        return empty


def extract_text(image: Any) -> str:
    """Flatten structured vision items to text for legacy OCR fallback hook."""
    result = extract_market_items(image)
    if not result.get('ok'):
        return ''
    lines = [str(item.get('cleaned_summary') or '').strip() for item in (result.get('items') or [])]
    return '\n'.join(line for line in lines if line)
