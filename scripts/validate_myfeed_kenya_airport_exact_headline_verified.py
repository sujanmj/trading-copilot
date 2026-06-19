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
    if os.system(f'{sys.executable} scripts/test_myfeed_kenya_airport_exact_headline_verified.py') != 0:
        print('MYFEED_KENYA_AIRPORT_EXACT_HEADLINE_VERIFIED_FAIL: test failed', file=sys.stderr)
        return 1
    print('MYFEED_KENYA_AIRPORT_EXACT_HEADLINE_VERIFIED_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
