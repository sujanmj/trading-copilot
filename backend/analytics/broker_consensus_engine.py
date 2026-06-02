"""
Broker/source consensus engine for canonical_market_memory.db broker_predictions.

Reads broker picks, normalizes stances, and calculates agreement across sources.
"""

from __future__ import annotations

import sys
from typing import Any

BULLISH_TOKENS = frozenset(
    {'BUY', 'STRONG_BUY', 'ACCUMULATE', 'OUTPERFORM', 'LONG', 'BULLISH'}
)
BEARISH_TOKENS = frozenset(
    {'SELL', 'STRONG_SELL', 'REDUCE', 'UNDERPERFORM', 'SHORT', 'BEARISH'}
)
NEUTRAL_TOKENS = frozenset({'HOLD', 'NEUTRAL', 'WATCH', 'WAIT'})


def _log_error(message: str) -> None:
    print(f'[BROKER_CONSENSUS] error: {message}', file=sys.stderr)


def normalize_broker_stance(value: str | None) -> str | None:
    """Map broker stance tokens to BULLISH, BEARISH, or NEUTRAL."""
    if value is None:
        return None
    token = str(value).strip().upper().replace(' ', '_').replace('-', '_')
    if not token:
        return None
    if token in BULLISH_TOKENS:
        return 'BULLISH'
    if token in BEARISH_TOKENS:
        return 'BEARISH'
    if token in NEUTRAL_TOKENS:
        return 'NEUTRAL'
    for bullish in BULLISH_TOKENS:
        if bullish in token:
            return 'BULLISH'
    for bearish in BEARISH_TOKENS:
        if bearish in token:
            return 'BEARISH'
    for neutral in NEUTRAL_TOKENS:
        if neutral in token:
            return 'NEUTRAL'
    return token


def _source_entry(item: dict) -> dict[str, Any]:
    return {
        'broker_source': item.get('broker_source'),
        'ticker': item.get('ticker'),
        'bullish_or_bearish': item.get('bullish_or_bearish'),
        'confidence': item.get('confidence'),
        'timeframe': item.get('timeframe'),
    }


def _resolve_agreement_direction(
    bullish_count: int,
    bearish_count: int,
    neutral_count: int,
) -> str:
    if bullish_count > bearish_count and bullish_count >= neutral_count:
        return 'BULLISH'
    if bearish_count > bullish_count and bearish_count >= neutral_count:
        return 'BEARISH'
    if neutral_count > bullish_count and neutral_count > bearish_count:
        return 'NEUTRAL'
    return 'MIXED'


def _build_summary(direction: str, bullish_count: int, bearish_count: int, neutral_count: int, total: int) -> str:
    if total == 0 or direction == 'UNKNOWN':
        return 'No broker predictions'
    if direction == 'BULLISH':
        return f'Agreement: {bullish_count}/{total} bullish'
    if direction == 'BEARISH':
        return f'Agreement: {bearish_count}/{total} bearish'
    if direction == 'NEUTRAL':
        return f'Agreement: {neutral_count}/{total} neutral'
    if direction == 'MIXED':
        return (
            f'Mixed signals: {bullish_count} bullish, '
            f'{bearish_count} bearish, {neutral_count} neutral'
        )
    return 'Unknown agreement'


