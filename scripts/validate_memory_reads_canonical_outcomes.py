#!/usr/bin/env python3
"""Validate /memory reads canonical outcome store (Stage 49D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_memory_reads_canonical_outcomes.py') != 0:
        return 1
    print('MEMORY_READS_CANONICAL_OUTCOMES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
