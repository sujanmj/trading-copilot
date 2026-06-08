#!/usr/bin/env python3
"""Validate GUI build text is not visible in app UI (Stage 48I)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_gui_no_build_text_leak.py') != 0:
        print('GUI_NO_BUILD_TEXT_LEAK_FAIL: test failed', file=sys.stderr)
        return 1
    print('GUI_NO_BUILD_TEXT_LEAK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
