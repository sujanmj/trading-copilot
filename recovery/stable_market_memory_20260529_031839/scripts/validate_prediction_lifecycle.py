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
        buildTimelineStats,
        validate_prediction_totals,
    )
    from backend.lifecycle.unified_metrics import _validate_sqlite_lifecycle
    from backend.storage.history_exporter import (
        get_days_back_range,
        get_predictions_in_range,
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

    start_all, end_all = get_days_back_range(90)
    canonical = get_predictions_in_range(start_all, end_all)

    period_stats = buildTimelineStats(canonical, '15d', source='validate_15d')
    print('[validate_prediction_lifecycle] 15d buildTimelineStats')
    print(json.dumps({
        'total': period_stats.get('total'),
        'wins': period_stats.get('wins'),
        'losses': period_stats.get('losses'),
        'pending': period_stats.get('pending'),
        'expired': period_stats.get('expired'),
        'neutralized': period_stats.get('neutralized'),
        'partition_reconciles': _partition_ok(period_stats),
        'reconciliation_valid': period_stats.get('reconciliation_valid'),
    }, indent=2))

    y_stats = buildTimelineStats(canonical, 'yesterday', source='validate_yesterday')
    print('[validate_prediction_lifecycle] yesterday buildTimelineStats')
    print(json.dumps({
        'total': y_stats.get('total'),
        'wins': y_stats.get('wins'),
        'losses': y_stats.get('losses'),
        'pending': y_stats.get('pending'),
        'expired': y_stats.get('expired'),
        'neutralized': y_stats.get('neutralized'),
        'partition_reconciles': _partition_ok(y_stats),
    }, indent=2))

    lw_stats = buildTimelineStats(canonical, 'last_week', source='validate_last_week')
    print('[validate_prediction_lifecycle] last_week buildTimelineStats')
    print(json.dumps({
        'total': lw_stats.get('total'),
        'wins': lw_stats.get('wins'),
        'losses': lw_stats.get('losses'),
        'pending': lw_stats.get('pending'),
        'expired': lw_stats.get('expired'),
        'neutralized': lw_stats.get('neutralized'),
        'partition_reconciles': _partition_ok(lw_stats),
    }, indent=2))

    week_stats = buildTimelineStats(canonical, 'this_week', source='validate_this_week')
    print('[validate_prediction_lifecycle] this_week buildTimelineStats')
    print(json.dumps({
        'total': week_stats.get('total'),
        'wins': week_stats.get('wins'),
        'losses': week_stats.get('losses'),
        'pending': week_stats.get('pending'),
        'expired': week_stats.get('expired'),
        'neutralized': week_stats.get('neutralized'),
        'partition_reconciles': _partition_ok(week_stats),
    }, indent=2))

    lw_has_terminal = (lw_stats.get('total') or 0) == 0 or (
        (lw_stats.get('expired') or 0) + (lw_stats.get('neutralized') or 0) > 0
        or (lw_stats.get('wins') or 0) + (lw_stats.get('losses') or 0) > 0
    )

    ok = (
        bool(report.get('valid'))
        and period_stats.get('reconciliation_valid', True)
        and validate_prediction_totals(week_stats, source='validate_this_week')
        and validate_prediction_totals(lw_stats, source='validate_last_week')
        and validate_prediction_totals(y_stats, source='validate_yesterday')
        and _partition_ok(period_stats)
        and _partition_ok(week_stats)
        and _partition_ok(lw_stats)
        and _partition_ok(y_stats)
        and lw_has_terminal
    )
    print(f'[validate_prediction_lifecycle] overall_ok={ok}')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
