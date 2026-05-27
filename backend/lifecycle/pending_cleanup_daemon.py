"""Interval pending cleanup between EOD cycles."""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def tick_pending_cleanup() -> dict:
    """Expire stale pending rows and reconcile orphan outcomes."""
    from backend.utils.market_hours import get_market_period
    if get_market_period() == 'weekend':
        return {'skipped': True, 'reason': 'weekend'}

    from backend.lifecycle.prediction_lifecycle_engine import expire_stale_pending
    from backend.lifecycle.eod_reconciliation_engine import ensure_outcome_rows
    stats = expire_stale_pending() or {}
    stats['orphans'] = ensure_outcome_rows()
    _log.info('[PENDING DAEMON] expired=%s neutralized=%s', stats.get('expired'), stats.get('neutralized'))
    return stats
