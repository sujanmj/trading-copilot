#!/usr/bin/env python3
"""Validate /full does not run outcome resolver (Stage 49A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_full_does_not_run_outcome_resolver.py') != 0:
        return 1
    print('FULL_DOES_NOT_RUN_OUTCOME_RESOLVER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
