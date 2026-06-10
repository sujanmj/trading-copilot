#!/usr/bin/env python3
"""Unit tests — My Feed private notification filter (Stage 50B)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_PRIVATE_NOTIFICATION_FILTER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.text_extractor import _is_private_line, filter_market_text

    private_lines = (
        'Check my Instagram story',
        'New Snapchat streak from friend',
        'WhatsApp message from Rahul about dinner',
        'Send UPI payment now',
        'Battery 42% · 10:32 am',
    )
    for line in private_lines:
        if not _is_private_line(line):
            return _fail(f'private line not filtered: {line!r}')

    raw = '\n'.join([
        'Instagram reel from friend',
        'Snapchat notification from Alex',
        'NIFTY futures rise on FII inflows today',
        'WhatsApp chat with Rahul about dinner',
        'SEBI announces new margin rules for brokers today',
        'Bank Nifty gains on strong banking sector rally',
    ])
    extracted = filter_market_text(raw)
    if extracted.get('ignored_private_items', 0) < 3:
        return _fail('expected private/social lines to be ignored')
    cleaned = str(extracted.get('cleaned_summary') or '').upper()
    for market_token in ('NIFTY', 'SEBI', 'BANK'):
        if market_token not in cleaned:
            return _fail(f'market line missing from cleaned summary: {cleaned!r}')
    for leak in ('INSTAGRAM', 'SNAPCHAT', 'WHATSAPP', 'UPI'):
        if leak in cleaned:
            return _fail(f'private content leaked into cleaned summary: {leak!r}')

    print('MYFEED_PRIVATE_NOTIFICATION_FILTER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
