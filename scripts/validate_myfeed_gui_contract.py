#!/usr/bin/env python3
"""Validate GUI My Feed contract (Stage 50A hotfix)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_gui_contract.py')])
    if rc != 0:
        return rc
    print('MYFEED_GUI_CONTRACT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
