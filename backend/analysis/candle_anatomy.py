"""
AstraEdge 53A — deterministic single-candle anatomy.

Facts and shape descriptors only. No trade interpretation.
Operates on one already-loaded OHLCV candle. No I/O, HTTP, AI, or context.
"""

from __future__ import annotations

import math
from typing import Any, Optional

SCHEMA_VERSION = '53A'

DIRECTION_BULLISH = 'BULLISH'
DIRECTION_BEARISH = 'BEARISH'
DIRECTION_NEUTRAL = 'NEUTRAL'

ANATOMY_STATE_OK = 'OK'
ANATOMY_STATE_ZERO_RANGE = 'ZERO_RANGE'
ANATOMY_STATE_MALFORMED = 'MALFORMED'

DOJI_BODY_RATIO_MAX = 0.10
STRONG_BODY_RATIO_MIN = 0.60
LONG_WICK_RATIO_MIN = 0.50
REJECTION_WICK_RATIO_MIN = 0.60
REJECTION_BODY_RATIO_MAX = 0.30
MARUBOZU_BODY_RATIO_MIN = 0.90
MARUBOZU_WICK_RATIO_MAX = 0.05
HAMMER_WICK_TO_BODY_MIN = 2.0
HAMMER_OPPOSITE_WICK_TO_BODY_MAX = 1.0

TAG_DOJI_LIKE = 'DOJI_LIKE'
TAG_STRONG_BULLISH_BODY = 'STRONG_BULLISH_BODY'
TAG_STRONG_BEARISH_BODY = 'STRONG_BEARISH_BODY'
TAG_UPPER_REJECTION = 'UPPER_REJECTION'
TAG_LOWER_REJECTION = 'LOWER_REJECTION'
TAG_HAMMER_LIKE = 'HAMMER_LIKE'
TAG_SHOOTING_STAR_LIKE = 'SHOOTING_STAR_LIKE'
TAG_MARUBOZU_LIKE = 'MARUBOZU_LIKE'
TAG_LONG_UPPER_WICK = 'LONG_UPPER_WICK'
TAG_LONG_LOWER_WICK = 'LONG_LOWER_WICK'

SHAPE_TAG_ORDER = (
    TAG_DOJI_LIKE,
    TAG_STRONG_BULLISH_BODY,
    TAG_STRONG_BEARISH_BODY,
    TAG_UPPER_REJECTION,
    TAG_LOWER_REJECTION,
    TAG_HAMMER_LIKE,
    TAG_SHOOTING_STAR_LIKE,
    TAG_MARUBOZU_LIKE,
    TAG_LONG_UPPER_WICK,
    TAG_LONG_LOWER_WICK,
)

ANATOMY_KEYS = (
    'schema_version',
    'open',
    'high',
    'low',
    'close',
    'volume',
    'direction',
    'anatomy_state',
    'range',
    'body',
    'upper_wick',
    'lower_wick',
    'body_ratio',
    'upper_wick_ratio',
    'lower_wick_ratio',
    'open_position',
    'close_position',
    'shape_tags',
)


class _AnatomyError(ValueError):
    """Internal fail-closed parse/geometry error. Not part of the public API."""


def _finite_number(value: Any, *, field: str, required: bool) -> Optional[float]:
    if value is None or value == '':
        if required:
            raise _AnatomyError(f'{field} is required')
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _AnatomyError(f'{field} must be numeric')
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise _AnatomyError(f'{field} must be finite')
    return number


def _optional_echo(value: Any) -> Optional[float]:
    try:
        return _finite_number(value, field='echo', required=False)
    except _AnatomyError:
        return None


def _envelope(
    *,
    open_: Optional[float],
    high: Optional[float],
    low: Optional[float],
    close: Optional[float],
    volume: Optional[float],
    direction: Optional[str],
    anatomy_state: str,
    range_value: Optional[float],
    body: Optional[float],
    upper_wick: Optional[float],
    lower_wick: Optional[float],
    body_ratio: Optional[float],
    upper_wick_ratio: Optional[float],
    lower_wick_ratio: Optional[float],
    open_position: Optional[float],
    close_position: Optional[float],
    shape_tags: list[str],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
        'direction': direction,
        'anatomy_state': anatomy_state,
        'range': range_value,
        'body': body,
        'upper_wick': upper_wick,
        'lower_wick': lower_wick,
        'body_ratio': body_ratio,
        'upper_wick_ratio': upper_wick_ratio,
        'lower_wick_ratio': lower_wick_ratio,
        'open_position': open_position,
        'close_position': close_position,
        'shape_tags': list(shape_tags),
    }


def _malformed(candle: Any) -> dict[str, Any]:
    if not isinstance(candle, dict):
        return _envelope(
            open_=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            direction=None,
            anatomy_state=ANATOMY_STATE_MALFORMED,
            range_value=None,
            body=None,
            upper_wick=None,
            lower_wick=None,
            body_ratio=None,
            upper_wick_ratio=None,
            lower_wick_ratio=None,
            open_position=None,
            close_position=None,
            shape_tags=[],
        )
    return _envelope(
        open_=_optional_echo(candle.get('open')),
        high=_optional_echo(candle.get('high')),
        low=_optional_echo(candle.get('low')),
        close=_optional_echo(candle.get('close')),
        volume=_optional_echo(candle.get('volume')),
        direction=None,
        anatomy_state=ANATOMY_STATE_MALFORMED,
        range_value=None,
        body=None,
        upper_wick=None,
        lower_wick=None,
        body_ratio=None,
        upper_wick_ratio=None,
        lower_wick_ratio=None,
        open_position=None,
        close_position=None,
        shape_tags=[],
    )


