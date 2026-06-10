#!/usr/bin/env python3
"""Unit tests — My Feed OCR private lines filtered (Stage 50D)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_OCR_PRIVATE_LINES_FILTERED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.image_extraction import _build_result

    raw = '\n'.join([
        'Snapchat notification from Alex',
        'NIFTY futures rise on FII inflows today',
        'Send UPI payment now',
        'SEBI announces new margin rules for brokers today',
    ])
    result = _build_result(raw, confidence=0.85)
    if not result.get('ok'):
        return _fail(f'expected ok result got {result!r}')
    notifications = result.get('notifications') or []
    if len(notifications) < 2:
        return _fail(f'expected 2 market notifications, got {notifications!r}')
    if int(result.get('ignored_private_count') or 0) < 2:
        return _fail('expected private lines to increment ignored_private_count')
    blob = ' '.join(notifications).upper()
    for leak in ('SNAPCHAT', 'UPI', 'ALEX'):
        if leak in blob:
            return _fail(f'private line leaked: {blob!r}')

    print('MYFEED_OCR_PRIVATE_LINES_FILTERED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
