#!/usr/bin/env python3
"""Unit tests for honest broker refresh messages (Stage 48M)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_REFRESH_HONEST_MESSAGE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import format_broker_refresh_telegram

    empty = format_broker_refresh_telegram({
        'ok': True,
        'cache_verify': {'ok': True, 'evidence_count': 0, 'ticker_count': 0},
        'evidence_items': [],
        'consensus_by_ticker': {},
    })
    if 'no fresh broker evidence found' not in empty.lower():
        return _fail('empty refresh must say no fresh broker evidence found')
    if 'started/completed' in empty.lower():
        return _fail('must not use vague started/completed wording')

    ok = format_broker_refresh_telegram({
        'ok': True,
        'cache_verify': {'ok': True, 'evidence_count': 3, 'ticker_count': 2},
        'evidence_items': [{}, {}, {}],
        'consensus_by_ticker': {'A': {}, 'B': {}},
    })
    if 'Broker refresh completed.' not in ok:
        return _fail('successful refresh must say completed with counts')
    if 'Evidence: 3' not in ok:
        return _fail('successful refresh must show evidence count')

    print('BROKER_REFRESH_HONEST_MESSAGE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
