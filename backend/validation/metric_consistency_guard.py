"""
Metric consistency guard — detect impossible or conflicting runtime metrics.

Integrates with runtime_state and validation scripts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from backend.lifecycle.win_rate_engine import (
    compute_win_rate,
    win_rate_denominator,
)

MIN_WIN_RATE_SAMPLE = 5
AWAITING_CONFIDENCE_MSG = 'Awaiting statistical confidence'


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


def _add(issues: List[str], code: str, detail: str) -> None:
    issues.append(f'{code}:{detail}')


def validate_metric_consistency(state: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
    """
    Validate runtime_state-shaped payload.
    Returns (ok, issues).
    """
    issues: List[str] = []
    state = state or {}

    metrics = state.get('prediction_counts') or state.get('metrics') or {}
    wins = int(metrics.get('wins') or 0)
    losses = int(metrics.get('losses') or 0)
    evaluated = int(metrics.get('evaluated') or metrics.get('total_evaluated') or 0)
    pending = int(metrics.get('pending') or 0)
    total = int(metrics.get('prediction_total') or metrics.get('total_predictions') or 0)
    reported_wr = metrics.get('win_rate')

    if wins < 0 or losses < 0 or evaluated < 0 or pending < 0:
        _add(issues, 'negative_count', f'w={wins} l={losses} e={evaluated} p={pending}')

    denom = win_rate_denominator(wins, losses)
    if denom == 0 and reported_wr not in (None, 0, 0.0):
        _add(issues, 'impossible_win_rate', f'0 resolved but win_rate={reported_wr}')

    if denom > 0 and denom < MIN_WIN_RATE_SAMPLE:
        wr_field = state.get('win_rate') or {}
        if wr_field.get('statistically_confident'):
            _add(issues, 'premature_confidence', f'denom={denom} marked confident')
        if reported_wr not in (None, 0, 0.0) and str(wr_field.get('win_rate_display', '')).endswith('%'):
            if AWAITING_CONFIDENCE_MSG not in str(wr_field.get('win_rate_display', '')):
                _add(issues, 'win_rate_below_min', f'denom={denom} wr={reported_wr}')

    if denom >= MIN_WIN_RATE_SAMPLE and reported_wr is not None:
        expected = compute_win_rate(wins, losses)
        try:
            if abs(float(reported_wr) - expected) > 0.05:
                _add(issues, 'win_rate_formula', f'reported={reported_wr} expected={expected}')
        except (TypeError, ValueError):
            _add(issues, 'win_rate_type', str(reported_wr))

    if total and evaluated + pending != total:
        _add(issues, 'partition_mismatch', f'eval+pend={evaluated + pending} total={total}')

    fresh = state.get('snapshot_freshness') or {}
    intel = state.get('intelligence_status') or {}
    if fresh.get('stale') and fresh.get('fresh'):
        _add(issues, 'freshness_contradiction', 'stale and fresh both true')
    if fresh.get('stale') and intel.get('status') == 'ready' and not intel.get('degraded'):
        _add(issues, 'stale_ready_contradiction', 'stale snapshot but intelligence ready')

    lc = state.get('lifecycle') or {}
    lc_state = str(lc.get('lifecycle_state') or '')
    pipe = str(lc.get('pipeline_status') or metrics.get('pipeline_status') or '').upper()
    if lc_state == 'MARKET_ACTIVE' and pipe in ('COMPLETE', 'POSTMARKET_EVAL', 'POST_MARKET'):
        _add(issues, 'lifecycle_pipeline_overlap', f'{lc_state}+{pipe}')

    regime = state.get('regime') or {}
    internal = str(regime.get('regime_internal') or regime.get('internal') or '')
    display = str(regime.get('regime_display') or regime.get('display') or '')
    if internal and display and internal.replace('_', ' ').lower() == display.replace('-', ' ').lower():
        if '_' in internal and ' ' not in display:
            pass  # normalized display is fine
    if display.lower() in ('unknown', 'none', 'null'):
        _add(issues, 'regime_unknown_exposed', display)

    sources = state.get('metric_sources') or {}
    if sources:
        eval_counts = [v for k, v in sources.items() if 'evaluated' in k.lower()]
        if eval_counts and len(set(eval_counts)) > 1:
            _add(issues, 'duplicate_evaluated_sources', str(sources))

    tg = state.get('telegram_metrics') or {}
    for key in ('alerts_sent_today', 'suppressed_today', 'duplicate_blocks'):
        val = tg.get(key)
        if val is not None and int(val) < 0:
            _add(issues, 'negative_telegram_metric', f'{key}={val}')

    return len(issues) == 0, issues
