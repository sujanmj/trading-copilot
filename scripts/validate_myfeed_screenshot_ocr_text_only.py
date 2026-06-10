#!/usr/bin/env python3
"""Validate My Feed screenshot OCR text-only storage (Stage 50B)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_myfeed_screenshot_ocr_text_only.py')])
    if rc != 0:
        return rc
    print('MYFEED_SCREENSHOT_OCR_TEXT_ONLY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
