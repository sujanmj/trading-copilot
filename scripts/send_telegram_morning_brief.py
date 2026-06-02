#!/usr/bin/env python3
"""Manual send: morning brief via Telegram Analysis Bot formatters."""

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
    from backend.telegram.telegram_brief_scheduler import build_morning_brief_text, send_brief

    text = build_morning_brief_text()
    ok = send_brief('morning')
    print('[SEND_MORNING_BRIEF] sent=' + ('yes' if ok else 'no'))
    if not ok:
        print(text[:500])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
