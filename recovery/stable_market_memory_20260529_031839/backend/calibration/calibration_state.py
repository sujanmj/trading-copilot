"""
Calibration phase machine — suppress overconfident tuning on small samples.
"""

from __future__ import annotations

from typing import Any, Dict

PHASE_LEARNING = 'LEARNING'
PHASE_EARLY = 'EARLY CONFIDENCE'
PHASE_CALIBRATED = 'CALIBRATED'
PHASE_HIGH = 'HIGH CONFIDENCE'

MIN_LEARNING = 5
MIN_EARLY = 20
MIN_CALIBRATED = 50
MIN_HIGH = 100


def resolved_sample_count(metrics: dict) -> int:
    wins = int(metrics.get('wins') or 0)
    losses = int(metrics.get('losses') or 0)
    neutral = int(metrics.get('neutral') or 0)
    partials = int(metrics.get('partials') or 0)
    return wins + losses + neutral + partials


def get_calibration_phase(metrics: dict) -> str:
    resolved = resolved_sample_count(metrics)
    if resolved < MIN_LEARNING:
        return PHASE_LEARNING
    if resolved < MIN_EARLY:
        return PHASE_EARLY
    if resolved < MIN_CALIBRATED:
        return PHASE_CALIBRATED
    if resolved < MIN_HIGH:
        return PHASE_CALIBRATED
    return PHASE_HIGH


def calibration_phase_message(phase: str) -> str:
    messages = {
        PHASE_LEARNING: 'Collecting resolved outcomes — calibration suppressed until sample is meaningful.',
        PHASE_EARLY: 'Early confidence — metrics directional only, not statistically stable.',
        PHASE_CALIBRATED: 'Calibrated — win-rate and thresholds reflect resolved sample.',
        PHASE_HIGH: 'High confidence — large resolved sample supports adaptive tuning.',
    }
    return messages.get(phase, messages[PHASE_LEARNING])


def build_calibration_display(metrics: dict) -> Dict[str, Any]:
    phase = get_calibration_phase(metrics)
    resolved = resolved_sample_count(metrics)
    return {
        'phase': phase,
        'resolved_sample': resolved,
        'min_calibrated': MIN_CALIBRATED,
        'min_high_confidence': MIN_HIGH,
        'message': calibration_phase_message(phase),
        'suppress_adaptive': phase in (PHASE_LEARNING, PHASE_EARLY),
        'show_win_rate': resolved >= MIN_EARLY,
    }
