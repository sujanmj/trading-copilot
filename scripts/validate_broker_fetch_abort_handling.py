#!/usr/bin/env python3
"""Validate broker fetch abort handling (Stage 48E)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_fetch_abort_handling.py') != 0:
        print('BROKER_FETCH_ABORT_HANDLING_FAIL: test failed', file=sys.stderr)
        return 1
    print('BROKER_FETCH_ABORT_HANDLING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
