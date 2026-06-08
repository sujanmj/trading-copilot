#!/usr/bin/env python3
"""Validate budget catalyst list never shows Direction ? (Stage 48H)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_budget_catalyst_list_no_question_mark.py') != 0:
        print('BUDGET_CATALYST_LIST_NO_QUESTION_MARK_FAIL: test failed', file=sys.stderr)
        return 1
    print('BUDGET_CATALYST_LIST_NO_QUESTION_MARK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