def calculate_consensus(items: list[dict]) -> dict:
    """Calculate broker agreement from normalized prediction items."""
    ticker = ''
    bullish_sources: list[dict] = []
    bearish_sources: list[dict] = []
    neutral_sources: list[dict] = []
    confidence_values: list[float] = []

    for item in items:
        if not ticker and item.get('ticker'):
            ticker = str(item['ticker']).strip().upper()

        stance = normalize_broker_stance(item.get('bullish_or_bearish'))
        entry = _source_entry({**item, 'bullish_or_bearish': stance})

        confidence = item.get('confidence')
        if confidence is not None:
            try:
                confidence_values.append(float(confidence))
            except (TypeError, ValueError):
                pass

        if stance == 'BULLISH':
            bullish_sources.append(entry)
        elif stance == 'BEARISH':
            bearish_sources.append(entry)
        elif stance == 'NEUTRAL':
            neutral_sources.append(entry)

    bullish_count = len(bullish_sources)
    bearish_count = len(bearish_sources)
    neutral_count = len(neutral_sources)
    total_sources = len(items)

    if total_sources == 0:
        return {
            'ticker': ticker,
            'total_sources': 0,
            'bullish_count': 0,
            'bearish_count': 0,
            'neutral_count': 0,
            'agreement_direction': 'UNKNOWN',
            'agreement_ratio': 0.0,
            'average_confidence': None,
            'sources': {'bullish': [], 'bearish': [], 'neutral': []},
            'summary': 'No broker predictions',
        }

    agreement_direction = _resolve_agreement_direction(
        bullish_count, bearish_count, neutral_count
    )

    if agreement_direction == 'BULLISH':
        dominant_count = bullish_count
    elif agreement_direction == 'BEARISH':
        dominant_count = bearish_count
    elif agreement_direction == 'NEUTRAL':
        dominant_count = neutral_count
    else:
        dominant_count = max(bullish_count, bearish_count, neutral_count)

    agreement_ratio = round(dominant_count / total_sources, 4) if total_sources else 0.0
    average_confidence = (
        round(sum(confidence_values) / len(confidence_values), 4)
        if confidence_values
        else None
    )

    return {
        'ticker': ticker,
        'total_sources': total_sources,
        'bullish_count': bullish_count,
        'bearish_count': bearish_count,
        'neutral_count': neutral_count,
        'agreement_direction': agreement_direction,
        'agreement_ratio': agreement_ratio,
        'average_confidence': average_confidence,
        'sources': {
            'bullish': bullish_sources,
            'bearish': bearish_sources,
            'neutral': neutral_sources,
        },
        'summary': _build_summary(
            agreement_direction,
            bullish_count,
            bearish_count,
            neutral_count,
            total_sources,
        ),
    }


def get_broker_predictions_for_ticker(
    ticker: str,
    timeframe: str | None = None,
) -> list[dict]:
    """Read broker_predictions rows for a ticker from canonical_market_memory.db."""
    try:
        from backend.storage.market_memory_db import get_connection, init_market_memory_db

        if not init_market_memory_db():
            _log_error('init_market_memory_db returned False')
            return []

        normalized_ticker = str(ticker).strip().upper()
        conn = get_connection()
        try:
            if timeframe is not None:
                rows = conn.execute(
                    """
                    SELECT id, prediction_id, broker_source, ticker, bullish_or_bearish,
                           target_type, timeframe, confidence, raw_payload, created_at
                    FROM broker_predictions
                    WHERE ticker = ? AND timeframe = ?
                    ORDER BY created_at DESC
                    """,
                    (normalized_ticker, timeframe),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, prediction_id, broker_source, ticker, bullish_or_bearish,
                           target_type, timeframe, confidence, raw_payload, created_at
                    FROM broker_predictions
                    WHERE ticker = ?
                    ORDER BY created_at DESC
                    """,
                    (normalized_ticker,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception as exc:
        _log_error(f'get_broker_predictions_for_ticker failed: {exc}')
        return []


def get_consensus_for_ticker(ticker: str, timeframe: str | None = None) -> dict:
    """Load broker predictions and calculate consensus for a ticker."""
    items = get_broker_predictions_for_ticker(ticker, timeframe=timeframe)
    consensus = calculate_consensus(items)
    if not consensus.get('ticker'):
        consensus['ticker'] = str(ticker).strip().upper()
    return consensus


def upsert_broker_pick(payload: dict) -> int | None:
    """Safely upsert a broker prediction with normalized stance."""
    try:
        from backend.storage.market_memory_db import upsert_broker_prediction

        data = dict(payload)
        if data.get('ticker'):
            data['ticker'] = str(data['ticker']).strip().upper()
        data['bullish_or_bearish'] = normalize_broker_stance(
            data.get('bullish_or_bearish')
        )
        return upsert_broker_prediction(data)
    except Exception as exc:
        _log_error(f'upsert_broker_pick failed: {exc}')
        return None
