#!/usr/bin/env python3
"""Validate Telegram AI provider masking (Stage 48M)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_telegram_ai_provider_masking.py') != 0:
        return 1
    print('TELEGRAM_AI_PROVIDER_MASKING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
