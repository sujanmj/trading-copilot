#!/usr/bin/env python3
"""Validate /aihub calib resolver-active zero-resolved wording (Stage 49B)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_calib_resolver_active_zero_resolved.py') != 0:
        return 1
    print('AIHUB_CALIB_RESOLVER_ACTIVE_ZERO_RESOLVED_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
