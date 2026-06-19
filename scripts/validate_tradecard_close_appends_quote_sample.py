#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_tradecard_close_appends_quote_sample.py') != 0:
        print('TRADECARD_CLOSE_APPENDS_QUOTE_SAMPLE_FAIL: test failed', file=sys.stderr)
        return 1
    print('TRADECARD_CLOSE_APPENDS_QUOTE_SAMPLE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
