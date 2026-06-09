#!/usr/bin/env python3
"""Validate /aihub calib reads canonical outcome store (Stage 49D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_calib_reads_canonical_outcomes.py') != 0:
        return 1
    print('AIHUB_CALIB_READS_CANONICAL_OUTCOMES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
