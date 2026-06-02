#!/usr/bin/env python3
"""
Inspect broker DB write review JSON.

Prints [BROKER_WRITE_REVIEW] summary and top review_only reasons.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def main() -> int:
    from backend.collectors.broker_db_write_gate import get_latest_broker_write_review

    review = get_latest_broker_write_review()
    if review.get('ok') is not True:
        print(f"[BROKER_WRITE_REVIEW] error={review.get('error') or review.get('warnings')}")
        return 1

    summary = review.get('summary') or {}
    print(f"[BROKER_WRITE_REVIEW] generated_at={review.get('generated_at')}")
    print(f"[BROKER_WRITE_REVIEW] candidates={summary.get('total_candidates', 0)}")
    print(f"[BROKER_WRITE_REVIEW] write_safe={summary.get('write_safe', 0)}")
    print(f"[BROKER_WRITE_REVIEW] review_only={summary.get('review_only', 0)}")
    print(f"[BROKER_WRITE_REVIEW] rejected={summary.get('rejected', 0)}")
    print(f"[BROKER_WRITE_REVIEW] duplicates={summary.get('duplicates', 0)}")

    reason_counts: Counter[str] = Counter()
    for row in review.get('review_only') or []:
        if not isinstance(row, dict):
            continue
        reason = str(row.get('reason') or 'unknown')
        reason_counts[reason] += 1

    print('[BROKER_WRITE_REVIEW] top_review_only_reasons:')
    for reason, count in reason_counts.most_common(8):
        print(f'  {reason}={count}')

    for row in (review.get('write_safe') or [])[:5]:
        if not isinstance(row, dict):
            continue
        print(
            f"[BROKER_WRITE_REVIEW] write_safe_sample | {row.get('ticker')} | "
            f"{row.get('direction')} | {(row.get('title') or '')[:70]}"
        )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
