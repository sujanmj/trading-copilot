#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_telegram_live_photo_handler_routes_before_text.py')])
    if rc != 0:
        return rc
    print('TELEGRAM_LIVE_PHOTO_HANDLER_ROUTES_BEFORE_TEXT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
