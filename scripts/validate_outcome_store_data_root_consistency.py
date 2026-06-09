#!/usr/bin/env python3
"""Validate outcome store data root consistency (Stage 49D)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_store_data_root_consistency.py') != 0:
        return 1
    print('OUTCOME_STORE_DATA_ROOT_CONSISTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
