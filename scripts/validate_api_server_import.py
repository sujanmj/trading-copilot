#!/usr/bin/env python3
"""Validate backend.api.api_server import (Stage 50A emergency)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_api_server_import.py')])
    if rc != 0:
        return rc
    print('API_SERVER_IMPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
