#!/usr/bin/env python3
"""Validate live avoid registry rejects stale AVANTIFEED (Stage 48Q)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_live_avoid_rejects_stale_candidate.py') != 0:
        return 1
    print('LIVE_AVOID_REJECTS_STALE_CANDIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
