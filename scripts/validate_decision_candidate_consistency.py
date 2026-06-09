#!/usr/bin/env python3
"""Validate unified decision live-guard consistency (Stage 48Q)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_decision_candidate_consistency.py') != 0:
        return 1
    print('DECISION_CANDIDATE_CONSISTENCY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
