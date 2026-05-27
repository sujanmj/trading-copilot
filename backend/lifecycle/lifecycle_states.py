"""
Canonical prediction lifecycle states for GUI, Telegram, and metrics.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

ACTIVE = 'ACTIVE'
RESOLVED_WIN = 'RESOLVED_WIN'
RESOLVED_LOSS = 'RESOLVED_LOSS'
EXPIRED = 'EXPIRED'
NEUTRALIZED = 'NEUTRALIZED'
CANCELLED = 'CANCELLED'

CANONICAL_TERMINAL = frozenset({RESOLVED_WIN, RESOLVED_LOSS, EXPIRED, NEUTRALIZED, CANCELLED})
CANONICAL_ACTIVE = frozenset({ACTIVE})

_VERDICT_MAP = {
    'ACTIVE': ACTIVE,
    'PENDING': ACTIVE,
    'WIN': RESOLVED_WIN,
    'LOSS': RESOLVED_LOSS,
    'PARTIAL': RESOLVED_WIN,
    'NEUTRAL': NEUTRALIZED,
    'EXPIRED': EXPIRED,
    'INVALIDATED': EXPIRED,
    'CANCELLED': CANCELLED,
    'UNRESOLVED': ACTIVE,
}


def to_canonical(verdict: Optional[str]) -> str:
    key = (verdict or 'ACTIVE').upper().strip()
    return _VERDICT_MAP.get(key, ACTIVE)


def is_resolved_for_win_rate(verdict: Optional[str]) -> bool:
    return to_canonical(verdict) in (RESOLVED_WIN, RESOLVED_LOSS)


def is_excluded_from_calibration(verdict: Optional[str]) -> bool:
    return to_canonical(verdict) in (EXPIRED, NEUTRALIZED)


def lifecycle_badge(verdict: Optional[str]) -> str:
    canon = to_canonical(verdict)
    icons = {
        ACTIVE: '🟡 ACTIVE',
        RESOLVED_WIN: '✅ WIN',
        RESOLVED_LOSS: '❌ LOSS',
        EXPIRED: '⏱ EXPIRED',
        NEUTRALIZED: '⚪ NEUTRAL',
        CANCELLED: '🚫 CANCELLED',
    }
    return icons.get(canon, canon)


def build_lifecycle_summary(metrics: dict, pending_cls: Optional[dict] = None) -> Dict[str, Any]:
    pending_cls = pending_cls or {}
    active = int(pending_cls.get('pending_active') or metrics.get('pending') or 0)
    return {
        'active': active,
        'resolved_win': int(metrics.get('wins') or 0),
        'resolved_loss': int(metrics.get('losses') or 0),
        'expired': int(metrics.get('expired') or pending_cls.get('expired') or 0),
        'neutralized': int(metrics.get('neutral') or pending_cls.get('neutralized_today') or 0),
        'cancelled': int(metrics.get('cancelled') or 0),
        'evaluated_for_win_rate': int(metrics.get('wins') or 0) + int(metrics.get('losses') or 0),
        'excluded_from_calibration': int(metrics.get('expired') or 0) + int(metrics.get('neutral') or 0),
    }
