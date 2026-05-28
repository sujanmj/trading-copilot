#!/usr/bin/env python3
"""Validate prediction lifecycle partition from SQLite raw rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from backend.lifecycle.unified_metrics import _validate_sqlite_lifecycle
    from backend.storage.history_exporter import calculate_period_stats, get_predictions_in_range, get_days_back_range

    report = _validate_sqlite_lifecycle()
    print('[validate_prediction_lifecycle] SQLite partition')
    print(json.dumps({
        'valid': report.get('valid'),
        'total': report.get('total'),
        'partition_sum': report.get('partition_sum'),
        'counts': report.get('counts'),
        'issues': report.get('issues'),
    }, indent=2))

    start, end = get_days_back_range(15)
    preds = get_predictions_in_range(start, end)
    period_stats = calculate_period_stats(preds)
    print('[validate_prediction_lifecycle] 15d period stats (raw rows)')
    print(json.dumps({
        'total': period_stats.get('total'),
        'wins': period_stats.get('wins'),
        'losses': period_stats.get('losses'),
        'pending': period_stats.get('pending'),
        'expired': period_stats.get('expired'),
        'neutralized': period_stats.get('neutralized'),
        'lifecycle_valid': period_stats.get('lifecycle_valid', True),
        'issues': period_stats.get('lifecycle_issues'),
    }, indent=2))

    ok = bool(report.get('valid')) and period_stats.get('lifecycle_valid', True)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
