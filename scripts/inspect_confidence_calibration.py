#!/usr/bin/env python3
"""
Inspect confidence calibration buckets and recommendations.

Usage:
  python scripts/inspect_confidence_calibration.py
  python scripts/inspect_confidence_calibration.py --json
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


def _fmt_rate(value: object) -> str:
    if value is None:
        return 'N/A'
    try:
        return f'{float(value) * 100:.1f}%'
    except (TypeError, ValueError):
        return str(value)


def _print_buckets(title: str, buckets: list[dict]) -> None:
    print(f'\n[{title}] bucket table')
    if not buckets:
        print('  (empty)')
        return
    print('bucket | candidates | resolved | wins | losses | win_rate | avg_score | cal_error | sample')
    for bucket in buckets:
        resolved = int(bucket.get('resolved_live') or 0) + int(bucket.get('resolved_historical') or 0)
        if title.lower().startswith('live'):
            resolved = int(bucket.get('resolved_live') or 0)
        elif title.lower().startswith('historical'):
            resolved = int(bucket.get('resolved_historical') or 0)
        else:
            resolved = int(bucket.get('wins') or 0) + int(bucket.get('losses') or 0)
        print(
            f"{bucket.get('bucket')} | {bucket.get('candidates')} | {resolved} | "
            f"{bucket.get('wins')} | {bucket.get('losses')} | {_fmt_rate(bucket.get('win_rate'))} | "
            f"{bucket.get('avg_score')} | {bucket.get('calibration_error')} | {bucket.get('sample_warning')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect confidence calibration report.')
    parser.add_argument('--json', action='store_true', help='Print JSON output')
    args = parser.parse_args()

    from backend.analytics.confidence_calibration_engine import build_confidence_calibration_report

    report = build_confidence_calibration_report()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    live = report.get('live') or {}
    historical = report.get('historical') or {}
    combined = report.get('combined') or {}

    print(f"[CALIBRATION] live win_rate={_fmt_rate(live.get('win_rate'))} resolved={live.get('resolved', 0)}")
    print(
        f"[CALIBRATION] historical win_rate={_fmt_rate(historical.get('win_rate'))} "
        f"resolved={historical.get('resolved', 0)}"
    )
    print(
        f"[CALIBRATION] combined resolved={combined.get('resolved', 0)} "
        f"label={combined.get('label')}"
    )

    _print_buckets('LIVE', live.get('buckets') or [])
    _print_buckets('HISTORICAL', historical.get('buckets') or [])
    _print_buckets('COMBINED', combined.get('buckets') or [])

    print('\n[CALIBRATION] overconfident buckets')
    for bucket in combined.get('overconfident') or []:
        print(f"  {bucket.get('bucket')} error={bucket.get('calibration_error')}")

    print('\n[CALIBRATION] underconfident buckets')
    for bucket in combined.get('underconfident') or []:
        print(f"  {bucket.get('bucket')} error={bucket.get('calibration_error')}")

    print('\n[CALIBRATION] recommendations')
    for rec in report.get('recommendations') or []:
        print(
            f"  {rec.get('type')} {rec.get('bucket')} strength={rec.get('strength')} "
            f"sample={rec.get('sample_size')}"
        )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
