#!/usr/bin/env python3
"""
Audit external evidence classification quality.

Prints EXTERNAL_EVIDENCE_CLASSIFICATION_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

EXPLICIT_BULLISH_RE = re.compile(
    r'\b(buy|accumulate|outperform|upgrade\s+to\s+buy|must\s+buy|target\s+price|upside)\b',
    re.IGNORECASE,
)
WATCH_TEXT_RE = re.compile(r'\b(stocks?\s+to\s+watch|watchlist|in\s+focus)\b', re.IGNORECASE)
BROKER_TERMS_RE = re.compile(
    r'\b(buy\s+call|sell\s+call|brokerage|recommends?|accumulate|target\s+price)\b',
    re.IGNORECASE,
)
MARKET_TERMS_RE = re.compile(r'\b(nifty|sensex|bank\s+nifty|closing\s+bell|market\s+wrap)\b', re.IGNORECASE)


def _fail(msg: str) -> int:
    print(f'EXTERNAL_EVIDENCE_CLASSIFICATION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_app_collector import load_external_evidence_cache

    cache = load_external_evidence_cache()
    if not cache.get('items'):
        from backend.collectors.broker_app_collector import build_external_evidence_cache

        cache = build_external_evidence_cache(limit=500)

    items = cache.get('items') if isinstance(cache.get('items'), list) else []
    fake_predictions = int(cache.get('fake_predictions') or 0)
    if fake_predictions != 0:
        return _fail(f'fake_predictions={fake_predictions}')

    for index, row in enumerate(items, start=1):
        if not isinstance(row, dict):
            return _fail(f'item {index} is not an object')

        token = str(row.get('classification') or '')
        title = str(row.get('title') or '')
        text = title
        direction = str(row.get('direction') or '').upper()

        if token == 'reject' and not row.get('rejection_reason'):
            return _fail(f'reject item {index} missing rejection_reason')

        if token == 'market_context' and BROKER_TERMS_RE.search(text) and row.get('ticker'):
            return _fail(f'market_context item {index} looks like broker prediction')

        if token == 'stock_news_evidence':
            if direction == 'BULLISH' and not EXPLICIT_BULLISH_RE.search(text):
                return _fail(f'stock_news item {index} is BULLISH without explicit buy terms')
            if WATCH_TEXT_RE.search(text) and direction == 'BULLISH' and not EXPLICIT_BULLISH_RE.search(text):
                return _fail(f'WATCH text converted to BULLISH at item {index}')

        if token == 'broker_prediction_candidate' and not row.get('ticker'):
            return _fail(f'broker candidate item {index} missing ticker')

        if token == 'market_context' and not MARKET_TERMS_RE.search(text):
            pass

    summary = cache.get('summary') if isinstance(cache.get('summary'), dict) else {}
    accepted = int(summary.get('accepted') or 0)
    total_raw = int(summary.get('total_raw') or 0)

    print(f'[EXT_EVIDENCE_AUDIT] total_raw={total_raw} accepted={accepted}')
    print(f'[EXT_EVIDENCE_AUDIT] broker_prediction_candidate={summary.get("broker_prediction_candidate", 0)}')
    print(f'[EXT_EVIDENCE_AUDIT] stock_news_evidence={summary.get("stock_news_evidence", 0)}')
    print(f'[EXT_EVIDENCE_AUDIT] market_context={summary.get("market_context", 0)}')
    print(f'[EXT_EVIDENCE_AUDIT] macro_context={summary.get("macro_context", 0)}')
    print(f'[EXT_EVIDENCE_AUDIT] rejected={summary.get("rejected", 0)}')
    print(f'[EXT_EVIDENCE_AUDIT] fake_predictions={fake_predictions}')
    print('EXTERNAL_EVIDENCE_CLASSIFICATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
