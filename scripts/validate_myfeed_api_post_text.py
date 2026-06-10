#!/usr/bin/env python3
"""Validate POST /api/myfeed stores text (Stage 50A hotfix)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_api_post_text.py')])
    if rc != 0:
        return rc
    print('MYFEED_API_POST_TEXT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
