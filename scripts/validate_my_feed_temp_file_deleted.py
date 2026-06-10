#!/usr/bin/env python3
"""Validate My Feed OCR temp file cleanup (Stage 50A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_my_feed_temp_file_deleted.py') != 0:
        return 1
    print('MY_FEED_TEMP_FILE_DELETED_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
