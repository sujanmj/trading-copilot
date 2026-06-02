#!/usr/bin/env python3
"""
Inspect external evidence classification cache.

Prints [EXT_EVIDENCE] lines and EXTERNAL_EVIDENCE_INSPECT_OK.
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
    print(f'EXTERNAL_EVIDENCE_INSPECT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_app_collector import (
        EXTERNAL_EVIDENCE_CACHE_FILE,
        get_external_evidence_dashboard,
        load_external_evidence_cache,
    )

    cache = load_external_evidence_cache()
    if cache.get('ok') is not True and not cache.get('items'):
        from backend.collectors.broker_app_collector import build_external_evidence_cache

        cache = build_external_evidence_cache(limit=500)

    dashboard = get_external_evidence_dashboard()
    summary = dashboard.get('summary') or cache.get('summary') or {}

    print(f"[EXT_EVIDENCE] path={EXTERNAL_EVIDENCE_CACHE_FILE.name}")
    print(f"[EXT_EVIDENCE] generated_at={dashboard.get('generated_at') or cache.get('generated_at')}")
    print(f"[EXT_EVIDENCE] total_raw={summary.get('total_raw', 0)}")
    print(f"[EXT_EVIDENCE] accepted={summary.get('accepted', 0)}")
    print(f"[EXT_EVIDENCE] broker_prediction_candidate={summary.get('broker_prediction_candidate', 0)}")
    print(f"[EXT_EVIDENCE] stock_news_evidence={summary.get('stock_news_evidence', 0)}")
    print(f"[EXT_EVIDENCE] market_context={summary.get('market_context', 0)}")
    print(f"[EXT_EVIDENCE] macro_context={summary.get('macro_context', 0)}")
    print(f"[EXT_EVIDENCE] rejected={summary.get('rejected', 0)}")
    print(f"[EXT_EVIDENCE] unique_tickers={summary.get('unique_tickers', 0)}")
    print(f"[EXT_EVIDENCE] fake_predictions={dashboard.get('fake_predictions', 0)}")
    print(f"[EXT_EVIDENCE] rejection_reasons={dashboard.get('rejection_reasons') or cache.get('rejection_reasons') or {}}")

    for bucket, key in (
        ('broker_candidates', 'broker_candidates'),
        ('stock_news', 'stock_news'),
        ('market_context', 'market_context_items'),
        ('macro_context', 'macro_context_items'),
    ):
        rows = dashboard.get(key) or dashboard.get(bucket) or []
        for row in rows[:3]:
            print(
                f"[EXT_EVIDENCE] sample {bucket} | "
                f"{row.get('ticker') or '-'} | "
                f"{row.get('direction', '-')} | "
                f"{(row.get('title') or '-')[:70]}"
            )

    print('EXTERNAL_EVIDENCE_INSPECT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
