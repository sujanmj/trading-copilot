#!/usr/bin/env python3
"""Validate /aihub journal rejected ticker removal (Stage 48U)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_aihub_journal_rejected_ticker_removed.py') != 0:
        return 1
    print('AIHUB_JOURNAL_REJECTED_TICKER_REMOVED_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