def _shape_tags(
    *,
    direction: str,
    body: float,
    upper_wick: float,
    lower_wick: float,
    body_ratio: float,
    upper_wick_ratio: float,
    lower_wick_ratio: float,
) -> list[str]:
    tags: list[str] = []
    if body_ratio <= DOJI_BODY_RATIO_MAX:
        tags.append(TAG_DOJI_LIKE)
    if direction == DIRECTION_BULLISH and body_ratio >= STRONG_BODY_RATIO_MIN:
        tags.append(TAG_STRONG_BULLISH_BODY)
    if direction == DIRECTION_BEARISH and body_ratio >= STRONG_BODY_RATIO_MIN:
        tags.append(TAG_STRONG_BEARISH_BODY)
    if upper_wick_ratio >= REJECTION_WICK_RATIO_MIN and body_ratio <= REJECTION_BODY_RATIO_MAX:
        tags.append(TAG_UPPER_REJECTION)
    if lower_wick_ratio >= REJECTION_WICK_RATIO_MIN and body_ratio <= REJECTION_BODY_RATIO_MAX:
        tags.append(TAG_LOWER_REJECTION)
    if body > 0 and lower_wick >= body * HAMMER_WICK_TO_BODY_MIN and upper_wick <= body * HAMMER_OPPOSITE_WICK_TO_BODY_MAX:
        tags.append(TAG_HAMMER_LIKE)
    if body > 0 and upper_wick >= body * HAMMER_WICK_TO_BODY_MIN and lower_wick <= body * HAMMER_OPPOSITE_WICK_TO_BODY_MAX:
        tags.append(TAG_SHOOTING_STAR_LIKE)
    if (
        body_ratio >= MARUBOZU_BODY_RATIO_MIN
        and upper_wick_ratio <= MARUBOZU_WICK_RATIO_MAX
        and lower_wick_ratio <= MARUBOZU_WICK_RATIO_MAX
    ):
        tags.append(TAG_MARUBOZU_LIKE)
    if upper_wick_ratio >= LONG_WICK_RATIO_MIN:
        tags.append(TAG_LONG_UPPER_WICK)
    if lower_wick_ratio >= LONG_WICK_RATIO_MIN:
        tags.append(TAG_LONG_LOWER_WICK)
    order = {name: index for index, name in enumerate(SHAPE_TAG_ORDER)}
    return sorted(tags, key=lambda name: order[name])


def analyze_candle(candle: dict) -> dict:
    """Project geometric anatomy for one already-loaded OHLCV candle."""
    if not isinstance(candle, dict):
        return _malformed(candle)
    try:
        open_ = _finite_number(candle.get('open'), field='open', required=True)
        high = _finite_number(candle.get('high'), field='high', required=True)
        low = _finite_number(candle.get('low'), field='low', required=True)
        close = _finite_number(candle.get('close'), field='close', required=True)
        volume = _finite_number(candle.get('volume'), field='volume', required=False)
        if volume is not None and volume < 0:
            raise _AnatomyError('volume must be non-negative')
        if high < low or high < open_ or high < close or low > open_ or low > close:
            raise _AnatomyError('OHLC geometry is invalid')
    except _AnatomyError:
        return _malformed(candle)

    range_value = high - low
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    if close > open_:
        direction = DIRECTION_BULLISH
    elif close < open_:
        direction = DIRECTION_BEARISH
    else:
        direction = DIRECTION_NEUTRAL

    if range_value == 0:
        return _envelope(
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            direction=DIRECTION_NEUTRAL,
            anatomy_state=ANATOMY_STATE_ZERO_RANGE,
            range_value=0.0,
            body=0.0,
            upper_wick=0.0,
            lower_wick=0.0,
            body_ratio=None,
            upper_wick_ratio=None,
            lower_wick_ratio=None,
            open_position=None,
            close_position=None,
            shape_tags=[],
        )

    body_ratio = body / range_value
    upper_wick_ratio = upper_wick / range_value
    lower_wick_ratio = lower_wick / range_value
    open_position = (open_ - low) / range_value
    close_position = (close - low) / range_value
    return _envelope(
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        direction=direction,
        anatomy_state=ANATOMY_STATE_OK,
        range_value=range_value,
        body=body,
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        body_ratio=body_ratio,
        upper_wick_ratio=upper_wick_ratio,
        lower_wick_ratio=lower_wick_ratio,
        open_position=open_position,
        close_position=close_position,
        shape_tags=_shape_tags(
            direction=direction,
            body=body,
            upper_wick=upper_wick,
            lower_wick=lower_wick,
            body_ratio=body_ratio,
            upper_wick_ratio=upper_wick_ratio,
            lower_wick_ratio=lower_wick_ratio,
        ),
    )
