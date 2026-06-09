#!/usr/bin/env python3
"""Validate today/morning/action_plan same live candidate (Stage 48R)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_today_morning_action_same_live_candidate.py') != 0:
        return 1
    print('TODAY_MORNING_ACTION_SAME_LIVE_CANDIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
