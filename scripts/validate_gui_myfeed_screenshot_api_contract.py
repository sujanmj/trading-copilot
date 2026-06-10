#!/usr/bin/env python3
"""Validate GUI My Feed screenshot API contract (Stage 50B)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_gui_myfeed_screenshot_api_contract.py')])
    if rc != 0:
        return rc
    print('GUI_MYFEED_SCREENSHOT_API_CONTRACT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
