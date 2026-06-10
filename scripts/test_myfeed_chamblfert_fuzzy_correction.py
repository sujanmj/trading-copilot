#!/usr/bin/env python3
"""Stage 50F — fuzzy ticker correction for known NSE symbols."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_CHAMBLFERT_FUZZY_CORRECTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.text_extractor import correct_fuzzy_tickers, extract_tickers

    corrected = correct_fuzzy_tickers(['CHAMBLERT'], 'CHAMBLERT surges 5.3%')
    if 'CHAMBLFERT' not in corrected:
        return _fail(f'CHAMBLERT must map to CHAMBLFERT, got {corrected!r}')

    invented = correct_fuzzy_tickers(['ZZZZUNKNOWN'], 'ZZZZUNKNOWN random word')
    if invented:
        return _fail('unknown token must not invent ticker outside known universe')

    tickers = extract_tickers('CHAMBLERT surges 5.3% on strong volume')
    if 'CHAMBLFERT' not in tickers:
        return _fail(f'extract_tickers must fuzzy-correct CHAMBLERT, got {tickers!r}')

    print('MYFEED_CHAMBLFERT_FUZZY_CORRECTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
