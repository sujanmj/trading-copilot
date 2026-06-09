#!/usr/bin/env python3
"""Validate /memory resolved count rendering (Stage 49A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_memory_resolved_counts_render.py') != 0:
        return 1
    print('MEMORY_RESOLVED_COUNTS_RENDER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
