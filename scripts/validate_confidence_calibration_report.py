#!/usr/bin/env python3
"""
Validate confidence_calibration_report.json structure.

Usage:
  python scripts/generate_confidence_calibration_report.py
  python scripts/validate_confidence_calibration_report.py

Prints exactly CONFIDENCE_CALIBRATION_VALIDATE_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'confidence_calibration_report.json'

REQUIRED_TOP = ('ok', 'generated_at', 'live', 'historical', 'combined', 'recommendations', 'warnings')
BUCKET_KEYS = (
    'bucket', 'candidates', 'resolved_live', 'resolved_historical',
    'wins', 'losses', 'win_rate', 'avg_score', 'expected_win_rate',
    'calibration_error', 'sample_warning', 'common_warnings',
)


def _fail(msg: str) -> int:
    print(f'CONFIDENCE_CALIBRATION_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _validate_bucket(bucket: dict, index: int) -> str | None:
    for key in BUCKET_KEYS:
        if key not in bucket:
            return f'bucket[{index}] missing key: {key}'
    if bucket.get('sample_warning') not in ('low_sample', 'ok'):
        return f'bucket[{index}] invalid sample_warning'
    if 'fake' in json.dumps(bucket).lower():
        return f'bucket[{index}] contains fake flag'
    resolved = int(bucket.get('wins') or 0) + int(bucket.get('losses') or 0)
    if resolved < 10 and bucket.get('sample_warning') != 'low_sample':
        return f'bucket[{index}] low sample must be marked low_sample'
    return None


def main() -> int:
    if not REPORT_PATH.is_file():
        return _fail(f'missing report: {REPORT_PATH}')

    try:
        report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return _fail(f'invalid JSON: {exc}')

    if report.get('ok') is not True:
        return _fail('report ok != true')
    if report.get('report_type') != 'confidence_calibration':
        return _fail('report_type must be confidence_calibration')
    if report.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')

    for key in REQUIRED_TOP:
        if key not in report:
            return _fail(f'missing top-level key: {key}')

    if 'fake' in json.dumps(report).lower() and report.get('fake_data') is True:
        return _fail('report must not use fake outcomes')

    for section_name in ('live', 'historical', 'combined'):
        section = report.get(section_name)
        if not isinstance(section, dict):
            return _fail(f'{section_name} must be object')
        buckets = section.get('buckets')
        if not isinstance(buckets, list):
            return _fail(f'{section_name}.buckets must be list')
        for index, bucket in enumerate(buckets):
            if not isinstance(bucket, dict):
                return _fail(f'{section_name}.buckets[{index}] must be object')
            err = _validate_bucket(bucket, index)
            if err:
                return _fail(f'{section_name}.{err}')

    recommendations = report.get('recommendations')
    if not isinstance(recommendations, list):
        return _fail('recommendations must be list')

    for index, rec in enumerate(recommendations):
        if not isinstance(rec, dict):
            return _fail(f'recommendations[{index}] must be object')
        rec_type = rec.get('type')
        if rec_type not in ('reduce_score', 'increase_score', 'warning_weight'):
            return _fail(f'recommendations[{index}] invalid type: {rec_type}')
        strength = rec.get('strength')
        if strength not in ('weak', 'medium', 'strong'):
            return _fail(f'recommendations[{index}] invalid strength: {strength}')
        sample = int(rec.get('sample_size') or 0)
        if sample < 10 and strength in ('medium', 'strong'):
            return _fail(f'recommendations[{index}] strong/medium on low sample')

    print('CONFIDENCE_CALIBRATION_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
