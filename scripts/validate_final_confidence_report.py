#!/usr/bin/env python3
"""
Validate final_confidence_report.json structure.

Usage:
  python scripts/generate_final_confidence_report.py
  python scripts/validate_final_confidence_report.py

Prints exactly FINAL_CONFIDENCE_REPORT_VALIDATE_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'

VALID_DECISIONS = frozenset({'BUY_CANDIDATE', 'WATCH', 'AVOID', 'NO_DECISION'})


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_REPORT_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not REPORT_PATH.is_file():
        return _fail(f'missing report: {REPORT_PATH}')

    try:
        report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return _fail(f'invalid JSON: {exc}')

    if report.get('ok') is not True:
        return _fail('report ok != true')
    if report.get('report_type') != 'final_confidence_fusion':
        return _fail('report_type must be final_confidence_fusion')
    if report.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')

    summary = report.get('summary')
    if not isinstance(summary, dict):
        return _fail('summary must be object')

    for key in ('checked', 'buy_candidate', 'watch', 'avoid', 'no_decision'):
        if key not in summary:
            return _fail(f'summary missing key: {key}')

    rows = report.get('rows')
    if not isinstance(rows, list):
        return _fail('rows must be a list')

    for row in rows:
        if not isinstance(row, dict):
            return _fail('row must be object')
        decision = str(row.get('decision') or '')
        if decision and decision not in VALID_DECISIONS:
            return _fail(f'invalid decision in row: {decision}')
        score = row.get('final_score')
        if score is not None and not (0 <= int(score) <= 100):
            return _fail(f'final_score out of range: {score}')

    top = report.get('top_candidates')
    if not isinstance(top, list):
        return _fail('top_candidates must be a list')

    print('FINAL_CONFIDENCE_REPORT_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
