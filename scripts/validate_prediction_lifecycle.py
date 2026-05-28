#!/usr/bin/env python3
"""Validate prediction lifecycle partition from SQLite raw rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _partition_ok(stats: dict) -> bool:
    total = int(stats.get('total') or 0)
    partition = (
        int(stats.get('wins') or 0)
        + int(stats.get('losses') or 0)
        + int(stats.get('pending') or 0)
        + int(stats.get('expired') or 0)
        + int(stats.get('neutralized') or stats.get('neutral') or 0)
    )
    return partition == total


def main() -> int:
    from backend.lifecycle.prediction_reconciliation import (
        reconcile_prediction_stats,
        validate_prediction_totals,
    )
    from backend.lifecycle.unified_metrics import _validate_sqlite_lifecycle
    from backend.storage.history_exporter import (
        calculate_period_stats,
        get_days_back_range,
        get_predictions_in_range,
        get_this_week_range,
    )

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
    period_stats = calculate_period_stats(preds, source='validate_15d')
    print('[validate_prediction_lifecycle] 15d period stats (raw rows)')
    print(json.dumps({
        'total': period_stats.get('total'),
        'wins': period_stats.get('wins'),
        'losses': period_stats.get('losses'),
        'pending': period_stats.get('pending'),
        'expired': period_stats.get('expired'),
        'neutralized': period_stats.get('neutralized'),
        'partition_sum': (
            (period_stats.get('wins') or 0)
            + (period_stats.get('losses') or 0)
            + (period_stats.get('pending') or 0)
            + (period_stats.get('expired') or 0)
            + (period_stats.get('neutralized') or 0)
        ),
        'reconciliation_valid': period_stats.get('reconciliation_valid'),
        'lifecycle_valid': period_stats.get('lifecycle_valid', True),
        'issues': period_stats.get('lifecycle_issues'),
    }, indent=2))

    wstart, wend = get_this_week_range()
    week_preds = get_predictions_in_range(wstart, wend)
    week_stats = reconcile_prediction_stats(week_preds, source='validate_this_week')
    print('[validate_prediction_lifecycle] this_week reconciled stats')
    print(json.dumps({
        'total': week_stats.get('total'),
        'wins': week_stats.get('wins'),
        'losses': week_stats.get('losses'),
        'pending': week_stats.get('pending'),
        'expired': week_stats.get('expired'),
        'neutralized': week_stats.get('neutralized'),
        'partition_reconciles': _partition_ok(week_stats),
    }, indent=2))

    ok = (
        bool(report.get('valid'))
        and period_stats.get('lifecycle_valid', True)
        and period_stats.get('reconciliation_valid', True)
        and validate_prediction_totals(week_stats, source='validate_this_week')
        and _partition_ok(period_stats)
        and _partition_ok(week_stats)
    )
    print(f'[validate_prediction_lifecycle] overall_ok={ok}')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
