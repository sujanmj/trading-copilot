"""
AstraEdge 53A2 — deterministic multi-candle candlestick-pattern grammar.

Pattern facts only. Consumes 53A analyze_candle. No trade interpretation.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.analysis.candle_anatomy import (
    ANATOMY_STATE_MALFORMED,
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    DIRECTION_NEUTRAL,
    analyze_candle,
)

SCHEMA_VERSION = '53A2'

PATTERN_STATE_OK = 'OK'
PATTERN_STATE_INSUFFICIENT = 'INSUFFICIENT_CANDLES'
PATTERN_STATE_MALFORMED = 'MALFORMED'
PATTERN_STATE_UNSUPPORTED_WINDOW = 'UNSUPPORTED_WINDOW'

TWEEZER_LEVEL_TOLERANCE_RATIO = 0.05
STAR_SMALL_BODY_RATIO_MAX = 0.30
STAR_OUTER_BODY_RATIO_MIN = 0.50
SOLDIER_BODY_RATIO_MIN = 0.50

TAG_BULLISH_ENGULFING = 'BULLISH_ENGULFING'
TAG_BEARISH_ENGULFING = 'BEARISH_ENGULFING'
TAG_BULLISH_HARAMI = 'BULLISH_HARAMI'
TAG_BEARISH_HARAMI = 'BEARISH_HARAMI'
TAG_PIERCING_LINE_LIKE = 'PIERCING_LINE_LIKE'
TAG_DARK_CLOUD_COVER_LIKE = 'DARK_CLOUD_COVER_LIKE'
TAG_INSIDE_BAR = 'INSIDE_BAR'
TAG_OUTSIDE_BAR = 'OUTSIDE_BAR'
TAG_TWEEZER_TOP_LIKE = 'TWEEZER_TOP_LIKE'
TAG_TWEEZER_BOTTOM_LIKE = 'TWEEZER_BOTTOM_LIKE'
TAG_MORNING_STAR_LIKE = 'MORNING_STAR_LIKE'
TAG_EVENING_STAR_LIKE = 'EVENING_STAR_LIKE'
TAG_THREE_WHITE_SOLDIERS_LIKE = 'THREE_WHITE_SOLDIERS_LIKE'
TAG_THREE_BLACK_CROWS_LIKE = 'THREE_BLACK_CROWS_LIKE'

PATTERN_TAG_ORDER = (
    TAG_BULLISH_ENGULFING,
    TAG_BEARISH_ENGULFING,
    TAG_BULLISH_HARAMI,
    TAG_BEARISH_HARAMI,
    TAG_PIERCING_LINE_LIKE,
    TAG_DARK_CLOUD_COVER_LIKE,
    TAG_INSIDE_BAR,
    TAG_OUTSIDE_BAR,
    TAG_TWEEZER_TOP_LIKE,
    TAG_TWEEZER_BOTTOM_LIKE,
    TAG_MORNING_STAR_LIKE,
    TAG_EVENING_STAR_LIKE,
    TAG_THREE_WHITE_SOLDIERS_LIKE,
    TAG_THREE_BLACK_CROWS_LIKE,
)

PATTERN_KEYS = (
    'schema_version',
    'pattern_state',
    'candle_count',
    'pattern_tags',
    'candle_anatomy',
)


def _ordered_tags(tags: list[str]) -> list[str]:
    rank = {name: index for index, name in enumerate(PATTERN_TAG_ORDER)}
    unique = {name for name in tags if name in rank}
    return sorted(unique, key=lambda name: rank[name])


def _envelope(
    *,
    pattern_state: str,
    candle_count: int,
    pattern_tags: list[str],
    candle_anatomy: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'pattern_state': pattern_state,
        'candle_count': candle_count,
        'pattern_tags': _ordered_tags(pattern_tags),
        'candle_anatomy': list(candle_anatomy),
    }


def _body_low(row: dict[str, Any]) -> float:
    return min(row['open'], row['close'])


def _body_high(row: dict[str, Any]) -> float:
    return max(row['open'], row['close'])


def _midpoint(row: dict[str, Any]) -> float:
    return (row['open'] + row['close']) / 2.0


def _open_inside_body(open_value: float, container: dict[str, Any]) -> bool:
    return _body_low(container) <= open_value <= _body_high(container)


def _fully_covers_body(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    return (
        current['body'] > 0
        and previous['body'] > 0
        and _body_low(current) <= _body_low(previous)
        and _body_high(current) >= _body_high(previous)
        and (
            _body_low(current) < _body_low(previous)
            or _body_high(current) > _body_high(previous)
        )
    )


def _pair_tags(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    prev_dir = previous['direction']
    curr_dir = current['direction']
    prev_body = previous['body']
    curr_body = current['body']

    if (
        prev_dir == DIRECTION_BEARISH
        and curr_dir == DIRECTION_BULLISH
        and _fully_covers_body(current, previous)
    ):
        tags.append(TAG_BULLISH_ENGULFING)
    if (
        prev_dir == DIRECTION_BULLISH
        and curr_dir == DIRECTION_BEARISH
        and _fully_covers_body(current, previous)
    ):
        tags.append(TAG_BEARISH_ENGULFING)

    if (
        prev_dir == DIRECTION_BEARISH
        and curr_dir == DIRECTION_BULLISH
        and prev_body > 0
        and curr_body > 0
        and curr_body < prev_body
        and _body_low(current) >= _body_low(previous)
        and _body_high(current) <= _body_high(previous)
    ):
        tags.append(TAG_BULLISH_HARAMI)
    if (
        prev_dir == DIRECTION_BULLISH
        and curr_dir == DIRECTION_BEARISH
        and prev_body > 0
        and curr_body > 0
        and curr_body < prev_body
        and _body_low(current) >= _body_low(previous)
        and _body_high(current) <= _body_high(previous)
    ):
        tags.append(TAG_BEARISH_HARAMI)

    if (
        prev_dir == DIRECTION_BEARISH
        and curr_dir == DIRECTION_BULLISH
        and prev_body > 0
        and curr_body > 0
        and current['close'] > _midpoint(previous)
        and current['close'] < previous['open']
        and not _fully_covers_body(current, previous)
    ):
        tags.append(TAG_PIERCING_LINE_LIKE)
    if (
        prev_dir == DIRECTION_BULLISH
        and curr_dir == DIRECTION_BEARISH
        and prev_body > 0
        and curr_body > 0
        and current['close'] < _midpoint(previous)
        and current['close'] > previous['open']
        and not _fully_covers_body(current, previous)
    ):
        tags.append(TAG_DARK_CLOUD_COVER_LIKE)

    if (
        current['high'] <= previous['high']
        and current['low'] >= previous['low']
        and (current['high'] < previous['high'] or current['low'] > previous['low'])
    ):
        tags.append(TAG_INSIDE_BAR)
    if (
        current['high'] >= previous['high']
        and current['low'] <= previous['low']
        and (current['high'] > previous['high'] or current['low'] < previous['low'])
    ):
        tags.append(TAG_OUTSIDE_BAR)

    larger_range = max(previous['range'], current['range'])
    tolerance = TWEEZER_LEVEL_TOLERANCE_RATIO * larger_range
    opposite = (
        {prev_dir, curr_dir} == {DIRECTION_BULLISH, DIRECTION_BEARISH}
        and DIRECTION_NEUTRAL not in {prev_dir, curr_dir}
    )
    if opposite and abs(current['high'] - previous['high']) <= tolerance:
        tags.append(TAG_TWEEZER_TOP_LIKE)
    if opposite and abs(current['low'] - previous['low']) <= tolerance:
        tags.append(TAG_TWEEZER_BOTTOM_LIKE)
    return tags


def _ratio(row: dict[str, Any]) -> Optional[float]:
    value = row.get('body_ratio')
    if value is None:
        return None
    return value


def _triple_tags(first: dict[str, Any], second: dict[str, Any], third: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    r1 = _ratio(first)
    r2 = _ratio(second)
    r3 = _ratio(third)
    if (
        r1 is not None
        and r2 is not None
        and r3 is not None
        and first['direction'] == DIRECTION_BEARISH
        and r1 >= STAR_OUTER_BODY_RATIO_MIN
        and r2 <= STAR_SMALL_BODY_RATIO_MAX
        and third['direction'] == DIRECTION_BULLISH
        and r3 >= STAR_OUTER_BODY_RATIO_MIN
        and third['close'] > _midpoint(first)
    ):
        tags.append(TAG_MORNING_STAR_LIKE)
    if (
        r1 is not None
        and r2 is not None
        and r3 is not None
        and first['direction'] == DIRECTION_BULLISH
        and r1 >= STAR_OUTER_BODY_RATIO_MIN
        and r2 <= STAR_SMALL_BODY_RATIO_MAX
        and third['direction'] == DIRECTION_BEARISH
        and r3 >= STAR_OUTER_BODY_RATIO_MIN
        and third['close'] < _midpoint(first)
    ):
        tags.append(TAG_EVENING_STAR_LIKE)

    if (
        r1 is not None
        and r2 is not None
        and r3 is not None
        and first['direction'] == DIRECTION_BULLISH
        and second['direction'] == DIRECTION_BULLISH
        and third['direction'] == DIRECTION_BULLISH
        and r1 >= SOLDIER_BODY_RATIO_MIN
        and r2 >= SOLDIER_BODY_RATIO_MIN
        and r3 >= SOLDIER_BODY_RATIO_MIN
        and second['close'] > first['close']
        and third['close'] > second['close']
        and _open_inside_body(second['open'], first)
        and _open_inside_body(third['open'], second)
    ):
        tags.append(TAG_THREE_WHITE_SOLDIERS_LIKE)
    if (
        r1 is not None
        and r2 is not None
        and r3 is not None
        and first['direction'] == DIRECTION_BEARISH
        and second['direction'] == DIRECTION_BEARISH
        and third['direction'] == DIRECTION_BEARISH
        and r1 >= SOLDIER_BODY_RATIO_MIN
        and r2 >= SOLDIER_BODY_RATIO_MIN
        and r3 >= SOLDIER_BODY_RATIO_MIN
        and second['close'] < first['close']
        and third['close'] < second['close']
        and _open_inside_body(second['open'], first)
        and _open_inside_body(third['open'], second)
    ):
        tags.append(TAG_THREE_BLACK_CROWS_LIKE)
    return tags


def analyze_candlestick_patterns(candles: list[dict]) -> dict:
    """Project geometric multi-candle pattern tags for a 2- or 3-candle window."""
    if not isinstance(candles, list):
        return _envelope(
            pattern_state=PATTERN_STATE_MALFORMED,
            candle_count=0,
            pattern_tags=[],
            candle_anatomy=[],
        )
    count = len(candles)
    if count < 2:
        return _envelope(
            pattern_state=PATTERN_STATE_INSUFFICIENT,
            candle_count=count,
            pattern_tags=[],
            candle_anatomy=[],
        )
    if count > 3:
        return _envelope(
            pattern_state=PATTERN_STATE_UNSUPPORTED_WINDOW,
            candle_count=count,
            pattern_tags=[],
            candle_anatomy=[],
        )
    anatomy = [analyze_candle(row) for row in candles]
    if any(row.get('anatomy_state') == ANATOMY_STATE_MALFORMED for row in anatomy):
        return _envelope(
            pattern_state=PATTERN_STATE_MALFORMED,
            candle_count=count,
            pattern_tags=[],
            candle_anatomy=anatomy,
        )
    tags = _pair_tags(anatomy[-2], anatomy[-1])
    if count == 3:
        tags.extend(_triple_tags(anatomy[0], anatomy[1], anatomy[2]))
    return _envelope(
        pattern_state=PATTERN_STATE_OK,
        candle_count=count,
        pattern_tags=tags,
        candle_anatomy=anatomy,
    )
