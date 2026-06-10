#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_reprocess_invalidates_aihub_cache.py')])
    if rc != 0:
        return rc
    print('MYFEED_REPROCESS_INVALIDATES_AIHUB_CACHE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
