"""
Canonical prediction lifecycle reconciliation — single state per prediction record.

Partition states: ACTIVE, WIN, LOSS, EXPIRED, NEUTRALIZED.
All export/GUI period totals must use reconcile_prediction_stats() on raw SQLite rows only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytz

_IST = pytz.timezone('Asia/Kolkata')

TIMELINE_WINDOWS = frozenset({
    'today', 'yesterday', 'this_week', 'last_week', '15d', 'custom',
})

# Canonical partition states (exactly one per prediction id)
ACTIVE = 'ACTIVE'
WIN = 'WIN'
LOSS = 'LOSS'
EXPIRED = 'EXPIRED'
NEUTRALIZED = 'NEUTRALIZED'

# Legacy alias kept for imports; maps to NEUTRALIZED at normalization time
CANCELLED = 'CANCELLED'

PARTITION_STATES = frozenset({ACTIVE, WIN, LOSS, EXPIRED, NEUTRALIZED})
CANONICAL_STATES = PARTITION_STATES
TERMINAL_STATES = frozenset({WIN, LOSS, EXPIRED, NEUTRALIZED})

_VERDICT_TO_CANONICAL = {
    'ACTIVE': ACTIVE,
    'PENDING': ACTIVE,
    'UNRESOLVED': ACTIVE,
    'PARTIAL': ACTIVE,
    'WIN': WIN,
    'LOSS': LOSS,
    'EXPIRED': EXPIRED,
    'ARCHIVED': EXPIRED,
    'STALE': EXPIRED,
    'TIMEOUT': EXPIRED,
    'INVALIDATED': NEUTRALIZED,
    'INVALID': NEUTRALIZED,
    'NEUTRAL': NEUTRALIZED,
    'NEUTRALIZED': NEUTRALIZED,
    'UNKNOWN': NEUTRALIZED,
    'CANCELLED': NEUTRALIZED,
}

# Raw SQLite/JSON verdict strings that require one-time or startup normalization
LEGACY_STORAGE_VERDICTS = frozenset({
    'PENDING', 'UNRESOLVED', 'PARTIAL', 'STALE', 'ARCHIVED', 'TIMEOUT',
    'UNKNOWN', 'INVALIDATED', 'INVALID', 'CANCELLED',
})

_CANONICAL_TO_STORAGE = {
    WIN: 'WIN',
    LOSS: 'LOSS',
    ACTIVE: 'ACTIVE',
    EXPIRED: 'EXPIRED',
    NEUTRALIZED: 'NEUTRAL',
}


def normalize_canonical_state(
    verdict: Optional[str],
    *,
    state: Optional[str] = None,
) -> str:
    """Map raw verdict/state to exactly one canonical lifecycle bucket."""
    raw = (verdict or state or '').strip().upper()
    if not raw:
        return NEUTRALIZED
    return _VERDICT_TO_CANONICAL.get(raw, NEUTRALIZED)


def canonical_to_storage_verdict(canonical: str) -> str:
    """Map canonical partition state to outcomes.verdict column value."""
    return _CANONICAL_TO_STORAGE.get(canonical, 'NEUTRAL')


def is_legacy_storage_verdict(verdict: Optional[str]) -> bool:
    if verdict is None:
        return True
    return str(verdict).strip().upper() in LEGACY_STORAGE_VERDICTS


def log_lifecycle_transition(
    prediction_id: Any,
    old_state: str,
    new_state: str,
    resolution_reason: str = '',
) -> None:
    reason = f' resolution_reason={resolution_reason}' if resolution_reason else ''
    print(
        f'[Lifecycle] prediction_id={prediction_id} old_state={old_state} new_state={new_state}{reason}',
        flush=True,
    )


def dedupe_prediction_records(records: Iterable[dict]) -> List[dict]:
    """Keep one row per prediction id — prevents live/archive double counting."""
    seen: Dict[Any, dict] = {}
    order: List[Any] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        pid = rec.get('id')
        if pid is None:
            order.append(id(rec))
            seen[id(rec)] = rec
            continue
        if pid not in seen:
            order.append(pid)
        seen[pid] = rec
    return [seen[k] for k in order]


def validate_prediction_totals(stats: Dict[str, Any], *, source: str = '') -> bool:
    """Ensure total = wins + losses + pending + expired + neutralized."""
    total = int(stats.get('total') or 0)
    wins = int(stats.get('wins') or 0)
    losses = int(stats.get('losses') or 0)
    pending = int(stats.get('pending') or stats.get('active') or 0)
    expired = int(stats.get('expired') or 0)
    neutralized = int(stats.get('neutralized') or stats.get('neutral') or 0)
    partition = wins + losses + pending + expired + neutralized
    if partition != total:
        src = f' source={source}' if source else ''
        print(
            f'[RECONCILIATION_ERROR]{src} total={total} '
            f'wins={wins} losses={losses} pending={pending} '
            f'expired={expired} neutralized={neutralized} partition={partition}',
            flush=True,
        )
        stats['reconciliation_valid'] = False
        stats['reconciliation_partition'] = partition
        return False
    stats['reconciliation_valid'] = True
    stats['reconciliation_partition'] = partition
    return True


def reconcile_prediction_stats(
    records: Iterable[dict],
    *,
    source: str = '',
) -> Dict[str, Any]:
    """Recompute period totals from raw prediction rows only."""
    unique = dedupe_prediction_records(records)
    counts = {s: 0 for s in PARTITION_STATES}
    for rec in unique:
        canon = normalize_canonical_state(rec.get('verdict'), state=rec.get('state'))
        counts[canon] = counts.get(canon, 0) + 1

    wins = counts[WIN]
    losses = counts[LOSS]
    pending = counts[ACTIVE]
    expired = counts[EXPIRED]
    neutralized = counts[NEUTRALIZED]
    total = wins + losses + pending + expired + neutralized
    resolved = wins + losses

    from backend.lifecycle.win_rate_engine import compute_win_rate

    stats = {
        'total': total,
        'wins': wins,
        'losses': losses,
        'neutral': neutralized,
        'pending': pending,
        'active': pending,
        'expired': expired,
        'neutralized': neutralized,
        'resolved': resolved,
        'evaluated': resolved + expired + neutralized,
        'win_rate': compute_win_rate(wins, losses),
        'canonical_counts': counts,
        'partition_sum': total,
    }
    validate_prediction_totals(stats, source=source)
    return stats


def aggregate_period_stats(records: Iterable[dict]) -> Dict[str, Any]:
    """Backward-compatible alias for reconcile_prediction_stats."""
    return reconcile_prediction_stats(records)


def _ist_today() -> date:
    return datetime.now(_IST).date()


def _parse_prediction_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return None


def timeframe_date_range(
    timeframe: str,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Tuple[date, date]:
    """IST calendar bounds for a timeline window (shared by all exports)."""
    if timeframe == 'custom':
        if start_date is None or end_date is None:
            raise ValueError('custom timeframe requires start_date and end_date')
        if start_date > end_date:
            raise ValueError('start_date must be <= end_date')
        return start_date, end_date

    today = _ist_today()
    if timeframe == 'today':
        return today, today
    if timeframe == 'yesterday':
        y = today - timedelta(days=1)
        return y, y
    if timeframe == '15d':
        return today - timedelta(days=15), today

    weekday = today.weekday()
    if weekday == 6:
        this_sunday = today
    else:
        this_sunday = today - timedelta(days=weekday + 1)

    if timeframe == 'this_week':
        if weekday == 6:
            return today, today
        return this_sunday, today
    if timeframe == 'last_week':
        last_sunday = this_sunday - timedelta(days=7)
        last_friday = last_sunday + timedelta(days=5)
        return last_sunday, last_friday

    raise ValueError(f'unknown timeline timeframe: {timeframe}')


def filter_predictions_for_timeframe(
    predictions: Iterable[dict],
    timeframe: str,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[dict]:
    """Keep canonical prediction rows whose prediction_date falls in the window."""
    start, end = timeframe_date_range(timeframe, start_date=start_date, end_date=end_date)
    filtered: List[dict] = []
    for rec in predictions:
        if not isinstance(rec, dict):
            continue
        pred_date = _parse_prediction_date(rec.get('prediction_date'))
        if pred_date is None:
            continue
        if start <= pred_date <= end:
            filtered.append(rec)
    return filtered


def log_timeline_rebuild(timeframe: str, stats: Dict[str, Any]) -> None:
    print(
        f'[TIMELINE_REBUILD] window={timeframe} '
        f'total={int(stats.get("total") or 0)} '
        f'wins={int(stats.get("wins") or 0)} '
        f'losses={int(stats.get("losses") or 0)} '
        f'pending={int(stats.get("pending") or stats.get("active") or 0)} '
        f'expired={int(stats.get("expired") or 0)} '
        f'neutralized={int(stats.get("neutralized") or stats.get("neutral") or 0)}',
        flush=True,
    )


def buildTimelineStats(
    predictions: Iterable[dict],
    timeframe: str,
    *,
    source: str = '',
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Single timeline aggregation entry — filter window, then reconcile canonical states.
    All GUI history periods (today … custom) must use this function only.
    """
    if timeframe not in TIMELINE_WINDOWS:
        raise ValueError(f'unsupported timeline timeframe: {timeframe}')
    filtered = filter_predictions_for_timeframe(
        predictions, timeframe, start_date=start_date, end_date=end_date,
    )
    src = source or f'timeline_{timeframe}'
    stats = reconcile_prediction_stats(filtered, source=src)
    log_timeline_rebuild(timeframe, stats)
    return stats


