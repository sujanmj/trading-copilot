"""
Canonical win-rate calculation — single source for all surfaces.

Formula: win_rate = WIN / (WIN + LOSS) × 100
Excluded from denominator: EXPIRED, NEUTRAL, CANCELLED, ACTIVE, PENDING, UNRESOLVED, PARTIAL, INVALIDATED
"""

from __future__ import annotations

from typing import Any, Dict, Optional

MIN_WIN_RATE_SAMPLE = 5
AWAITING_CONFIDENCE_MSG = 'Awaiting statistical confidence'


def win_rate_denominator(wins: int, losses: int) -> int:
    """Resolved outcomes that count toward win rate."""
    return max(0, int(wins or 0)) + max(0, int(losses or 0))


def compute_win_rate(wins: int, losses: int) -> float:
    """WIN / (WIN + LOSS) × 100, or 0 when no resolved win/loss pair."""
    denom = win_rate_denominator(wins, losses)
    if denom <= 0:
        return 0.0
    return round((int(wins or 0) / denom) * 100, 2)


def apply_win_rate(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Attach canonical win_rate to a metrics dict (mutates copy)."""
    out = dict(metrics)
    wins = int(out.get('wins') or 0)
    losses = int(out.get('losses') or 0)
    out['win_rate'] = compute_win_rate(wins, losses)
    out['win_rate_denominator'] = win_rate_denominator(wins, losses)
    out['win_rate_formula'] = 'WIN / (WIN + LOSS)'
    return out


def win_rate_from_metrics(metrics: Optional[Dict[str, Any]]) -> float:
    if not metrics:
        return 0.0
    return compute_win_rate(metrics.get('wins', 0), metrics.get('losses', 0))


def format_win_rate_line(metrics: Dict[str, Any], *, min_sample: int = MIN_WIN_RATE_SAMPLE) -> str:
    """Telegram/HTML win-rate line using canonical formula."""
    wins = int(metrics.get('wins') or 0)
    losses = int(metrics.get('losses') or 0)
    denom = win_rate_denominator(wins, losses)
    if denom < min_sample:
        if wins > 0 and denom > 0:
            return '<i>Early positive sample detected.</i>\n'
        return '<i>Win rate withheld — sample below minimum threshold.</i>\n'
    wr = compute_win_rate(wins, losses)
    return f"<b>Win Rate:</b> {wr:.1f}% <i>({wins}W / {losses}L)</i>\n"
