#!/usr/bin/env python3
"""Validate after-close scheduler outcome resolver hook (Stage 49A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_resolver_after_close_scheduler.py') != 0:
        return 1
    print('OUTCOME_RESOLVER_AFTER_CLOSE_SCHEDULER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
