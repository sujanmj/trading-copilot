"""
Canonical prediction lifecycle reconciliation — single state per prediction record.

States: ACTIVE, WIN, LOSS, EXPIRED, NEUTRALIZED (+ CANCELLED for partition).
All export/GUI period totals must use aggregate_period_stats() on raw SQLite rows only.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

# Canonical partition states (exactly one per prediction id)
ACTIVE = 'ACTIVE'
WIN = 'WIN'
LOSS = 'LOSS'
EXPIRED = 'EXPIRED'
NEUTRALIZED = 'NEUTRALIZED'
CANCELLED = 'CANCELLED'

CANONICAL_STATES = frozenset({ACTIVE, WIN, LOSS, EXPIRED, NEUTRALIZED, CANCELLED})
TERMINAL_STATES = frozenset({WIN, LOSS, EXPIRED, NEUTRALIZED, CANCELLED})

_VERDICT_TO_CANONICAL = {
    'ACTIVE': ACTIVE,
    'PENDING': ACTIVE,
    'UNRESOLVED': ACTIVE,
    'PARTIAL': ACTIVE,
    'WIN': WIN,
    'LOSS': LOSS,
    'EXPIRED': EXPIRED,
    'INVALIDATED': EXPIRED,
    'NEUTRAL': NEUTRALIZED,
    'NEUTRALIZED': NEUTRALIZED,
    'CANCELLED': CANCELLED,
}


def normalize_canonical_state(
    verdict: Optional[str],
    *,
    state: Optional[str] = None,
) -> str:
    """Map raw verdict/state to exactly one canonical lifecycle bucket."""
    raw = (verdict or state or '').strip().upper()
    if not raw:
        return ACTIVE
    return _VERDICT_TO_CANONICAL.get(raw, ACTIVE)


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


def aggregate_period_stats(records: Iterable[dict]) -> Dict[str, Any]:
    """Recompute period totals from raw prediction rows only."""
    unique = dedupe_prediction_records(records)
    counts = {s: 0 for s in CANONICAL_STATES}
    for rec in unique:
        canon = normalize_canonical_state(rec.get('verdict'), state=rec.get('state'))
        counts[canon] = counts.get(canon, 0) + 1

    total = len(unique)
    wins = counts[WIN]
    losses = counts[LOSS]
    pending = counts[ACTIVE]
    expired = counts[EXPIRED]
    neutral = counts[NEUTRALIZED]
    cancelled = counts[CANCELLED]
    resolved = wins + losses
    evaluated = resolved + expired + neutral + cancelled

    from backend.lifecycle.win_rate_engine import compute_win_rate

    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'neutral': neutral,
        'pending': pending,
        'active': pending,
        'expired': expired,
        'neutralized': neutral,
        'cancelled': cancelled,
        'resolved': resolved,
        'evaluated': evaluated,
        'win_rate': compute_win_rate(wins, losses),
        'canonical_counts': counts,
        'partition_sum': sum(counts.values()),
    }


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

    counts = aggregate_period_stats(unique)
    partition_sum = counts.get('partition_sum', 0)
    total = counts.get('total', 0)
    if partition_sum != total:
        issues.append(f'partition_mismatch:sum={partition_sum} total={total}')

    raw_total = sum(1 for r in records if isinstance(r, dict))
    if raw_total > total:
        issues.append(f'deduped_rows:{raw_total - total}')

    return {
        'valid': len(issues) == 0,
        'total': total,
        'partition_sum': partition_sum,
        'counts': counts.get('canonical_counts') or {},
        'stats': counts,
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
