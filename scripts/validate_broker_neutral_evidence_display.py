#!/usr/bin/env python3
"""Validate broker neutral evidence display (Stage 48N)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_neutral_evidence_display.py') != 0:
        return 1
    print('BROKER_NEUTRAL_EVIDENCE_DISPLAY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
