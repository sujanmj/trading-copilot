#!/usr/bin/env python3
"""Validate after-hours scanner wording (Stage 48T)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_after_hours_scanner_wording.py') != 0:
        return 1
    print('AFTER_HOURS_SCANNER_WORDING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
