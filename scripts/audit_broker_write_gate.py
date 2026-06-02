#!/usr/bin/env python3
"""
Audit broker DB write gate against unsafe headline patterns.

Prints BROKER_WRITE_GATE_OK on success.
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

RALLY_RE = re.compile(r'\b(rally|rallied|surge|soar|jumped|gains?\s+\d)\b', re.IGNORECASE)
CREDIT_RE = re.compile(r"\b(credit\s+rating|moody'?s|crisil|icra)\b", re.IGNORECASE)
BLOCK_RE = re.compile(r'\b(block\s+deal|bulk\s+deal)\b', re.IGNORECASE)
QUESTION_RE = re.compile(
    r'\b(should\s+you\s+buy|buy,\s*sell\s+or\s*hold|buy\s+or\s+sell)\b',
    re.IGNORECASE,
)
TOP_PICK_RE = re.compile(r'\btop\s+picks?\b', re.IGNORECASE)
MANUAL_RE = re.compile(r'\bmanual\b', re.IGNORECASE)


def _fail(msg: str) -> int:
    print(f'BROKER_WRITE_GATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _title(row: dict) -> str:
    return str(row.get('title') or '')


def main() -> int:
    from backend.collectors.broker_app_collector import load_collector_cache
    from backend.collectors.broker_db_write_gate import get_latest_broker_write_review

    cache = load_collector_cache()
    fake_predictions = int(cache.get('fake_predictions') or 0)
    if fake_predictions != 0:
        return _fail(f'fake_predictions={fake_predictions}')

    review = get_latest_broker_write_review()
    if review.get('ok') is not True:
        return _fail('broker_db_write_review.json missing or invalid')

    write_safe = review.get('write_safe') or []
    review_only = review.get('review_only') or []

    for row in write_safe:
        if not isinstance(row, dict):
            continue
        title = _title(row)
        combined = f'{title} {row.get("source") or ""}'
        if RALLY_RE.search(title) and not TOP_PICK_RE.search(combined):
            if not re.search(r'\b(recommends?|upgrade|buy\s+call|target\s+price)\b', combined, re.I):
                return _fail(f'rally headline write_safe: {title[:80]}')
        if CREDIT_RE.search(title) and not re.search(
            r'\b(broker|analyst|recommends?|buy|sell|accumulate)\b', combined, re.I
        ):
            return _fail(f'credit rating write_safe: {title[:80]}')
        if BLOCK_RE.search(title) and not re.search(
            r'\b(recommends?|rated?\s+(?:buy|sell|hold)|upgrade(?:d|s)?\s+to\s+(?:buy|sell)|'
            r'downgrade(?:d|s)?\s+to\s+(?:buy|sell)|buy\s+call|sell\s+call|'
            r'(?:raises?|cuts?)\s+(?:the\s+)?(?:price\s+)?target)\b',
            combined,
            re.I,
        ):
            return _fail(f'block deal write_safe: {title[:80]}')
        if QUESTION_RE.search(title) and not re.search(
            r'\b(recommends?|rated?|maintains?)\b.{0,30}\b(buy|sell|hold)\b', combined, re.I
        ):
            return _fail(f'question headline write_safe: {title[:80]}')

    dup_write_safe = 0
    for row in write_safe:
        warnings = row.get('warnings') or []
        if 'duplicate_in_broker_predictions' in warnings:
            dup_write_safe += 1
    if dup_write_safe:
        return _fail(f'duplicates marked write_safe: {dup_write_safe}')

    has_top_pick_safe = any(TOP_PICK_RE.search(_title(r)) for r in write_safe if isinstance(r, dict))
    has_manual_safe = any(
        MANUAL_RE.search(str(r.get('source') or '')) or str((r.get('item') or {}).get('collector_source') or '') == 'manual'
        for r in write_safe
        if isinstance(r, dict)
    )

    summary = review.get('summary') or {}
    print(f'[BROKER_WRITE_GATE_AUDIT] write_safe={summary.get("write_safe", 0)}')
    print(f'[BROKER_WRITE_GATE_AUDIT] review_only={summary.get("review_only", 0)}')
    print(f'[BROKER_WRITE_GATE_AUDIT] rejected={summary.get("rejected", 0)}')
    print(f'[BROKER_WRITE_GATE_AUDIT] fake_predictions={fake_predictions}')
    print(f'[BROKER_WRITE_GATE_AUDIT] top_pick_in_write_safe={has_top_pick_safe}')
    print(f'[BROKER_WRITE_GATE_AUDIT] manual_in_write_safe={has_manual_safe}')
    print('BROKER_WRITE_GATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
