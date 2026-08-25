"""AstraEdge 53B deterministic price-action structure facts.

Consumes an already-loaded chronological OHLC candle series. The projection
is pure and confirmation-aware: a span-2 pivot is unavailable until both
right-side candles exist.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.analysis.candle_anatomy import ANATOMY_STATE_MALFORMED, analyze_candle

SCHEMA_VERSION = '53B'

SWING_SPAN = 2
MIN_STRUCTURE_CANDLES = 5

STRUCTURE_STATE_OK = 'OK'
STRUCTURE_STATE_INSUFFICIENT = 'INSUFFICIENT_CANDLES'
STRUCTURE_STATE_MALFORMED = 'MALFORMED'

SWING_KIND_HIGH = 'HIGH'
SWING_KIND_LOW = 'LOW'
SWING_KIND_ORDER = (SWING_KIND_HIGH, SWING_KIND_LOW)

RELATION_FIRST_HIGH = 'FIRST_HIGH'
RELATION_HIGHER_HIGH = 'HIGHER_HIGH'
RELATION_LOWER_HIGH = 'LOWER_HIGH'
RELATION_EQUAL_HIGH = 'EQUAL_HIGH'
RELATION_FIRST_LOW = 'FIRST_LOW'
RELATION_HIGHER_LOW = 'HIGHER_LOW'
RELATION_LOWER_LOW = 'LOWER_LOW'
RELATION_EQUAL_LOW = 'EQUAL_LOW'

STRUCTURE_BIAS_BULLISH = 'BULLISH'
STRUCTURE_BIAS_BEARISH = 'BEARISH'
STRUCTURE_BIAS_MIXED = 'MIXED'
STRUCTURE_BIAS_UNDEFINED = 'UNDEFINED'

DIRECTION_ABOVE = 'ABOVE'
DIRECTION_BELOW = 'BELOW'

TAG_BREAK_ABOVE_SWING_HIGH = 'BREAK_ABOVE_SWING_HIGH'
TAG_BREAK_BELOW_SWING_LOW = 'BREAK_BELOW_SWING_LOW'
TAG_BULLISH_BOS_LIKE = 'BULLISH_BOS_LIKE'
TAG_BEARISH_BOS_LIKE = 'BEARISH_BOS_LIKE'
TAG_BULLISH_CHOCH_LIKE = 'BULLISH_CHOCH_LIKE'
TAG_BEARISH_CHOCH_LIKE = 'BEARISH_CHOCH_LIKE'

EVENT_TAG_ORDER = (
    TAG_BREAK_ABOVE_SWING_HIGH,
    TAG_BREAK_BELOW_SWING_LOW,
    TAG_BULLISH_BOS_LIKE,
    TAG_BEARISH_BOS_LIKE,
    TAG_BULLISH_CHOCH_LIKE,
    TAG_BEARISH_CHOCH_LIKE,
)

STRUCTURE_KEYS = (
    'schema_version',
    'structure_state',
    'candle_count',
    'swing_span',
    'structure_bias',
    'swing_points',
    'break_events',
    'candle_anatomy',
)

SWING_KEYS = (
    'swing_id',
    'index',
    'kind',
    'price',
    'confirmed_at_index',
    'relation',
)

BREAK_EVENT_KEYS = (
    'index',
    'reference_swing_id',
    'reference_swing_index',
    'reference_price',
    'close',
    'direction',
    'structure_bias_before',
    'event_tags',
)


def _ordered_event_tags(tags: list[str]) -> list[str]:
    rank = {name: index for index, name in enumerate(EVENT_TAG_ORDER)}
    unique = {name for name in tags if name in rank}
    return sorted(unique, key=lambda name: rank[name])


def _envelope(
    *,
    structure_state: str,
    candle_count: int,
    structure_bias: str,
    swing_points: list[dict[str, Any]],
    break_events: list[dict[str, Any]],
    candle_anatomy: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'structure_state': structure_state,
        'candle_count': candle_count,
        'swing_span': SWING_SPAN,
        'structure_bias': structure_bias,
        'swing_points': list(swing_points),
        'break_events': list(break_events),
        'candle_anatomy': list(candle_anatomy),
    }


def _high_relation(price: float, previous: Optional[float]) -> str:
    if previous is None:
        return RELATION_FIRST_HIGH
    if price > previous:
        return RELATION_HIGHER_HIGH
    if price < previous:
        return RELATION_LOWER_HIGH
    return RELATION_EQUAL_HIGH


def _low_relation(price: float, previous: Optional[float]) -> str:
    if previous is None:
        return RELATION_FIRST_LOW
    if price > previous:
        return RELATION_HIGHER_LOW
    if price < previous:
        return RELATION_LOWER_LOW
    return RELATION_EQUAL_LOW


def _confirmed_swings(anatomy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    swings: list[dict[str, Any]] = []
    previous_high: Optional[float] = None
    previous_low: Optional[float] = None

    for index in range(SWING_SPAN, len(anatomy) - SWING_SPAN):
        row = anatomy[index]
        neighbors = (
            anatomy[index - 2],
            anatomy[index - 1],
            anatomy[index + 1],
            anatomy[index + 2],
        )
        is_high = all(row['high'] > other['high'] for other in neighbors)
        is_low = all(row['low'] < other['low'] for other in neighbors)

        for kind in SWING_KIND_ORDER:
            if kind == SWING_KIND_HIGH and is_high:
                price = row['high']
                relation = _high_relation(price, previous_high)
                previous_high = price
            elif kind == SWING_KIND_LOW and is_low:
                price = row['low']
                relation = _low_relation(price, previous_low)
                previous_low = price
            else:
                continue
            swings.append({
                'swing_id': f'{kind}:{index}',
                'index': index,
                'kind': kind,
                'price': price,
                'confirmed_at_index': index + SWING_SPAN,
                'relation': relation,
            })
    return swings


def _structure_bias(swings: list[dict[str, Any]]) -> str:
    highs = [row for row in swings if row['kind'] == SWING_KIND_HIGH]
    lows = [row for row in swings if row['kind'] == SWING_KIND_LOW]
    if len(highs) < 2 or len(lows) < 2:
        return STRUCTURE_BIAS_UNDEFINED

    high_relation = highs[-1]['relation']
    low_relation = lows[-1]['relation']
    if high_relation == RELATION_HIGHER_HIGH and low_relation == RELATION_HIGHER_LOW:
        return STRUCTURE_BIAS_BULLISH
    if high_relation == RELATION_LOWER_HIGH and low_relation == RELATION_LOWER_LOW:
        return STRUCTURE_BIAS_BEARISH
    return STRUCTURE_BIAS_MIXED


def _latest_unbroken(
    swings: list[dict[str, Any]],
    *,
    kind: str,
    index: int,
    broken_ids: set[str],
) -> Optional[dict[str, Any]]:
    eligible = [
        row for row in swings
        if row['kind'] == kind
        and row['confirmed_at_index'] <= index
        and row['swing_id'] not in broken_ids
    ]
    return eligible[-1] if eligible else None


def _break_tags(direction: str, bias: str) -> list[str]:
    if direction == DIRECTION_ABOVE:
        tags = [TAG_BREAK_ABOVE_SWING_HIGH]
        if bias == STRUCTURE_BIAS_BULLISH:
            tags.append(TAG_BULLISH_BOS_LIKE)
        elif bias == STRUCTURE_BIAS_BEARISH:
            tags.append(TAG_BULLISH_CHOCH_LIKE)
        return _ordered_event_tags(tags)

    tags = [TAG_BREAK_BELOW_SWING_LOW]
    if bias == STRUCTURE_BIAS_BEARISH:
        tags.append(TAG_BEARISH_BOS_LIKE)
    elif bias == STRUCTURE_BIAS_BULLISH:
        tags.append(TAG_BEARISH_CHOCH_LIKE)
    return _ordered_event_tags(tags)


def _break_event(
    *,
    index: int,
    reference: dict[str, Any],
    close: float,
    direction: str,
    bias: str,
) -> dict[str, Any]:
    return {
        'index': index,
        'reference_swing_id': reference['swing_id'],
        'reference_swing_index': reference['index'],
        'reference_price': reference['price'],
        'close': close,
        'direction': direction,
        'structure_bias_before': bias,
        'event_tags': _break_tags(direction, bias),
    }


def _break_events(
    anatomy: list[dict[str, Any]],
    swings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    broken_highs: set[str] = set()
    broken_lows: set[str] = set()

    for index in range(1, len(anatomy)):
        available = [row for row in swings if row['confirmed_at_index'] <= index]
        bias = _structure_bias(available)
        previous_close = anatomy[index - 1]['close']
        current_close = anatomy[index]['close']

        high = _latest_unbroken(
            swings,
            kind=SWING_KIND_HIGH,
            index=index,
            broken_ids=broken_highs,
        )
        if (
            high is not None
            and current_close > high['price']
            and previous_close <= high['price']
        ):
            events.append(_break_event(
                index=index,
                reference=high,
                close=current_close,
                direction=DIRECTION_ABOVE,
                bias=bias,
            ))
            broken_highs.add(high['swing_id'])

        low = _latest_unbroken(
            swings,
            kind=SWING_KIND_LOW,
            index=index,
            broken_ids=broken_lows,
        )
        if (
            low is not None
            and current_close < low['price']
            and previous_close >= low['price']
        ):
            events.append(_break_event(
                index=index,
                reference=low,
                close=current_close,
                direction=DIRECTION_BELOW,
                bias=bias,
            ))
            broken_lows.add(low['swing_id'])
    return events


def analyze_price_action_structure(candles: list[dict]) -> dict:
    """Project confirmed swings, structure bias, and close-break facts."""
    if not isinstance(candles, list):
        return _envelope(
            structure_state=STRUCTURE_STATE_MALFORMED,
            candle_count=0,
            structure_bias=STRUCTURE_BIAS_UNDEFINED,
            swing_points=[],
            break_events=[],
            candle_anatomy=[],
        )

    count = len(candles)
    if count < MIN_STRUCTURE_CANDLES:
        return _envelope(
            structure_state=STRUCTURE_STATE_INSUFFICIENT,
            candle_count=count,
            structure_bias=STRUCTURE_BIAS_UNDEFINED,
            swing_points=[],
            break_events=[],
            candle_anatomy=[],
        )

    anatomy = [analyze_candle(row) for row in candles]
    if any(row.get('anatomy_state') == ANATOMY_STATE_MALFORMED for row in anatomy):
        return _envelope(
            structure_state=STRUCTURE_STATE_MALFORMED,
            candle_count=count,
            structure_bias=STRUCTURE_BIAS_UNDEFINED,
            swing_points=[],
            break_events=[],
            candle_anatomy=anatomy,
        )

    swings = _confirmed_swings(anatomy)
    return _envelope(
        structure_state=STRUCTURE_STATE_OK,
        candle_count=count,
        structure_bias=_structure_bias(swings),
        swing_points=swings,
        break_events=_break_events(anatomy, swings),
        candle_anatomy=anatomy,
    )
