#!/usr/bin/env python3
"""Unit tests — My Feed OCR multi-notification split (Stage 50D)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_OCR_MULTI_NOTIFICATION_SPLIT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.text_extractor import split_market_notifications

    raw = '\n'.join([
        'Inshorts: Iran attacks US bases in Kuwait, Jordan, Bahrain',
        'Instagram reel from friend',
        'Moneycontrol: CHAMBLFERT surges 5.3% on strong Q4 results today',
        'WhatsApp message from Rahul about dinner',
    ])
    split = split_market_notifications(raw)
    notifications = split.get('notifications') or []
    if len(notifications) < 2:
        return _fail(f'expected at least 2 market notifications, got {notifications!r}')
    joined = ' '.join(notifications).upper()
    if 'IRAN' not in joined or 'CHAMBLFERT' not in joined:
        return _fail(f'market notifications missing expected tokens: {notifications!r}')
    for leak in ('INSTAGRAM', 'WHATSAPP', 'RAHUL'):
        if leak in joined:
            return _fail(f'private content leaked into notifications: {joined!r}')
    if int(split.get('ignored_private_count') or 0) < 1:
        return _fail('expected ignored_private_count for social lines')

    print('MYFEED_OCR_MULTI_NOTIFICATION_SPLIT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
