#!/usr/bin/env python3
"""
Audit external evidence ticker matching precision (Stage 40B).

Usage:
  python scripts/audit_external_evidence_ticker_matching.py

Prints EXTERNAL_EVIDENCE_TICKER_MATCHING_OK on success.
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


def _fail(msg: str) -> int:
    print(f'EXTERNAL_EVIDENCE_TICKER_MATCHING_FAIL: {msg}', file=sys.stderr)
    return 1


RELIANCE_TITLE_RE = re.compile(
    r'\b(?:RELIANCE|RIL|Reliance(?:\s+(?:Industries|Communications|Petroleum))?)\b',
    re.IGNORECASE,
)


def _title_ok_for_ticker(title: str, ticker: str) -> bool:
    text = str(title or '')
    token = ticker.upper()
    if token == 'RELIANCE':
        if re.search(r'\bdell\b', text, re.IGNORECASE):
            return False
        return bool(RELIANCE_TITLE_RE.search(text))
    if token == 'MCX':
        return bool(re.search(r'\bMCX\b', text, re.IGNORECASE))
    return True


def main() -> int:
    from backend.analytics.external_evidence_adapter import (
        BROKER_PRED_CLASS,
        get_ticker_external_evidence,
    )
    from backend.collectors.broker_app_collector import (
        build_external_evidence_cache,
        load_external_evidence_cache,
    )
    from backend.collectors.external_evidence_classifier import classify_external_item, load_universe

    cache = load_external_evidence_cache()
    if not cache.get('items'):
        cache = build_external_evidence_cache(limit=500)

    universe = load_universe()

    dell = classify_external_item({
        'title': 'Dell shares soar more than 30% on strong earnings',
        'description': (
            "Following robust financial results, Dell's stock soared, reflecting a successful "
            'pivot toward AI servers, surpassing the company\'s historical reliance on PC sales.'
        ),
        'source': 'Economic Times (Markets)',
    }, universe)
    if dell.get('classification') == 'stock_news_evidence' and dell.get('ticker') == 'RELIANCE':
        return _fail('Dell headline classified as RELIANCE stock news')

    reliance = classify_external_item({
        'title': 'Supreme Court provides relief to Reliance in 2007 securities market fraud case',
        'description': 'Reliance Industries Ltd received relief from Supreme Court',
        'source': 'Economic Times',
    }, universe)
    if reliance.get('ticker') != 'RELIANCE':
        return _fail(f'Reliance headline missing RELIANCE ticker: {reliance.get("ticker")}')

    mcx = classify_external_item({
        'title': 'Oil prices slip as U.S.-Iran deal awaited; Brent set for worst month since 2020',
        'description': 'Crude oil benchmarks declined ahead of talks',
        'source': 'Investing.com',
    }, universe)
    if mcx.get('ticker') == 'MCX':
        return _fail('macro headline incorrectly tagged MCX')

    rel_payload = get_ticker_external_evidence('RELIANCE')
    for row in rel_payload.get('items') or []:
        title = str(row.get('title') or '')
        if re.search(r'\bdell\b', title, re.IGNORECASE):
            return _fail(f'RELIANCE evidence includes Dell headline: {title[:80]}')
        if not _title_ok_for_ticker(title, 'RELIANCE'):
            return _fail(f'RELIANCE title not supported: {title[:80]}')
        matched = str(row.get('matched_ticker') or row.get('ticker') or '').upper()
        if matched and matched != 'RELIANCE':
            return _fail(f'matched_ticker mismatch: {matched}')

    mcx_payload = get_ticker_external_evidence('MCX')
    for row in mcx_payload.get('items') or []:
        if str(row.get('classification') or '') == BROKER_PRED_CLASS:
            return _fail('broker candidate leaked into MCX stock_news items')
        title = str(row.get('title') or '')
        if not _title_ok_for_ticker(title, 'MCX'):
            return _fail(f'MCX evidence unrelated headline: {title[:80]}')

    items = cache.get('items') if isinstance(cache.get('items'), list) else []
    for index, row in enumerate(items, start=1):
        if not isinstance(row, dict):
            continue
        if str(row.get('classification') or '') != 'stock_news_evidence':
            continue
        ticker = str(row.get('ticker') or '').upper()
        matched = str(row.get('matched_ticker') or row.get('ticker') or '').upper()
        if ticker and matched and ticker != matched:
            return _fail(f'item {index} ticker {ticker} != matched_ticker {matched}')

    print(f'[TICKER_MATCH] reliance_items={len(rel_payload.get("items") or [])}')
    print(f'[TICKER_MATCH] mcx_items={len(mcx_payload.get("items") or [])}')
    print('EXTERNAL_EVIDENCE_TICKER_MATCHING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
