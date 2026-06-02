"""
Alert priority routing — INFO / IMPORTANT / HIGH_IMPACT / CRITICAL.

Only HIGH_IMPACT and CRITICAL auto-push aggressively; INFO and IMPORTANT are suppressed or batched.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

INFO = 'INFO'
IMPORTANT = 'IMPORTANT'
HIGH_IMPACT = 'HIGH_IMPACT'
CRITICAL = 'CRITICAL'

PRIORITY_RANK = {
    INFO: 1,
    IMPORTANT: 2,
    HIGH_IMPACT: 3,
    CRITICAL: 4,
}

# Map alert categories to default priority
from backend.orchestration.alert_filters import (  # noqa: E402
    EMERGENCY_MACRO_ALERT,
    INTRADAY_EVENT,
    INTRADAY_OPPORTUNITY,
    MARKET_CLOSE_SUMMARY,
    MIDDAY_UPDATE,
    PRE_MARKET,
)

CATEGORY_PRIORITY: Dict[str, str] = {
    EMERGENCY_MACRO_ALERT: CRITICAL,
    INTRADAY_OPPORTUNITY: HIGH_IMPACT,
    INTRADAY_EVENT: HIGH_IMPACT,
    PRE_MARKET: IMPORTANT,
    MIDDAY_UPDATE: IMPORTANT,
    MARKET_CLOSE_SUMMARY: IMPORTANT,
    'OUTCOME_REPORT': INFO,
}


def priority_for_category(category: str, *, confidence: float = 0.0) -> str:
    base = CATEGORY_PRIORITY.get(category, IMPORTANT)
    if confidence >= 0.9 and category != EMERGENCY_MACRO_ALERT:
        return HIGH_IMPACT
    if confidence < 0.5 and base == HIGH_IMPACT:
        return IMPORTANT
    return base


def should_auto_push(priority: str) -> bool:
    return priority in (HIGH_IMPACT, CRITICAL)


def should_suppress_or_batch(priority: str) -> bool:
    return priority in (INFO, IMPORTANT)


def evaluate_priority_gate(
    category: str,
    confidence: float = 0.0,
    *,
    force: bool = False,
) -> Tuple[bool, str, str]:
    """
    Returns (allow_send, reason, priority).
    IMPORTANT/INFO require elevated confidence unless force=True (e.g. user /brief).
    """
    priority = priority_for_category(category, confidence=confidence)
    if force:
        return True, 'forced', priority
    if should_auto_push(priority):
        return True, 'high_impact_or_critical', priority
    if should_suppress_or_batch(priority):
        threshold = 0.72 if priority == IMPORTANT else 0.85
        if confidence >= threshold:
            return True, 'elevated_confidence_override', priority
        return False, f'batch_or_suppress_{priority.lower()}', priority
    return True, 'ok', priority
