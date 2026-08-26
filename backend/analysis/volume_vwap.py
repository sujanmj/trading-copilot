"""AstraEdge 53D deterministic supplied-window volume and VWAP facts."""

from __future__ import annotations

import math
from typing import Any, Optional

from backend.analysis.candle_anatomy import ANATOMY_STATE_MALFORMED, analyze_candle

SCHEMA_VERSION = '53D'

MIN_VOLUME_VWAP_CANDLES = 1
VOLUME_LOOKBACK = 20
MIN_VOLUME_BASELINE_SAMPLES = 3
HIGH_VOLUME_RATIO_MIN = 1.50
LOW_VOLUME_RATIO_MAX = 0.50
VWAP_SCOPE = 'SUPPLIED_WINDOW'

ANALYSIS_STATE_OK = 'OK'
ANALYSIS_STATE_INSUFFICIENT = 'INSUFFICIENT_CANDLES'
ANALYSIS_STATE_MALFORMED = 'MALFORMED'
ANALYSIS_STATE_MISSING_VOLUME = 'MISSING_VOLUME'

VOLUME_STATE_HIGH = 'HIGH_VOLUME'
VOLUME_STATE_NORMAL = 'NORMAL_VOLUME'
VOLUME_STATE_LOW = 'LOW_VOLUME'
VOLUME_STATE_UNDEFINED = 'UNDEFINED'

VWAP_RELATION_ABOVE = 'ABOVE_VWAP'
VWAP_RELATION_BELOW = 'BELOW_VWAP'
VWAP_RELATION_AT = 'AT_VWAP'
VWAP_RELATION_UNDEFINED = 'UNDEFINED'

TAG_CROSS_ABOVE_VWAP = 'CROSS_ABOVE_VWAP'
TAG_CROSS_BELOW_VWAP = 'CROSS_BELOW_VWAP'
EVENT_TAG_ORDER = (TAG_CROSS_ABOVE_VWAP, TAG_CROSS_BELOW_VWAP)

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'candle_count',
    'vwap_scope',
    'vwap_anchor_index',
    'volume_lookback',
    'min_volume_baseline_samples',
    'high_volume_ratio_min',
    'low_volume_ratio_max',
    'latest_vwap',
    'latest_vwap_relation',
    'latest_volume_ratio',
    'latest_volume_state',
    'records',
    'candle_anatomy',
)

RECORD_KEYS = (
    'index',
    'volume',
    'baseline_volume',
    'baseline_sample_count',
    'volume_ratio',
    'volume_state',
    'typical_price',
    'cumulative_volume',
    'vwap',
    'close',
    'vwap_relation',
    'vwap_distance',
    'vwap_distance_ratio',
    'event_tags',
)


def _envelope(
    *,
    analysis_state: str,
    candle_count: int,
    vwap_anchor_index: Optional[int],
    latest_vwap: Optional[float],
    latest_vwap_relation: str,
    latest_volume_ratio: Optional[float],
    latest_volume_state: str,
    records: list[dict[str, Any]],
    candle_anatomy: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'analysis_state': analysis_state,
        'candle_count': candle_count,
        'vwap_scope': VWAP_SCOPE,
        'vwap_anchor_index': vwap_anchor_index,
        'volume_lookback': VOLUME_LOOKBACK,
        'min_volume_baseline_samples': MIN_VOLUME_BASELINE_SAMPLES,
        'high_volume_ratio_min': HIGH_VOLUME_RATIO_MIN,
        'low_volume_ratio_max': LOW_VOLUME_RATIO_MAX,
        'latest_vwap': latest_vwap,
        'latest_vwap_relation': latest_vwap_relation,
        'latest_volume_ratio': latest_volume_ratio,
        'latest_volume_state': latest_volume_state,
        'records': list(records),
        'candle_anatomy': list(candle_anatomy),
    }


def _non_ok(
    *,
    analysis_state: str,
    candle_count: int,
    vwap_anchor_index: Optional[int],
    candle_anatomy: list[dict[str, Any]],
) -> dict[str, Any]:
    return _envelope(
        analysis_state=analysis_state,
        candle_count=candle_count,
        vwap_anchor_index=vwap_anchor_index,
        latest_vwap=None,
        latest_vwap_relation=VWAP_RELATION_UNDEFINED,
        latest_volume_ratio=None,
        latest_volume_state=VOLUME_STATE_UNDEFINED,
        records=[],
        candle_anatomy=candle_anatomy,
    )


def _valid_volume(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and value >= 0
    )


