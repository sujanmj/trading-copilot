#!/usr/bin/env python3
"""
Audit external evidence classification precision (Stage 39D).

Prints EXTERNAL_EVIDENCE_PRECISION_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EXTERNAL_EVIDENCE_PRECISION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_app_collector import load_external_evidence_cache
    from backend.collectors.external_evidence_classifier import (
        EXPLICIT_BULLISH_RE,
        PURE_PRICE_MOVEMENT_RE,
        WATCH_TEXT_RE,
        has_explicit_recommendation_signal,
    )

    cache = load_external_evidence_cache()
    if not cache.get('items'):
        from backend.collectors.broker_app_collector import build_external_evidence_cache

        cache = build_external_evidence_cache(limit=500)

    items = cache.get('items') if isinstance(cache.get('items'), list) else []
    fake_predictions = int(cache.get('fake_predictions') or 0)
    if fake_predictions != 0:
        return _fail(f'fake_predictions={fake_predictions}')

    broker_candidates = 0
    stock_news = 0
    precision_warnings = 0

    for index, row in enumerate(items, start=1):
        if not isinstance(row, dict):
            return _fail(f'item {index} is not an object')

        token = str(row.get('classification') or '')
        title = str(row.get('title') or '')
        body = str((row.get('raw_payload') or {}).get('description') or '')
        text = f'{title} {body}'.strip()
        direction = str(row.get('direction') or '').upper()

        if token == 'broker_prediction_candidate':
            broker_candidates += 1
            has_signal, _ = has_explicit_recommendation_signal(text)
            if PURE_PRICE_MOVEMENT_RE.search(text) and not has_signal:
                precision_warnings += 1
                return _fail(f'broker candidate {index} is pure price movement: {title[:80]}')
            if direction == 'BULLISH' and row.get('negative_override_applied'):
                precision_warnings += 1
                return _fail(f'broker candidate {index} BULLISH despite negative override')
            if WATCH_TEXT_RE.search(text) and direction == 'BULLISH' and not EXPLICIT_BULLISH_RE.search(text):
                precision_warnings += 1
                return _fail(f'stocks-to-watch item {index} is BULLISH without explicit buy')
            downgrade_neutral = 'downgrade' in text.lower() and 'neutral' in text.lower()
            if downgrade_neutral and direction == 'BULLISH':
                precision_warnings += 1
                return _fail(f'downgrade/neutral item {index} is BULLISH: {title[:80]}')

        if token == 'stock_news_evidence':
            stock_news += 1
            if WATCH_TEXT_RE.search(text) and direction == 'BULLISH' and not EXPLICIT_BULLISH_RE.search(text):
                precision_warnings += 1
                return _fail(f'stock news watch item {index} is BULLISH without explicit buy')

    print(f'[EXT_PRECISION] broker_candidates={broker_candidates}')
    print(f'[EXT_PRECISION] stock_news={stock_news}')
    print(f'[EXT_PRECISION] precision_warnings={precision_warnings}')
    print('EXTERNAL_EVIDENCE_PRECISION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
