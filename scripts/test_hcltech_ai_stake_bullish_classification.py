#!/usr/bin/env python3
"""Stage 50O — HCLTECH Sarvam AI stake classified bullish."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HEADLINE = 'HCL Tech shares jump 3% after buying stake in Sarvam AI for Rs 1,427 crore'


def _fail(msg: str) -> int:
    print(f'HCLTECH_AI_STAKE_BULLISH_CLASSIFICATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import classify_catalyst, resolve_tickers_from_text

    ctype, side = classify_catalyst(HEADLINE)
    if side != 'BULLISH':
        return _fail(f'expected BULLISH got {side}')
    if ctype not in ('AI_INVESTMENT', 'ACQUISITION', 'STAKE_BUY'):
        return _fail(f'expected acquisition/AI catalyst got {ctype}')
    tickers = resolve_tickers_from_text(HEADLINE)
    if 'HCLTECH' not in tickers:
        return _fail(f'expected HCLTECH in tickers got {tickers}')

    print('HCLTECH_AI_STAKE_BULLISH_CLASSIFICATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
