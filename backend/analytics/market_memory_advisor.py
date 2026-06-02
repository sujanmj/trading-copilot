"""
Read-only shadow learning advisor for market memory predictions.

Uses historical performance from market_memory_learning; does not alter predictions.
"""

from __future__ import annotations

from typing import Any

from backend.analytics.market_memory_learning import get_learning_summary, get_ticker_performance

SHADOW_MODE = True

SAMPLE_GATES: dict[str, int] = {
    'ticker': 5,
    'signal_type': 10,
    'confidence_label': 10,
    'prediction_horizon': 10,
    'broker_consensus': 10,
}

ADVICE_ORDER: dict[str, int] = {
    'avoid_candidate': 0,
    'caution': 1,
    'neutral': 2,
    'boost': 3,
}

DIMENSION_WEIGHTS: dict[str, float] = {
    'ticker': 1.5,
    'signal_type': 1.0,
    'confidence_label': 1.0,
    'prediction_horizon': 0.75,
    'broker_consensus': 0.75,
}


def _normalize_text(value: object, *, upper: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.upper() if upper else text


def _normalize_candidate(candidate: dict[str, Any]) -> dict[str, str | None]:
    confidence = candidate.get('confidence_label') or candidate.get('confidence')
    broker = candidate.get('broker_consensus')
    agreement = None
    if isinstance(broker, dict):
        agreement = broker.get('agreement_direction')
    if agreement is None:
        agreement = candidate.get('agreement_direction') or candidate.get('direction')

    return {
        'ticker': _normalize_text(candidate.get('ticker'), upper=True),
        'confidence_label': _normalize_text(confidence, upper=True),
        'signal_type': _normalize_text(candidate.get('signal_type')),
        'prediction_horizon': _normalize_text(
            candidate.get('prediction_horizon') or candidate.get('horizon'),
        ),
        'broker_consensus': _normalize_text(agreement, upper=True),
    }


def _advice_from_win_rate(win_rate: float | None) -> str:
    if win_rate is None:
        return 'neutral'
    if win_rate >= 0.60:
        return 'boost'
    if win_rate >= 0.40:
        return 'neutral'
    if win_rate >= 0.25:
        return 'caution'
    return 'avoid_candidate'


def _score_from_win_rate(win_rate: float | None) -> int:
    if win_rate is None:
        return 50
    return max(0, min(100, round(win_rate * 100)))


def _evaluate_dimension(
    *,
    dimension: str,
    key: str | None,
    metrics: dict[str, Any] | None,
    gate: int,
) -> dict[str, Any]:
    if not key:
        return {
            'dimension': dimension,
            'key': None,
            'advice': 'neutral',
            'learning_score': 50,
            'sample_size': 0,
            'win_rate': None,
            'wins': 0,
            'losses': 0,
            'warnings': ['missing_key'],
            'reason': f'{dimension}: key missing => neutral',
        }

    if not metrics:
        return {
            'dimension': dimension,
            'key': key,
            'advice': 'neutral',
            'learning_score': 50,
            'sample_size': 0,
            'win_rate': None,
            'wins': 0,
            'losses': 0,
            'warnings': ['no_history'],
            'reason': f'{dimension}={key}: no resolved history => neutral',
        }

    resolved = int(metrics.get('resolved') or 0)
    wins = int(metrics.get('wins') or 0)
    losses = int(metrics.get('losses') or 0)
    win_rate = metrics.get('win_rate')

    if resolved < gate:
        return {
            'dimension': dimension,
            'key': key,
            'advice': 'neutral',
            'learning_score': _score_from_win_rate(win_rate if isinstance(win_rate, (int, float)) else None),
            'sample_size': resolved,
            'win_rate': win_rate,
            'wins': wins,
            'losses': losses,
            'warnings': ['low_sample_size'],
            'reason': (
                f'{dimension}={key}: sample {resolved} < gate {gate} => neutral (low_sample_size)'
            ),
        }

    advice = _advice_from_win_rate(win_rate if isinstance(win_rate, (int, float)) else None)
    rate_pct = f'{float(win_rate) * 100:.1f}%' if isinstance(win_rate, (int, float)) else 'N/A'
    return {
        'dimension': dimension,
        'key': key,
        'advice': advice,
        'learning_score': _score_from_win_rate(win_rate if isinstance(win_rate, (int, float)) else None),
        'sample_size': resolved,
        'win_rate': win_rate,
        'wins': wins,
        'losses': losses,
        'warnings': [],
        'reason': f'{dimension}={key}: win_rate {rate_pct} ({wins}W/{losses}L) => {advice}',
    }


def _lookup_group_map(summary: dict[str, Any], dimension: str) -> dict[str, Any]:
    mapping = {
        'ticker': 'by_ticker',
        'signal_type': 'by_signal_type',
        'confidence_label': 'by_confidence_label',
        'prediction_horizon': 'by_prediction_horizon',
        'broker_consensus': 'by_broker_consensus',
    }
    return summary.get(mapping[dimension]) or {}


def _combine_components(components: dict[str, dict[str, Any]]) -> tuple[str, int, list[str], list[str]]:
    warnings: list[str] = []
    reasons: list[str] = []
    weighted_score = 0.0
    weight_total = 0.0
    worst_advice = 'boost'

    for dimension, component in components.items():
        for warning in component.get('warnings') or []:
            if warning not in warnings:
                warnings.append(warning)
        reason = component.get('reason')
        if reason:
            reasons.append(str(reason))

        advice = str(component.get('advice') or 'neutral')
        if ADVICE_ORDER.get(advice, 2) < ADVICE_ORDER.get(worst_advice, 2):
            worst_advice = advice

        sample_size = int(component.get('sample_size') or 0)
        gate = SAMPLE_GATES.get(dimension, 10)
        if sample_size >= gate:
            weight = DIMENSION_WEIGHTS.get(dimension, 1.0) * sample_size
            weighted_score += float(component.get('learning_score') or 50) * weight
            weight_total += weight

    if weight_total > 0:
        learning_score = max(0, min(100, round(weighted_score / weight_total)))
    else:
        learning_score = 50
        if 'low_sample_size' not in warnings:
            warnings.append('low_sample_size')

    return worst_advice, learning_score, warnings, reasons


def _build_advice_payload(
    *,
    ticker: str | None,
    components: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    overall_advice, learning_score, warnings, reasons = _combine_components(components)
    sample_sizes = [int(c.get('sample_size') or 0) for c in components.values() if int(c.get('sample_size') or 0) > 0]
    sample_size = min(sample_sizes) if sample_sizes else 0

    return {
        'ticker': ticker,
        'overall_advice': overall_advice,
        'learning_score': learning_score,
        'sample_size': sample_size,
        'warnings': warnings,
        'reasons': reasons,
        'components': components,
        'shadow_mode': SHADOW_MODE,
    }


def advise_prediction(
    candidate: dict[str, Any],
    *,
    limit_days: int | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return shadow learning advice for a prediction candidate."""
    normalized = _normalize_candidate(candidate)
    ticker = normalized.get('ticker')
    learning = summary if summary is not None else get_learning_summary(limit_days=limit_days)

    components: dict[str, dict[str, Any]] = {}

    ticker_metrics = None
    if ticker:
        ticker_map = _lookup_group_map(learning, 'ticker')
        ticker_metrics = ticker_map.get(ticker)
    components['ticker'] = _evaluate_dimension(
        dimension='ticker',
        key=ticker,
        metrics=ticker_metrics,
        gate=SAMPLE_GATES['ticker'],
    )

    for dimension, key in (
        ('signal_type', normalized.get('signal_type')),
        ('confidence_label', normalized.get('confidence_label')),
        ('prediction_horizon', normalized.get('prediction_horizon')),
        ('broker_consensus', normalized.get('broker_consensus')),
    ):
        group_map = _lookup_group_map(learning, dimension)
        metrics = group_map.get(key) if key else None
        components[dimension] = _evaluate_dimension(
            dimension=dimension,
            key=key,
            metrics=metrics,
            gate=SAMPLE_GATES[dimension],
        )

    return _build_advice_payload(ticker=ticker, components=components)


def advise_ticker(
    ticker: str,
    *,
    limit_days: int | None = None,
) -> dict[str, Any]:
    """Return shadow learning advice scoped to a ticker."""
    normalized = str(ticker or '').strip().upper()
    perf = get_ticker_performance(normalized, limit_days=limit_days)
    metrics = perf.get('performance') if perf.get('ok') else None

    components = {
        'ticker': _evaluate_dimension(
            dimension='ticker',
            key=normalized,
            metrics=metrics,
            gate=SAMPLE_GATES['ticker'],
        ),
    }
    return _build_advice_payload(ticker=normalized, components=components)


def advise_batch(
    candidates: list[dict[str, Any]],
    *,
    limit_days: int | None = None,
) -> list[dict[str, Any]]:
    """Return shadow learning advice for multiple candidates."""
    summary = get_learning_summary(limit_days=limit_days)
    return [
        advise_prediction(candidate, limit_days=limit_days, summary=summary)
        for candidate in candidates
    ]


VALID_BATCH_ADVICE = frozenset({'boost', 'neutral', 'caution', 'avoid_candidate'})


def _prediction_to_candidate(prediction: dict[str, Any]) -> dict[str, Any]:
    from backend.analytics.market_memory_learning import (
        _extract_broker_consensus,
        _extract_horizon,
        _extract_signal_type,
    )

    signal_stack = prediction.get('signal_stack')
    raw_payload = prediction.get('raw_payload')
    broker = _extract_broker_consensus(signal_stack, raw_payload)
    broker_consensus = (
        {'agreement_direction': broker}
        if broker and broker != 'UNKNOWN'
        else None
    )
    return {
        'prediction_id': prediction.get('prediction_id'),
        'ticker': prediction.get('ticker'),
        'direction': prediction.get('direction'),
        'confidence_label': prediction.get('confidence_label'),
        'signal_type': _extract_signal_type(signal_stack, raw_payload),
        'prediction_horizon': _extract_horizon(signal_stack, raw_payload),
        'broker_consensus': broker_consensus,
    }


def fetch_unresolved_predictions(
    *,
    limit: int | None = None,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Return predictions with no resolved outcome (read-only)."""
    from backend.storage.market_memory_db import get_connection, get_market_memory_stats

    stats = get_market_memory_stats()
    if not stats.get('db_exists'):
        return []

    clauses = [
        """
        NOT EXISTS (
            SELECT 1 FROM outcomes o
            WHERE o.prediction_id = p.prediction_id
              AND o.resolved_as IS NOT NULL
        )
        """,
    ]
    params: list[Any] = []

    if ticker:
        clauses.append('UPPER(p.ticker) = ?')
        params.append(str(ticker).strip().upper())

    sql = f"""
        SELECT p.*
        FROM predictions p
        WHERE {' AND '.join(clauses)}
        ORDER BY p.timestamp ASC
    """
    if limit is not None and int(limit) > 0:
        sql += ' LIMIT ?'
        params.append(int(limit))

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_advisor_batch_report(
    *,
    limit: int | None = None,
    advice: str | None = None,
    ticker: str | None = None,
    limit_days: int | None = None,
) -> dict[str, Any]:
    """Score unresolved predictions in shadow mode; optional advice filter on rows."""
    predictions = fetch_unresolved_predictions(limit=limit, ticker=ticker)
    learning = get_learning_summary(limit_days=limit_days)

    counts = {key: 0 for key in VALID_BATCH_ADVICE}
    all_rows: list[dict[str, Any]] = []

    for prediction in predictions:
        candidate = _prediction_to_candidate(prediction)
        advice_payload = advise_prediction(candidate, limit_days=limit_days, summary=learning)
        overall = str(advice_payload.get('overall_advice') or 'neutral')
        if overall in counts:
            counts[overall] += 1

        broker_val = candidate.get('broker_consensus')
        broker_display = (
            broker_val.get('agreement_direction')
            if isinstance(broker_val, dict)
            else broker_val
        )

        all_rows.append({
            'prediction_id': prediction.get('prediction_id'),
            'ticker': candidate.get('ticker'),
            'direction': prediction.get('direction'),
            'confidence_label': candidate.get('confidence_label'),
            'signal_type': candidate.get('signal_type'),
            'horizon': candidate.get('prediction_horizon'),
            'broker_consensus': broker_display,
            'advice': overall,
            'learning_score': advice_payload.get('learning_score'),
            'warnings': advice_payload.get('warnings') or [],
        })

    filtered_rows = all_rows
    if advice:
        normalized = str(advice).strip().lower()
        filtered_rows = [row for row in all_rows if row.get('advice') == normalized]

    return {
        'ok': True,
        'checked': len(all_rows),
        'boost': counts['boost'],
        'neutral': counts['neutral'],
        'caution': counts['caution'],
        'avoid_candidate': counts['avoid_candidate'],
        'shadow_mode': SHADOW_MODE,
        'rows': filtered_rows,
    }
