#!/usr/bin/env python3
"""Validate market mentions section (Stage 48O)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_market_mentions_section.py') != 0:
        return 1
    print('BROKER_MARKET_MENTIONS_SECTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
