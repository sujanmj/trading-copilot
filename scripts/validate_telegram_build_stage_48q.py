#!/usr/bin/env python3
"""Validate Telegram build label Stage 48R."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_telegram_build_stage_48q.py') != 0:
        return 1
    print('TELEGRAM_BUILD_STAGE_48Q_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