def validate_prediction_lifecycle(records: Iterable[dict]) -> Dict[str, Any]:
    """
    Validate that each prediction id maps to exactly one canonical state.
    Returns counts, duplicate ids, and orphan verdicts.
    """
    unique = dedupe_prediction_records(records)
    by_id: Dict[Any, str] = {}
    duplicates: List[Any] = []
    issues: List[str] = []

    for rec in unique:
        pid = rec.get('id')
        canon = normalize_canonical_state(rec.get('verdict'), state=rec.get('state'))
        if pid is None:
            continue
        if pid in by_id:
            duplicates.append(pid)
            issues.append(f'duplicate_id:{pid}')
            continue
        by_id[pid] = canon

    stats = reconcile_prediction_stats(unique)
    partition_sum = stats.get('partition_sum', 0)
    total = stats.get('total', 0)
    if partition_sum != total:
        issues.append(f'partition_mismatch:sum={partition_sum} total={total}')
    if not stats.get('reconciliation_valid', True):
        issues.append(
            f'reconciliation_error:partition={stats.get("reconciliation_partition")} total={total}'
        )

    raw_total = sum(1 for r in records if isinstance(r, dict))
    if raw_total > total:
        issues.append(f'deduped_rows:{raw_total - total}')

    return {
        'valid': len(issues) == 0,
        'total': total,
        'partition_sum': partition_sum,
        'counts': stats.get('canonical_counts') or {},
        'stats': stats,
        'duplicate_ids': duplicates[:50],
        'issues': issues,
    }


def reconcile_export_records(
    records: Iterable[dict],
    *,
    source: str = 'export',
) -> Tuple[List[dict], Dict[str, Any]]:
    """Dedupe + validate; log summary for export pipelines."""
    unique = dedupe_prediction_records(records)
    report = validate_prediction_lifecycle(unique)
    if report['issues']:
        print(
            f'[Lifecycle] validate_prediction_lifecycle source={source} '
            f'issues={len(report["issues"])} total={report["total"]}',
            flush=True,
        )
        for issue in report['issues'][:10]:
            print(f'[Lifecycle]   {issue}', flush=True)
    return unique, report
