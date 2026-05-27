"""Interval pending cleanup between EOD cycles."""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def tick_pending_cleanup() -> dict:
    """Expire stale pending rows and archive terminal expired outcomes."""
    from backend.utils.market_hours import get_lifecycle_state
    state = get_lifecycle_state()
    if state == 'NIGHT_IDLE':
        return {'skipped': True, 'reason': 'night_idle'}

    from backend.lifecycle.prediction_lifecycle_engine import expire_stale_pending
    stats = expire_stale_pending() or {}
    _log.info('[PENDING DAEMON] expired=%s neutralized=%s', stats.get('expired'), stats.get('neutralized'))
    return stats
