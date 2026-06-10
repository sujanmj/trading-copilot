#!/usr/bin/env python3
"""Unit tests — My Feed privacy filter (Stage 50A)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MY_FEED_PRIVACY_FILTER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.text_extractor import _is_private_line, filter_market_text

    if not _is_private_line('Check my Instagram story'):
        return _fail('Instagram line must be private')
    if not _is_private_line('Send UPI payment now'):
        return _fail('payment line must be private')

    raw = '\n'.join([
        'Instagram reel from friend',
        'NIFTY futures rise on FII inflows today',
        'WhatsApp chat with Rahul about dinner',
        'SEBI announces new margin rules for brokers today',
    ])
    extracted = filter_market_text(raw)
    if extracted.get('ignored_private_items', 0) < 2:
        return _fail('expected ignored private/non-market lines')
    cleaned = str(extracted.get('cleaned_summary') or '').upper()
    if 'NIFTY' not in cleaned or 'SEBI' not in cleaned:
        return _fail(f'market lines missing from cleaned={cleaned!r}')
    if 'INSTAGRAM' in cleaned or 'WHATSAPP' in cleaned:
        return _fail('private content leaked into cleaned summary')

    print('MY_FEED_PRIVACY_FILTER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
