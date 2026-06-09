#!/usr/bin/env python3
"""Unit tests — outcome price coverage report script (Stage 49C)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'OUTCOME_PRICE_COVERAGE_REPORT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    proc = subprocess.run(
        [sys.executable, 'scripts/outcome_price_coverage_report.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return _fail(proc.stderr[:300])
    out = proc.stdout
    if 'OUTCOME_PRICE_COVERAGE_REPORT_OK' not in out:
        return _fail('missing OUTCOME_PRICE_COVERAGE_REPORT_OK')
    for key in (
        'pending_total=',
        'has_reference_price=',
        'has_evaluation_price=',
        'resolvable_now=',
        'missing_reference=',
        'missing_evaluation=',
        'missing_both=',
        'top_missing_tickers=',
    ):
        if key not in out:
            return _fail(f'missing {key!r}')

    print('OUTCOME_PRICE_COVERAGE_REPORT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
