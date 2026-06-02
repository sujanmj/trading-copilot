#!/usr/bin/env python3
"""Manual send: market close summary via Telegram Analysis Bot formatters."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def main() -> int:
    from backend.telegram.telegram_brief_scheduler import send_brief

    ok = send_brief('close')
    print('[SEND_CLOSE_SUMMARY] sent=' + ('yes' if ok else 'no'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
