"""
Backward-compatible re-exports — all logic lives in unified_metrics.py.
"""

from backend.lifecycle.unified_metrics import (  # noqa: F401
    format_calibration_telegram,
    format_outcomes_telegram,
    format_stats_telegram,
    get_calibration_metrics,
    get_metrics_for_telegram,
    get_outcome_metrics,
    get_prediction_metrics,
    get_unified_snapshot,
)


def aggregate_outcomes(metric_type: str = 'all_time'):
    return get_outcome_metrics(metric_type)


def aggregate_calibration():
    return get_calibration_metrics()


def aggregate_stats():
    snap = get_unified_snapshot()
    return {
        'db_stats': snap.get('db_stats'),
        'metrics_all_time': snap.get('metrics_all_time'),
        'metrics_weekly': snap.get('metrics_weekly'),
        'metrics_daily': snap.get('metrics_daily'),
        'calibration_core': snap.get('calibration'),
    }


def get_live_stats_payload(refresh_export: bool = False):
    if refresh_export:
        from backend.storage.stats_exporter import export_stats
        return export_stats()
    return aggregate_stats()
