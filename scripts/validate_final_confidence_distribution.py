#!/usr/bin/env python3
"""
Validate final confidence report distribution in local research/closed mode.

Usage:
  python scripts/generate_final_confidence_report.py
  python scripts/validate_final_confidence_distribution.py

Prints exactly FINAL_CONFIDENCE_DISTRIBUTION_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_DISTRIBUTION_FAIL: {msg}', file=sys.stderr)
    return 1


def _critical_only_no_decision(row: dict) -> bool:
    hard = set(row.get('hard_warnings') or [])
    critical = {'missing_ticker', 'missing_prediction_id', 'insufficient_evidence', 'suspicious_price_scale'}
    return bool(hard) and hard.issubset(critical)


def main() -> int:
    if not REPORT_PATH.is_file():
        return _fail(f'missing report: {REPORT_PATH}')

    try:
        report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return _fail(f'invalid JSON: {exc}')

    if report.get('ok') is not True:
        return _fail('report ok != true')

    summary = report.get('summary') or {}
    checked = int(summary.get('checked') or 0)
    buy = int(summary.get('buy_candidate') or 0)
    watch = int(summary.get('watch') or 0)
    avoid = int(summary.get('avoid') or 0)
    no_decision = int(summary.get('no_decision') or 0)

    print(
        f'[FINAL_CONFIDENCE_DISTRIBUTION] checked={checked} buy={buy} '
        f'watch={watch} avoid={avoid} no_decision={no_decision}'
    )
    print(
        f"[FINAL_CONFIDENCE_DISTRIBUTION] mode={report.get('active_mode')} "
        f"market_closed={report.get('market_closed')} buy_cap_active={report.get('buy_cap_active')}"
    )

    if checked <= 0:
        return _fail('checked must be > 0')

    rows = report.get('rows') or []
    if no_decision == checked:
        if not rows or not all(_critical_only_no_decision(row) for row in rows):
            return _fail('all candidates are NO_DECISION without critical-only justification')

    active_mode = str(report.get('active_mode') or summary.get('active_mode') or '')
    buy_cap_active = bool(report.get('buy_cap_active') or summary.get('buy_cap_active'))
    if buy_cap_active and buy != 0:
        return _fail(f'buy_cap_active but buy_candidate={buy}')

    if active_mode == 'RESEARCH_MODE' and buy != 0:
        return _fail(f'RESEARCH_MODE requires buy=0, got {buy}')

    if watch + avoid <= 0:
        return _fail(f'expected watch+avoid > 0, got watch={watch} avoid={avoid}')

    print('FINAL_CONFIDENCE_DISTRIBUTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
