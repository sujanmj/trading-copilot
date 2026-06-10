#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_build_info_stage_matches_status.py')])
    if rc != 0:
        return rc
    print('BUILD_INFO_STAGE_MATCHES_STATUS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
