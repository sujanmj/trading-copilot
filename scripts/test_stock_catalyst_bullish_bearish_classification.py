#!/usr/bin/env python3
"""Stage 50N — catalyst side/type classification."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'STOCK_CATALYST_BULLISH_BEARISH_CLASSIFICATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import classify_catalyst, score_catalyst_row

    cases = [
        ('Arvind SmartSpaces announces new housing project', 'PROJECT_ANNOUNCEMENT', 'BULLISH'),
        ('GMR Airports traffic surges after broker upgrade', 'BROKER_UPGRADE', 'BULLISH'),
        ('HCL Technologies acquires stake in Sarvam AI', 'ACQUISITION', 'BULLISH'),
        ('GICRE OFS stake sale by government', 'OFS', 'BEARISH'),
        ('PTCIL shares plunge 8% with no fresh order news', 'GENERAL_NEWS', 'RISK'),
    ]
    for text, exp_type, exp_side in cases:
        ctype, side = classify_catalyst(text)
        if ctype != exp_type:
            return _fail(f'{text!r} type expected {exp_type} got {ctype}')
        if side != exp_side:
            return _fail(f'{text!r} side expected {exp_side} got {side}')

    block = score_catalyst_row({
        'ticker': 'SUZLON',
        'catalyst_type': 'BLOCK_DEAL',
        'side': 'MIXED',
        'change_pct': 4.2,
        'volume_ratio': 1.6,
        'source_key': 'news_feed',
        'published_at': '2026-06-16T09:00:00+05:30',
    })
    if block.get('side') not in ('MIXED', 'BULLISH'):
        return _fail(f'SUZLON block should stay mixed/bullish with price confirm got {block.get("side")}')

    print('STOCK_CATALYST_BULLISH_BEARISH_CLASSIFICATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
