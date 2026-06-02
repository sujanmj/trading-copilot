"""
Score broker consensus evidence for a prediction candidate (shadow adjustment only).
"""

from __future__ import annotations

from typing import Any

from backend.analytics.broker_consensus_engine import get_consensus_for_ticker

MAX_ADJUSTMENT = 20
MIN_ADJUSTMENT = -20


def _normalize_ticker(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _candidate_direction(candidate: dict[str, Any]) -> str | None:
    for key in ('direction', 'signal_type', 'bias'):
        val = candidate.get(key)
        if val is not None and str(val).strip():
            token = str(val).strip().upper()
            if token in {'BUY', 'BULLISH', 'LONG', 'ACCUMULATE'}:
                return 'BULLISH'
            if token in {'SELL', 'BEARISH', 'SHORT', 'REDUCE'}:
                return 'BEARISH'
            if token in {'WATCH', 'HOLD', 'NEUTRAL'}:
                return 'NEUTRAL'
            return token
    broker = candidate.get('broker_consensus')
    if isinstance(broker, dict):
        direction = broker.get('agreement_direction')
        if direction:
            return str(direction).strip().upper()
    return None


def score_broker_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Return broker consensus scoring for a candidate.

    confidence_adjustment is clamped to [-20, +20].
    """
    ticker = _normalize_ticker(candidate.get('ticker'))
    if not ticker:
        return {
            'ok': False,
            'error': 'ticker is required',
            'confidence_adjustment': 0,
        }

    timeframe = candidate.get('timeframe') or candidate.get('prediction_horizon')
    consensus = get_consensus_for_ticker(ticker, timeframe=timeframe)
    total = int(consensus.get('total_sources') or 0)
    our_dir = _candidate_direction(candidate)
    broker_dir = consensus.get('agreement_direction')

    if total == 0 or broker_dir in {None, 'UNKNOWN'}:
        return {
            'ok': True,
            'ticker': ticker,
            'total_sources': total,
            'agreement_direction': broker_dir,
            'confidence_adjustment': 0,
            'reason': 'no_broker_evidence',
            'consensus': consensus,
        }

    ratio = float(consensus.get('agreement_ratio') or 0.0)
    avg_conf = consensus.get('average_confidence')
    conf_factor = float(avg_conf) if avg_conf is not None else 0.65
    conf_factor = max(0.35, min(1.0, conf_factor))

    adjustment = 0.0
    reason = 'neutral_broker_signal'

    if our_dir and broker_dir in {'BULLISH', 'BEARISH', 'NEUTRAL'}:
        if our_dir == broker_dir:
            adjustment = ratio * MAX_ADJUSTMENT * conf_factor
            reason = 'broker_agrees_with_candidate'
        elif our_dir != 'NEUTRAL' and broker_dir != 'NEUTRAL':
            adjustment = -ratio * abs(MIN_ADJUSTMENT) * conf_factor
            reason = 'broker_conflicts_with_candidate'
        else:
            adjustment = ratio * 5 * conf_factor
            reason = 'partial_broker_signal'
    elif broker_dir in {'BULLISH', 'BEARISH'}:
        adjustment = ratio * 8 * conf_factor
        reason = 'broker_direction_without_candidate'
    elif broker_dir == 'MIXED':
        adjustment = -4
        reason = 'mixed_broker_signals'

    adjustment = round(max(MIN_ADJUSTMENT, min(MAX_ADJUSTMENT, adjustment)))

    return {
        'ok': True,
        'ticker': ticker,
        'our_direction': our_dir,
        'agreement_direction': broker_dir,
        'total_sources': total,
        'agreement_ratio': ratio,
        'average_confidence': avg_conf,
        'confidence_adjustment': int(adjustment),
        'reason': reason,
        'consensus': consensus,
        'disclaimer': 'External broker evidence only; does not replace our prediction.',
    }
