#!/usr/bin/env python3
"""
Generate final confidence fusion report JSON.

Usage:
  python scripts/generate_final_confidence_report.py
  python scripts/generate_final_confidence_report.py --limit 30

Prints exactly FINAL_CONFIDENCE_REPORT_OK on success.
Writes data/final_confidence_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

OUTPUT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_REPORT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate final confidence report JSON.')
    parser.add_argument('--limit', type=int, default=50, help='Max candidates to score')
    parser.add_argument('--output', default=str(OUTPUT_PATH), help='Output JSON path')
    args = parser.parse_args()

    from backend.analytics.final_confidence_fusion import build_final_confidence_report

    report = build_final_confidence_report(limit=args.limit)
    if report.get('ok') is not True:
        return _fail(report.get('error') or 'build_final_confidence_report failed')

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')

    summary = report.get('summary') or {}
    print(f'[FINAL_CONFIDENCE_REPORT] wrote={output_path}')
    print(
        f"[FINAL_CONFIDENCE_REPORT] mode={report.get('active_mode')} "
        f"market_closed={report.get('market_closed')} buy_cap_active={report.get('buy_cap_active')}"
    )
    print(
        f"[FINAL_CONFIDENCE_REPORT] checked={summary.get('checked', 0)} "
        f"buy={summary.get('buy_candidate', 0)} watch={summary.get('watch', 0)} "
        f"avoid={summary.get('avoid', 0)} no_decision={summary.get('no_decision', 0)}"
    )
    calibration = report.get('calibration') or {}
    print(
        f"[FINAL_CONFIDENCE_REPORT] calibration report_loaded={calibration.get('report_loaded')} "
        f"adjusted={calibration.get('candidates_adjusted', 0)} "
        f"weak_signal={calibration.get('candidates_weak_signal', 0)}"
    )
    simulation = report.get('simulation') or {}
    print(
        f"[FINAL_CONFIDENCE_REPORT] simulation_applied="
        f"{simulation.get('simulation_applied', 0)}"
    )
    print(
        f"[FINAL_CONFIDENCE_REPORT] simulation_positive="
        f"{simulation.get('simulation_positive', 0)}"
    )
    print(
        f"[FINAL_CONFIDENCE_REPORT] simulation_negative="
        f"{simulation.get('simulation_negative', 0)}"
    )
    print(
        f"[FINAL_CONFIDENCE_REPORT] simulation_neutral="
        f"{simulation.get('simulation_neutral', 0)}"
    )
    if report.get('buy_cap_active') and summary.get('buy_candidate', 0) != 0:
        return _fail('buy_cap_active but buy_candidate > 0')
    if summary.get('checked', 0) > 0 and summary.get('no_decision', 0) == summary.get('checked', 0):
        return _fail('all candidates are NO_DECISION')
    print('FINAL_CONFIDENCE_REPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
