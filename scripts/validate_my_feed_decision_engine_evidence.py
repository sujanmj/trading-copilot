#!/usr/bin/env python3
"""Validate My Feed decision engine evidence (Stage 50A)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_my_feed_decision_engine_evidence.py') != 0:
        return 1
    print('MY_FEED_DECISION_ENGINE_EVIDENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
