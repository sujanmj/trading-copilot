#!/usr/bin/env python3
"""Validate /full unified snapshot avoid consistency (Stage 48Q)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_full_snapshot_no_conflicting_today_candidate.py') != 0:
        return 1
    print('FULL_SNAPSHOT_NO_CONFLICTING_TODAY_CANDIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
