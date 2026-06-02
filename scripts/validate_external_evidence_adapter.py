#!/usr/bin/env python3
"""
Validate external evidence adapter module.

Usage:
  python scripts/validate_external_evidence_adapter.py

Prints exactly EXTERNAL_EVIDENCE_ADAPTER_OK on success.
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
    print(f'EXTERNAL_EVIDENCE_ADAPTER_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics import external_evidence_adapter as adapter
    from backend.analytics.external_evidence_adapter import (
        EXTERNAL_EVIDENCE_CAP,
        get_external_evidence_summary,
        get_market_context_summary,
        get_ticker_external_evidence,
        score_external_evidence,
    )

    for name in (
        'get_external_evidence_summary',
        'get_ticker_external_evidence',
        'get_market_context_summary',
        'score_external_evidence',
    ):
        if not callable(getattr(adapter, name, None)):
            return _fail(f'missing function: {name}')

    summary = get_external_evidence_summary()
    if summary.get('ok') is not True:
        return _fail(f'get_external_evidence_summary failed: {summary.get("error")}')

    for key in (
        'accepted',
        'stock_news_evidence',
        'market_context',
        'macro_context',
        'broker_prediction_candidate',
    ):
        if key not in summary:
            return _fail(f'summary missing key: {key}')

    context = get_market_context_summary(limit=5)
    if context.get('ok') is not True:
        return _fail('get_market_context_summary ok != true')
    if 'market_context_count' not in context or 'macro_context_count' not in context:
        return _fail('market context summary missing counts')

    ticker = get_ticker_external_evidence('RELIANCE')
    for key in (
        'ok',
        'ticker',
        'items',
        'counts',
        'score_adjustment',
        'warnings',
        'summary_reason',
    ):
        if key not in ticker:
            return _fail(f'get_ticker_external_evidence missing key: {key}')

    counts = ticker.get('counts') or {}
    for bucket in ('positive', 'negative', 'watch', 'neutral'):
        if bucket not in counts:
            return _fail(f'counts missing bucket: {bucket}')

    mcx = get_ticker_external_evidence('MCX')
    broker_skipped = int(mcx.get('broker_candidates_skipped') or 0)
    if broker_skipped <= 0:
        return _fail('MCX should skip broker_prediction_candidate from ticker scoring')

    scored = score_external_evidence({'ticker': 'RELIANCE'}, pre_decision='WATCH')
    adj = int(scored.get('confidence_adjustment') or 0)
    if abs(adj) > EXTERNAL_EVIDENCE_CAP:
        return _fail(f'adjustment {adj} exceeds cap {EXTERNAL_EVIDENCE_CAP}')

    neutral_only = score_external_evidence({'ticker': 'RELIANCE'}, pre_decision='AVOID')
    if int(neutral_only.get('confidence_adjustment') or 0) > 0:
        counts_rel = (neutral_only.get('counts') or {})
        if int(counts_rel.get('positive') or 0) == 0:
            pass
        elif int(neutral_only.get('confidence_adjustment') or 0) > 0:
            return _fail('positive external ignored when pre_decision is AVOID')

    print('EXTERNAL_EVIDENCE_ADAPTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
