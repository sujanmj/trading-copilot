#!/usr/bin/env python3
"""Stage 50F — Groq vision JSON contract parsing."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_GROQ_VISION_JSON_CONTRACT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed import groq_vision_fallback

    src = (PROJECT_ROOT / 'backend/my_feed/groq_vision_fallback.py').read_text(encoding='utf-8')
    if 'response_format' not in src or 'json_object' not in src:
        return _fail('Groq vision call must request json_object response_format')
    if '"items"' not in src or '"confidence"' not in src:
        return _fail('vision prompt must define strict JSON contract')

    sample = '''```json
{
  "items": [{
    "raw_market_text": "Inshorts: Iran attacks US bases",
    "cleaned_summary": "Iran attacks US bases in Kuwait, Jordan, Bahrain",
    "detected_source_app": "Inshorts",
    "tickers": [],
    "entities": ["IRAN","US"],
    "themes": ["Geopolitical"],
    "event_type": "geopolitical",
    "sentiment": "geopolitical",
    "impact_score": 80,
    "urgency": "high",
    "suggested_action": "MARKET RISK ALERT",
    "confirmation_required": false
  }],
  "ignored_private_items": 0,
  "confidence": 0.88
}
```'''
    parsed = groq_vision_fallback._parse_json_payload(sample)
    normalized = groq_vision_fallback._normalize_vision_items(parsed)
    items = normalized.get('items') or []
    if not items:
        return _fail('JSON contract parser must yield vision items')
    if float(normalized.get('confidence') or 0) < 0.5:
        return _fail('confidence must parse from JSON contract')

    low = groq_vision_fallback._normalize_vision_items({'items': [], 'confidence': 0.2})
    if low.get('items'):
        return _fail('empty items must remain empty after normalize')

    print('MYFEED_GROQ_VISION_JSON_CONTRACT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