def _volume_context(
    volumes: list[float],
    index: int,
) -> tuple[Optional[float], int, Optional[float], str]:
    previous = volumes[max(0, index - VOLUME_LOOKBACK):index]
    sample_count = len(previous)
    if sample_count < MIN_VOLUME_BASELINE_SAMPLES:
        return None, sample_count, None, VOLUME_STATE_UNDEFINED

    baseline = sum(previous) / sample_count
    if baseline == 0:
        return baseline, sample_count, None, VOLUME_STATE_UNDEFINED

    ratio = volumes[index] / baseline
    if ratio >= HIGH_VOLUME_RATIO_MIN:
        state = VOLUME_STATE_HIGH
    elif ratio <= LOW_VOLUME_RATIO_MAX:
        state = VOLUME_STATE_LOW
    else:
        state = VOLUME_STATE_NORMAL
    return baseline, sample_count, ratio, state


def _vwap_relation(close: float, vwap: Optional[float]) -> str:
    if vwap is None:
        return VWAP_RELATION_UNDEFINED
    if close > vwap:
        return VWAP_RELATION_ABOVE
    if close < vwap:
        return VWAP_RELATION_BELOW
    return VWAP_RELATION_AT


def _cross_tags(previous: str, current: str) -> list[str]:
    if previous in (VWAP_RELATION_BELOW, VWAP_RELATION_AT) and current == VWAP_RELATION_ABOVE:
        return [TAG_CROSS_ABOVE_VWAP]
    if previous in (VWAP_RELATION_ABOVE, VWAP_RELATION_AT) and current == VWAP_RELATION_BELOW:
        return [TAG_CROSS_BELOW_VWAP]
    return []


def _records(anatomy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    volumes = [row['volume'] for row in anatomy]
    records: list[dict[str, Any]] = []
    cumulative_weighted_value = 0.0
    cumulative_volume = 0.0
    previous_relation = VWAP_RELATION_UNDEFINED

    for index, row in enumerate(anatomy):
        volume = volumes[index]
        typical_price = (row['high'] + row['low'] + row['close']) / 3.0
        cumulative_weighted_value += typical_price * volume
        cumulative_volume += volume
        vwap = (
            cumulative_weighted_value / cumulative_volume
            if cumulative_volume > 0
            else None
        )
        relation = _vwap_relation(row['close'], vwap)
        baseline, sample_count, ratio, volume_state = _volume_context(volumes, index)

        if vwap is None:
            distance = None
            distance_ratio = None
        else:
            distance = row['close'] - vwap
            distance_ratio = distance / abs(vwap) if vwap != 0 else None

        event_tags = _cross_tags(previous_relation, relation)
        records.append({
            'index': index,
            'volume': volume,
            'baseline_volume': baseline,
            'baseline_sample_count': sample_count,
            'volume_ratio': ratio,
            'volume_state': volume_state,
            'typical_price': typical_price,
            'cumulative_volume': cumulative_volume,
            'vwap': vwap,
            'close': row['close'],
            'vwap_relation': relation,
            'vwap_distance': distance,
            'vwap_distance_ratio': distance_ratio,
            'event_tags': event_tags,
        })
        previous_relation = relation
    return records


def analyze_volume_vwap(candles: list[dict]) -> dict:
    """Project volume baselines and cumulative VWAP over supplied candles."""
    if not isinstance(candles, list):
        return _non_ok(
            analysis_state=ANALYSIS_STATE_MALFORMED,
            candle_count=0,
            vwap_anchor_index=None,
            candle_anatomy=[],
        )

    candle_count = len(candles)
    if candle_count < MIN_VOLUME_VWAP_CANDLES:
        return _non_ok(
            analysis_state=ANALYSIS_STATE_INSUFFICIENT,
            candle_count=candle_count,
            vwap_anchor_index=None,
            candle_anatomy=[],
        )

    anatomy = [analyze_candle(candle) for candle in candles]
    if any(row.get('anatomy_state') == ANATOMY_STATE_MALFORMED for row in anatomy):
        return _non_ok(
            analysis_state=ANALYSIS_STATE_MALFORMED,
            candle_count=candle_count,
            vwap_anchor_index=0,
            candle_anatomy=anatomy,
        )

    if any(row.get('volume') is None for row in anatomy):
        return _non_ok(
            analysis_state=ANALYSIS_STATE_MISSING_VOLUME,
            candle_count=candle_count,
            vwap_anchor_index=0,
            candle_anatomy=anatomy,
        )

    if any(not _valid_volume(row.get('volume')) for row in anatomy):
        return _non_ok(
            analysis_state=ANALYSIS_STATE_MALFORMED,
            candle_count=candle_count,
            vwap_anchor_index=0,
            candle_anatomy=anatomy,
        )

    records = _records(anatomy)
    latest = records[-1]
    return _envelope(
        analysis_state=ANALYSIS_STATE_OK,
        candle_count=candle_count,
        vwap_anchor_index=0,
        latest_vwap=latest['vwap'],
        latest_vwap_relation=latest['vwap_relation'],
        latest_volume_ratio=latest['volume_ratio'],
        latest_volume_state=latest['volume_state'],
        records=records,
        candle_anatomy=anatomy,
    )
