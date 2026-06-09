#!/usr/bin/env python3
"""Validate after-hours premarket labels (Stage 48S)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_after_hours_premarket_labels.py') != 0:
        return 1
    print('AFTER_HOURS_PREMARKET_LABELS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
