"""
Canonical metrics — single source for win rate and prediction counts on all surfaces.

Consolidates win_rate_engine + metric_consistency_guard display rules.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.lifecycle.win_rate_engine import (
    AWAITING_CONFIDENCE_MSG,
    MIN_WIN_RATE_SAMPLE,
    compute_win_rate,
    win_rate_denominator,
)

__all__ = [
    'AWAITING_CONFIDENCE_MSG',
    'MIN_WIN_RATE_SAMPLE',
    'build_canonical_metrics',
    'format_win_rate_display',
    'resolved_outcomes',
    'validate_win_rate',
]


def resolved_outcomes(wins: int, losses: int) -> int:
    """Win/loss only — excludes neutral/expired from win-rate denominator."""
    return win_rate_denominator(wins, losses)


def format_win_rate_display(
    wins: int,
    losses: int,
    *,
    min_sample: int = MIN_WIN_RATE_SAMPLE,
) -> Dict[str, Any]:
    """Canonical win-rate display — never show fake percentages."""
    denom = win_rate_denominator(wins, losses)
    if denom < min_sample:
        return {
            'win_rate': None,
            'win_rate_display': AWAITING_CONFIDENCE_MSG,
            'win_rate_denominator': denom,
            'statistically_confident': False,
            'wins': int(wins or 0),
            'losses': int(losses or 0),
        }
    wr = compute_win_rate(wins, losses)
    return {
        'win_rate': wr,
        'win_rate_display': f'{wr:.1f}%',
        'win_rate_denominator': denom,
        'statistically_confident': True,
        'wins': int(wins or 0),
        'losses': int(losses or 0),
    }


def validate_win_rate(metrics: Optional[Dict[str, Any]]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    metrics = metrics or {}
    wins = int(metrics.get('wins') or 0)
    losses = int(metrics.get('losses') or 0)
    reported = metrics.get('win_rate')
    denom = win_rate_denominator(wins, losses)
    if denom == 0 and reported not in (None, 0, 0.0):
        issues.append(f'impossible_win_rate:0 resolved but wr={reported}')
    if denom > 0 and denom < MIN_WIN_RATE_SAMPLE and reported not in (None, 0, 0.0):
        issues.append(f'premature_win_rate:denom={denom}')
    if denom >= MIN_WIN_RATE_SAMPLE and reported is not None:
        expected = compute_win_rate(wins, losses)
        try:
            if abs(float(reported) - expected) > 0.05:
                issues.append(f'win_rate_formula:reported={reported} expected={expected}')
        except (TypeError, ValueError):
            issues.append(f'win_rate_type:{reported}')
    return len(issues) == 0, issues


def build_canonical_metrics(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize a metrics dict with canonical win_rate fields."""
    raw = dict(raw or {})
    wins = int(raw.get('wins') or 0)
    losses = int(raw.get('losses') or 0)
    partials = int(raw.get('partials') or 0)
    evaluated = int(raw.get('evaluated') or raw.get('total_evaluated') or 0)
    pending = int(raw.get('pending') or 0)
    expired = int(raw.get('expired') or 0)
    neutralized = int(raw.get('neutralized') or raw.get('neutral') or 0)
    resolved = resolved_outcomes(wins, losses)
    wr = format_win_rate_display(wins, losses)
    out = {
        **raw,
        'wins': wins,
        'losses': losses,
        'partials': partials,
        'resolved': resolved,
        'evaluated': evaluated,
        'pending': pending,
        'expired': expired,
        'neutralized': neutralized,
        'neutral': neutralized,
        'prediction_total': int(raw.get('prediction_total') or raw.get('total_predictions') or 0),
        'win_rate': wr.get('win_rate'),
        'win_rate_display': wr.get('win_rate_display'),
        'win_rate_denominator': wr.get('win_rate_denominator'),
        'statistically_confident': wr.get('statistically_confident'),
    }
    if not wr.get('statistically_confident'):
        out['win_rate'] = None
    return out
