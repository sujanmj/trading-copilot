#!/usr/bin/env python3
"""Validate consensus only from true ratings (Stage 48O)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_consensus_only_true_ratings.py') != 0:
        return 1
    print('BROKER_CONSENSUS_ONLY_TRUE_RATINGS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
