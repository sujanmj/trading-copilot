#!/usr/bin/env python3
"""Unit tests for stale AIHub cache labels (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_STALE_AIHUB_LABELS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import (
        _aihub_payload_is_stale,
        _global_item_display_label,
        _news_item_display_label,
        format_aihub_payload,
    )

    stale_payload = {
        'source': 'cache',
        'cache_age_seconds': 7200,
        'summary': {'stale': True},
        'items': [{'title': 'Bitcoin hits new high', 'headline': 'Bitcoin hits new high'}],
        'warnings': [],
    }
    if not _aihub_payload_is_stale(stale_payload):
        return _fail('stale payload not detected')

    news_text = format_aihub_payload('news', stale_payload)
    for needle in ('Research cache · stale', '/refresh full'):
        if needle not in news_text:
            return _fail(f'stale news missing {needle!r}')

    noise_label = _news_item_display_label({'title': 'SpaceX IPO filing announced'})
    if 'Global/Noise' not in noise_label:
        return _fail('SpaceX IPO should be Global/Noise')

    india_label = _global_item_display_label({'title': 'Nifty falls on RBI rate hike fears'})
    if 'Global/Noise' in india_label:
        return _fail('India-linked headline must not be Global/Noise')

    print('TELEGRAM_STALE_AIHUB_LABELS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
