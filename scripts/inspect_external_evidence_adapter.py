#!/usr/bin/env python3
"""
Inspect external evidence adapter output.

Usage:
  python scripts/inspect_external_evidence_adapter.py
  python scripts/inspect_external_evidence_adapter.py --ticker RELIANCE
  python scripts/inspect_external_evidence_adapter.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect external evidence adapter.')
    parser.add_argument('--ticker', default=None, help='Optional ticker for stock news evidence')
    parser.add_argument('--json', action='store_true', help='Emit JSON only')
    args = parser.parse_args()

    from backend.analytics.external_evidence_adapter import (
        get_external_evidence_summary,
        get_market_context_summary,
        get_ticker_external_evidence,
        score_external_evidence,
    )

    summary = get_external_evidence_summary()
    context = get_market_context_summary(limit=8)

    if args.json:
        payload = {'summary': summary, 'market_context': context}
        if args.ticker:
            payload['ticker'] = get_ticker_external_evidence(args.ticker)
            payload['sample_score'] = score_external_evidence(
                {'ticker': args.ticker, 'decision': 'WATCH'},
                pre_decision='WATCH',
            )
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(f'[EXT_ADAPTER] ok={summary.get("ok")} accepted={summary.get("accepted", 0)}')
    print(
        f'[EXT_ADAPTER] stock_news={summary.get("stock_news_evidence", 0)} '
        f'market={summary.get("market_context", 0)} macro={summary.get("macro_context", 0)} '
        f'broker_candidates={summary.get("broker_prediction_candidate", 0)}',
    )
    print(
        f'[EXT_ADAPTER] context_items={len(context.get("items") or [])} '
        f'context_warnings={len(context.get("warnings") or [])}',
    )

    if args.ticker:
        ticker_payload = get_ticker_external_evidence(args.ticker)
        counts = ticker_payload.get('counts') or {}
        print(
            f'[EXT_ADAPTER] ticker={args.ticker} items={len(ticker_payload.get("items") or [])} '
            f'counts={counts} adjustment={ticker_payload.get("score_adjustment", 0)}',
        )
        for item in (ticker_payload.get('items') or [])[:3]:
            print(
                f'[EXT_ADAPTER] headline={str(item.get("title") or "")[:90]} '
                f'direction={item.get("direction")}',
            )
        scored = score_external_evidence(
            {'ticker': args.ticker, 'decision': 'WATCH'},
            pre_decision='WATCH',
        )
        print(
            f'[EXT_ADAPTER] score_adj={scored.get("confidence_adjustment")} '
            f'warnings={scored.get("warnings")}',
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
