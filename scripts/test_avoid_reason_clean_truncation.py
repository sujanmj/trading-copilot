#!/usr/bin/env python3
"""Stage 50L — avoid reason clean truncation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'AVOID_REASON_CLEAN_TRUNCATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import clean_avoid_reason_text

    long_text = (
        'Gap up on weak participation with sector divergence and no volume confirmation '
        'for sustained follow-through into the close session INFRA_'
    )
    cleaned = clean_avoid_reason_text(long_text, max_len=180)
    if cleaned.endswith('INFRA_') or cleaned.endswith('0'):
        return _fail(f'broken suffix remains: {cleaned!r}')
    if len(cleaned) > 181:
        return _fail(f'too long: {len(cleaned)}')
    if not cleaned.endswith('…') and len(long_text) > 180:
        return _fail('long text should end with ellipsis')

    partial = 'Bearish breakdown on low liquidity 0'
    out = clean_avoid_reason_text(partial)
    if out.endswith(' 0'):
        return _fail(f'trailing zero not trimmed: {out!r}')

    print('AVOID_REASON_CLEAN_TRUNCATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
