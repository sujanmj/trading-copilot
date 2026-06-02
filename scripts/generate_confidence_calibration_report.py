#!/usr/bin/env python3
"""
Generate confidence calibration report JSON.

Usage:
  python scripts/generate_confidence_calibration_report.py

Prints exactly CONFIDENCE_CALIBRATION_REPORT_OK on success.
Writes data/confidence_calibration_report.json
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

OUTPUT_PATH = PROJECT_ROOT / 'data' / 'confidence_calibration_report.json'


def _fail(msg: str) -> int:
    print(f'CONFIDENCE_CALIBRATION_REPORT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate confidence calibration report JSON.')
    parser.add_argument('--output', default=str(OUTPUT_PATH), help='Output JSON path')
    args = parser.parse_args()

    from backend.analytics.confidence_calibration_engine import build_confidence_calibration_report

    report = build_confidence_calibration_report()
    if report.get('ok') is not True:
        return _fail(report.get('error') or 'build_confidence_calibration_report failed')

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')

    live = report.get('live') or {}
    historical = report.get('historical') or {}
    combined = report.get('combined') or {}
    recommendations = report.get('recommendations') or []

    print(f'[CALIBRATION] live_resolved={live.get("resolved", 0)}')
    print(f'[CALIBRATION] historical_resolved={historical.get("resolved", 0)}')
    print(f'[CALIBRATION] buckets={len(combined.get("buckets") or [])}')
    print(f'[CALIBRATION] overconfident={len(combined.get("overconfident") or [])}')
    print(f'[CALIBRATION] underconfident={len(combined.get("underconfident") or [])}')
    print(f'[CALIBRATION] recommendations={len(recommendations)}')
    print(f'[CALIBRATION] output={output_path}')
    print('CONFIDENCE_CALIBRATION_REPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
