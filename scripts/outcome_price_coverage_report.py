#!/usr/bin/env python3
"""
Outcome price coverage report — Stage 49C.

Usage:
  python scripts/outcome_price_coverage_report.py
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


def main() -> int:
    try:
        from backend.storage.outcome_price_lookup import build_price_coverage_report

        report = build_price_coverage_report()
    except Exception:
        report = {
            'pending_total': 0,
            'has_reference_price': 0,
            'has_evaluation_price': 0,
            'resolvable_now': 0,
            'missing_reference': 0,
            'missing_evaluation': 0,
            'missing_both': 0,
            'top_missing_tickers': [],
        }

    top = report.get('top_missing_tickers') or []
    top_txt = ','.join(str(t) for t in top[:10]) if top else 'none'
    print('OUTCOME_PRICE_COVERAGE_REPORT_OK', flush=True)
    print(f"pending_total={int(report.get('pending_total') or 0)}", flush=True)
    print(f"has_reference_price={int(report.get('has_reference_price') or 0)}", flush=True)
    print(f"has_evaluation_price={int(report.get('has_evaluation_price') or 0)}", flush=True)
    print(f"resolvable_now={int(report.get('resolvable_now') or 0)}", flush=True)
    print(f"missing_reference={int(report.get('missing_reference') or 0)}", flush=True)
    print(f"missing_evaluation={int(report.get('missing_evaluation') or 0)}", flush=True)
    print(f"missing_both={int(report.get('missing_both') or 0)}", flush=True)
    print(f'top_missing_tickers={top_txt}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
