#!/usr/bin/env python3
"""Validate honest broker refresh messages (Stage 48M)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_refresh_honest_message.py') != 0:
        return 1
    print('BROKER_REFRESH_HONEST_MESSAGE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
