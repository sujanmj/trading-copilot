#!/usr/bin/env python3
"""Manual send: overnight/global brief via Telegram Analysis Bot formatters."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

from backend.config.local_safe_mode import apply_local_safe_mode_defaults

apply_local_safe_mode_defaults()


def main() -> int:
    from backend.telegram.telegram_brief_scheduler import send_brief

    ok = send_brief('overnight')
    print('[SEND_OVERNIGHT_BRIEF] sent=' + ('yes' if ok else 'no'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
