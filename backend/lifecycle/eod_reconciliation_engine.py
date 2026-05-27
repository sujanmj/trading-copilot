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

TERMINAL_VERDICTS = ('WIN', 'LOSS', 'EXPIRED', 'NEUTRAL', 'CANCELLED')
ACTIVE_VERDICTS = ('ACTIVE', 'PENDING', 'UNRESOLVED')


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def detect_missing_predictions() -> dict:
    """Find predictions without outcome rows or orphaned outcome rows."""
    stats = {'missing_outcomes': 0, 'orphan_outcomes': 0, 'prediction_ids': []}
    init_db()
    conn = get_connection()
    try:
        orphans = conn.execute("""
            SELECT p.id, p.prediction_date, p.ticker
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE o.id IS NULL
        """).fetchall()
        stats['missing_outcomes'] = len(orphans)
        stats['prediction_ids'] = [row['id'] for row in orphans[:20]]
        orphan_out = conn.execute("""
            SELECT o.id, o.source_id
            FROM outcomes o
            LEFT JOIN predictions p ON p.id = o.source_id AND o.source_type='prediction'
            WHERE o.source_type='prediction' AND p.id IS NULL
        """).fetchall()
        stats['orphan_outcomes'] = len(orphan_out)
    finally:
        conn.close()
    return stats


def ensure_outcome_rows() -> dict:
    """Create missing outcome rows for orphan predictions."""
    stats = {'created': 0, 'errors': 0}
    missing = detect_missing_predictions()
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
    stats['missing_before'] = missing.get('missing_outcomes', 0)
    return stats


def recount_active_predictions() -> dict:
    """Reconcile active_predictions.json count with SQLite ACTIVE/PENDING."""
    stats = {'sqlite_active': 0, 'export_active': 0, 'delta': 0}
    init_db()
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT COUNT(*) AS cnt FROM outcomes
            WHERE verdict IN ('ACTIVE', 'PENDING', 'UNRESOLVED')
        """).fetchone()
        stats['sqlite_active'] = int(row['cnt'] or 0) if row else 0
    finally:
        conn.close()
    try:
        from backend.utils.config import DATA_DIR
        import json
        path = DATA_DIR / 'active_predictions.json'
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            preds = data.get('predictions') or []
            stats['export_active'] = sum(
                1 for p in preds
                if str(p.get('state') or '').upper() in ('ACTIVE', 'PENDING')
            )
    except Exception:
        pass
    stats['delta'] = stats['sqlite_active'] - stats['export_active']
    if stats['delta'] != 0:
        log_lifecycle_event('active_prediction_recount', f"sqlite={stats['sqlite_active']} export={stats['export_active']}")
    return stats


def reconcile_stale_active(*, max_age_days: int = 7) -> dict:
    """Force-expire stale ACTIVE/PENDING beyond TTL."""
    from backend.lifecycle.prediction_lifecycle_engine import expire_stale_pending
    stats = expire_stale_pending() or {}
    stats['orphans'] = ensure_outcome_rows()
    stats['active_recount'] = recount_active_predictions()
    return stats


def validate_metrics_partition() -> Dict[str, Any]:
    """wins + losses + expired + neutralized + cancelled + active == total predictions."""
    from backend.lifecycle.unified_metrics import get_outcome_metrics
    m = get_outcome_metrics('all_time')
    wins = int(m.get('wins') or 0)
    losses = int(m.get('losses') or 0)
    expired = int(m.get('expired') or 0)
    neutral = int(m.get('neutral') or 0)
    cancelled = int(m.get('cancelled') or 0)
    active = int(m.get('pending') or 0)
    total = int(m.get('total_predictions') or m.get('prediction_total') or 0)
    resolved = wins + losses + expired + neutral + cancelled
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
        'cancelled': cancelled,
        'partials': partials,
        'invalidated': invalidated,
        'delta': total - computed - partials - invalidated,
        'missing_predictions': detect_missing_predictions(),
    }


def run_eod_reconciliation() -> dict:
    """Full EOD reconciliation pass."""
    orphan_stats = ensure_outcome_rows()
    expire_stats = reconcile_stale_active()
    partition = validate_metrics_partition()
    active_recount = recount_active_predictions()
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
        'active_recount': active_recount,
        'reconciled_at': _now_iso(),
    }
