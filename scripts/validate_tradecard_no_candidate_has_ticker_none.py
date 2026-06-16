#!/usr/bin/env python3
"""Validate Stage 50Q tradecard no-candidate Ticker: NONE contract."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TRADECARD_NO_CANDIDATE_HAS_TICKER_NONE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'Ticker: NONE' not in src:
        return _fail('format_tradecard_telegram missing Ticker: NONE branch')
    proc = os.system(f'{sys.executable} scripts/test_tradecard_no_candidate_has_ticker_none.py')
    if proc != 0:
        return _fail('test_tradecard_no_candidate_has_ticker_none.py failed')
    print('TRADECARD_NO_CANDIDATE_HAS_TICKER_NONE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
