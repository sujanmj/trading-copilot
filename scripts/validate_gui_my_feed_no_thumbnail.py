#!/usr/bin/env python3
"""Validate standalone My Feed workspace has no thumbnails (Stage 50H)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_gui_my_feed_no_thumbnail.py') != 0:
        return 1
    print('GUI_MY_FEED_NO_THUMBNAIL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
