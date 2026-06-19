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
    if os.system(f'{sys.executable} scripts/test_tradecard_no_rolling_down_duplicate_entries.py') != 0:
        print('TRADECARD_NO_ROLLING_DOWN_DUPLICATE_ENTRIES_FAIL: test failed', file=sys.stderr)
        return 1
    print('TRADECARD_NO_ROLLING_DOWN_DUPLICATE_ENTRIES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
