#!/usr/bin/env python3
"""
Validate final confidence report includes soft calibration integration.

Usage:
  python scripts/generate_final_confidence_report.py
  python scripts/validate_final_confidence_calibration_integration.py

Prints exactly FINAL_CONFIDENCE_CALIBRATION_INTEGRATION_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_CALIBRATION_INTEGRATION_FAIL: {msg}', file=sys.stderr)
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

    calibration = report.get('calibration')
    if not isinstance(calibration, dict):
        return _fail('report must include calibration object')

    for key in ('report_loaded', 'candidates_adjusted', 'candidates_weak_signal'):
        if key not in calibration:
            return _fail(f'calibration missing key: {key}')

    rows = report.get('rows') or []
    if not isinstance(rows, list):
        return _fail('rows must be a list')

    has_row_calibration_fields = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if 'calibration_adjustment' in row or 'calibration_applied' in row:
            has_row_calibration_fields = True
        adj = row.get('calibration_adjustment')
        if adj is not None and int(adj) != 0:
            pre = row.get('pre_calibration_score')
            final = row.get('final_score')
            if pre is not None and final is not None and int(final) - int(pre) != int(adj):
                return _fail(
                    f'calibration_adjustment mismatch for {row.get("prediction_id")}: '
                    f'pre={pre} final={final} adj={adj}'
                )
        if row.get('calibration_warning') == 'weak_calibration_signal':
            if int(row.get('calibration_adjustment') or 0) != 0:
                return _fail('weak_calibration_signal row must have calibration_adjustment=0')
            pre = row.get('pre_calibration_score')
            final = row.get('final_score')
            if pre is not None and final is not None and int(pre) != int(final):
                return _fail('weak calibration must not change final_score vs pre_calibration_score')

    if rows and not has_row_calibration_fields:
        return _fail('rows missing calibration_applied / calibration_adjustment fields')

    summary = report.get('summary') or {}
    if report.get('buy_cap_active') and summary.get('buy_candidate', 0) != 0:
        return _fail('buy_cap_active but buy_candidate > 0 in report')

    for row in rows:
        if report.get('buy_cap_active') and row.get('decision') == 'BUY_CANDIDATE':
            return _fail('BUY_CANDIDATE found while buy_cap_active')

    print('FINAL_CONFIDENCE_CALIBRATION_INTEGRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
