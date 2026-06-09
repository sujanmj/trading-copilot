#!/usr/bin/env python3
"""Validate outcome resolver status line rendering (Stage 49B)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_resolver_status_render.py') != 0:
        return 1
    print('OUTCOME_RESOLVER_STATUS_RENDER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
