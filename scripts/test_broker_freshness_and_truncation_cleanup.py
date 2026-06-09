#!/usr/bin/env python3
"""Unit tests — broker evidence freshness + headline truncation (Stage 48Q)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'BROKER_FRESHNESS_AND_TRUNCATION_CLEANUP_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import (
        _evidence_timestamp,
        _freshness_from_timestamp,
        _truncate_headline,
    )

    long_headline = (
        'Stocks to watch: Adani Enterprises, Bharti Airtel, RVNL, Vodafone Idea '
        'among key stocks in focus for the session ahead with sector rotation cues'
    )
    trimmed = _truncate_headline(long_headline, 110)
    if not trimmed.endswith('…'):
        return _fail('truncated headline must end with ellipsis')
    if len(trimmed) > 110:
        return _fail(f'truncated headline exceeds 110 chars: {len(trimmed)}')
    if trimmed.endswith(' i…') or trimmed.rstrip('…').endswith(' i'):
        return _fail('truncated headline must not end with ugly mid-word cut')

    short = _truncate_headline('Short headline', 110)
    if short != 'Short headline':
        return _fail('short headlines must pass through unchanged')

    ist = ZoneInfo('Asia/Kolkata')
    recent = datetime.now(ist) - timedelta(hours=3)
    row = {'extracted_at': recent.replace(microsecond=0).isoformat()}
    ts = _evidence_timestamp(row)
    if ts is None:
        return _fail('extracted_at must resolve evidence timestamp')
    if _freshness_from_timestamp(ts) != 'fresh':
        return _fail('recent extracted_at must not be unknown freshness')
    if _freshness_from_timestamp(_evidence_timestamp({})) != 'unknown':
        return _fail('missing timestamp must remain unknown')

    old = datetime.now(ist) - timedelta(days=10)
    old_row = {'extracted_at': old.replace(microsecond=0).isoformat()}
    if _freshness_from_timestamp(_evidence_timestamp(old_row)) != 'stale':
        return _fail('old extracted_at must classify as stale')

    print('BROKER_FRESHNESS_AND_TRUNCATION_CLEANUP_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
