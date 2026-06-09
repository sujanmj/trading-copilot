#!/usr/bin/env python3
"""Validate compact stale report labels (Stage 48Q)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_report_stale_label_consistency.py') != 0:
        return 1
    print('REPORT_STALE_LABEL_CONSISTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
