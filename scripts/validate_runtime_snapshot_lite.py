#!/usr/bin/env python3
"""Validate runtime snapshot lite pack (Stage 48C)."""

from __future__ import annotations

import os
import sys


def _fail(msg: str) -> int:
    print(f'RUNTIME_SNAPSHOT_LITE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_runtime_snapshot_lite.py') != 0:
        return _fail('test_runtime_snapshot_lite.py failed')
    print('RUNTIME_SNAPSHOT_LITE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
