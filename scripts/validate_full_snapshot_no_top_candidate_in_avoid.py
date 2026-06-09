#!/usr/bin/env python3
"""Validate guarded top_pick not in avoid list (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_full_snapshot_no_top_candidate_in_avoid.py') != 0:
        return 1
    print('FULL_SNAPSHOT_NO_TOP_CANDIDATE_IN_AVOID_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
