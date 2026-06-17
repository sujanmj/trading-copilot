#!/usr/bin/env python3
"""Validate Stage 50W verified My Feed catalyst integration test."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_verified_catalyst_integration.py')])
    if rc != 0:
        return rc
    print('MYFEED_VERIFIED_CATALYST_INTEGRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
