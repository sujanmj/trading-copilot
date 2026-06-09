#!/usr/bin/env python3
"""Validate outcome_resolver_status.py script (Stage 49B)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_outcome_resolver_status_script.py') != 0:
        return 1
    if os.system(f'{sys.executable} scripts/validate_outcome_resolver_mock_closes.py') != 0:
        return 1
    if os.system(f'{sys.executable} scripts/validate_full_does_not_run_outcome_resolver.py') != 0:
        return 1
    print('OUTCOME_RESOLVER_STATUS_SCRIPT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
