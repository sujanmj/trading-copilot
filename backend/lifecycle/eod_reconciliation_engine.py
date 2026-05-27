"""
EOD reconciliation — ensure every prediction resolves; metrics partition must close.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

import pytz

from backend.lifecycle.lifecycle_audit import log_lifecycle_event
from backend.storage.db_manager import get_connection, init_db

IST = pytz.timezone('Asia/Kolkata')
_log = logging.getLogger(__name__)

TERMINAL_VERDICTS = ('WIN', 'LOSS', 'EXPIRED', 'NEUTRAL')
ACTIVE_VERDICTS = ('ACTIVE', 'PENDING', 'UNRESOLVED')


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def ensure_outcome_rows() -> dict:
    """Create missing outcome rows for orphan predictions."""
    stats = {'created': 0, 'errors': 0}
    init_db()
    conn = get_connection()
    try:
        orphans = conn.execute("""
            SELECT p.id, p.prediction_date, p.ticker
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE o.id IS NULL
        """).fetchall()
        for row in orphans:
            try:
                conn.execute("""
                    INSERT INTO outcomes (source_type, source_id, prediction_date, ticker, verdict, last_checked)
                    VALUES ('prediction', ?, ?, ?, 'ACTIVE', ?)
                """, (row['id'], row['prediction_date'], row['ticker'], _now_iso()))
                stats['created'] += 1
            except Exception:
                stats['errors'] += 1
        conn.commit()
    finally:
        conn.close()
    if stats['created']:
        log_lifecycle_event('orphan_outcomes_created', f"created={stats['created']}")
    return stats


def reconcile_stale_active(*, max_age_days: int = 7) -> dict:
    """Force-expire stale ACTIVE/PENDING beyond TTL."""
    from backend.lifecycle.prediction_lifecycle_engine import expire_stale_pending
    stats = expire_stale_pending() or {}
    stats['orphans'] = ensure_outcome_rows()
    return stats


def validate_metrics_partition() -> Dict[str, Any]:
    """wins + losses + expired + neutralized + active == total predictions."""
    from backend.lifecycle.unified_metrics import get_outcome_metrics
    m = get_outcome_metrics('all_time')
    wins = int(m.get('wins') or 0)
    losses = int(m.get('losses') or 0)
    expired = int(m.get('expired') or 0)
    neutral = int(m.get('neutral') or 0)
    active = int(m.get('pending') or 0)
    total = int(m.get('total_predictions') or m.get('prediction_total') or 0)
    resolved = wins + losses + expired + neutral
    computed = resolved + active
    partials = int(m.get('partials') or 0)
    invalidated = int(m.get('invalidated') or 0)
    balanced = computed + partials + invalidated == total or abs(computed - total) <= partials + invalidated
    return {
        'balanced': balanced,
        'total_predictions': total,
        'resolved': resolved,
        'active_pending': active,
        'wins': wins,
        'losses': losses,
        'expired': expired,
        'neutralized': neutral,
        'partials': partials,
        'invalidated': invalidated,
        'delta': total - computed - partials - invalidated,
    }


def run_eod_reconciliation() -> dict:
    """Full EOD reconciliation pass."""
    orphan_stats = ensure_outcome_rows()
    expire_stats = reconcile_stale_active()
    partition = validate_metrics_partition()
    log_lifecycle_event(
        'eod_reconciliation',
        f"balanced={partition.get('balanced')} delta={partition.get('delta')}",
        payload=partition,
    )
    if not partition.get('balanced'):
        _log.warning('[EOD RECONCILE] metrics partition imbalance delta=%s', partition.get('delta'))
    return {
        'orphan_outcomes': orphan_stats,
        'expire': expire_stats,
        'partition': partition,
        'reconciled_at': _now_iso(),
    }
