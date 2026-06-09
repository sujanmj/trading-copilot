#!/usr/bin/env python3
"""Validate stale wording cleanup (Stage 48T)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_remove_stale_no_old_cache_wording.py') != 0:
        return 1
    print('REMOVE_STALE_NO_OLD_CACHE_WORDING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
