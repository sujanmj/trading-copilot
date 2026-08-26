"""AstraEdge 53E2 deterministic caller-supplied premarket facts."""

from __future__ import annotations

import math
from typing import Any, Optional

from backend.analysis.multi_timeframe import analyze_multi_timeframe

SCHEMA_VERSION = '53E2'
PREMARKET_SCOPE = 'CALLER_SUPPLIED_PREMARKET_SNAPSHOT'

ANALYSIS_STATE_MALFORMED = 'MALFORMED'
UNDEFINED = 'UNDEFINED'

GAP_STATE_UP = 'GAP_UP'
GAP_STATE_DOWN = 'GAP_DOWN'
GAP_STATE_FLAT = 'FLAT'

OBSERVATION_ABOVE_PREVIOUS_CLOSE = 'ABOVE_PREVIOUS_CLOSE'
OBSERVATION_BELOW_PREVIOUS_CLOSE = 'BELOW_PREVIOUS_CLOSE'
OBSERVATION_AT_PREVIOUS_CLOSE = 'AT_PREVIOUS_CLOSE'

OBSERVATION_ABOVE_PREMARKET_REFERENCE = 'ABOVE_PREMARKET_REFERENCE'
OBSERVATION_BELOW_PREMARKET_REFERENCE = 'BELOW_PREMARKET_REFERENCE'
OBSERVATION_AT_PREMARKET_REFERENCE = 'AT_PREMARKET_REFERENCE'

OBSERVATION_ABOVE_PREMARKET_RANGE = 'ABOVE_PREMARKET_RANGE'
OBSERVATION_BELOW_PREMARKET_RANGE = 'BELOW_PREMARKET_RANGE'
OBSERVATION_AT_PREMARKET_RANGE = 'AT_PREMARKET_RANGE'
OBSERVATION_AT_PREMARKET_HIGH = 'AT_PREMARKET_HIGH'
OBSERVATION_AT_PREMARKET_LOW = 'AT_PREMARKET_LOW'
OBSERVATION_INSIDE_PREMARKET_RANGE = 'INSIDE_PREMARKET_RANGE'

REQUIRED_SCALAR_KEYS = (
    'previous_close',
    'premarket_reference_price',
    'premarket_high',
    'premarket_low',
    'observation_price',
)

VOLUME_STATE_KEYS = (
    'HIGH_VOLUME',
    'NORMAL_VOLUME',
    'LOW_VOLUME',
    UNDEFINED,
)

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'premarket_scope',
    'previous_close',
    'premarket_reference_price',
    'premarket_high',
    'premarket_low',
    'observation_price',
    'gap_points',
    'gap_ratio',
    'gap_state',
    'premarket_range_points',
    'premarket_range_ratio',
    'observation_vs_previous_close',
    'observation_vs_premarket_reference',
    'observation_vs_premarket_range',
    'timeframe_count',
    'structure_alignment',
    'structure_alignment_frame_count',
    'vwap_alignment',
    'vwap_alignment_frame_count',
    'volume_state_counts',
    'source_multi_timeframe',
)


def _zero_volume_state_counts() -> dict[str, int]:
    return {state: 0 for state in VOLUME_STATE_KEYS}


def _envelope(
    *,
    analysis_state: str,
    previous_close: Optional[float],
    premarket_reference_price: Optional[float],
    premarket_high: Optional[float],
    premarket_low: Optional[float],
    observation_price: Optional[float],
    gap_points: Optional[float],
    gap_ratio: Optional[float],
    gap_state: str,
    premarket_range_points: Optional[float],
    premarket_range_ratio: Optional[float],
    observation_vs_previous_close: str,
    observation_vs_premarket_reference: str,
    observation_vs_premarket_range: str,
    timeframe_count: int,
    structure_alignment: str,
    structure_alignment_frame_count: int,
    vwap_alignment: str,
    vwap_alignment_frame_count: int,
    volume_state_counts: dict[str, int],
    source_multi_timeframe: Optional[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'analysis_state': analysis_state,
        'premarket_scope': PREMARKET_SCOPE,
        'previous_close': previous_close,
        'premarket_reference_price': premarket_reference_price,
        'premarket_high': premarket_high,
        'premarket_low': premarket_low,
        'observation_price': observation_price,
        'gap_points': gap_points,
        'gap_ratio': gap_ratio,
        'gap_state': gap_state,
        'premarket_range_points': premarket_range_points,
        'premarket_range_ratio': premarket_range_ratio,
        'observation_vs_previous_close': observation_vs_previous_close,
        'observation_vs_premarket_reference': observation_vs_premarket_reference,
        'observation_vs_premarket_range': observation_vs_premarket_range,
        'timeframe_count': timeframe_count,
        'structure_alignment': structure_alignment,
        'structure_alignment_frame_count': structure_alignment_frame_count,
        'vwap_alignment': vwap_alignment,
        'vwap_alignment_frame_count': vwap_alignment_frame_count,
        'volume_state_counts': volume_state_counts,
        'source_multi_timeframe': source_multi_timeframe,
    }


def _malformed() -> dict[str, Any]:
    return _envelope(
        analysis_state=ANALYSIS_STATE_MALFORMED,
        previous_close=None,
        premarket_reference_price=None,
        premarket_high=None,
        premarket_low=None,
        observation_price=None,
        gap_points=None,
        gap_ratio=None,
        gap_state=UNDEFINED,
        premarket_range_points=None,
        premarket_range_ratio=None,
        observation_vs_previous_close=UNDEFINED,
        observation_vs_premarket_reference=UNDEFINED,
        observation_vs_premarket_range=UNDEFINED,
        timeframe_count=0,
        structure_alignment=UNDEFINED,
        structure_alignment_frame_count=0,
        vwap_alignment=UNDEFINED,
        vwap_alignment_frame_count=0,
        volume_state_counts=_zero_volume_state_counts(),
        source_multi_timeframe=None,
    )


def _valid_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def _gap_state(gap_points: float) -> str:
    if gap_points > 0:
        return GAP_STATE_UP
    if gap_points < 0:
        return GAP_STATE_DOWN
    return GAP_STATE_FLAT


def _relation(
    value: float,
    reference: float,
    *,
    above: str,
    below: str,
    at: str,
) -> str:
    if value > reference:
        return above
    if value < reference:
        return below
    return at


def _range_relation(observation: float, high: float, low: float) -> str:
    if observation > high:
        return OBSERVATION_ABOVE_PREMARKET_RANGE
    if observation < low:
        return OBSERVATION_BELOW_PREMARKET_RANGE
    if high == low and observation == high:
        return OBSERVATION_AT_PREMARKET_RANGE
    if observation == high:
        return OBSERVATION_AT_PREMARKET_HIGH
    if observation == low:
        return OBSERVATION_AT_PREMARKET_LOW
    return OBSERVATION_INSIDE_PREMARKET_RANGE


def analyze_premarket_structure(snapshot: dict) -> dict:
    """Project premarket scalar facts and one exact 53E source result."""
    if not isinstance(snapshot, dict):
        return _malformed()
    if any(key not in snapshot for key in (*REQUIRED_SCALAR_KEYS, 'frames')):
        return _malformed()
    if any(not _valid_number(snapshot[key]) for key in REQUIRED_SCALAR_KEYS):
        return _malformed()
    if not isinstance(snapshot['frames'], list):
        return _malformed()

    previous_close = snapshot['previous_close']
    reference = snapshot['premarket_reference_price']
    high = snapshot['premarket_high']
    low = snapshot['premarket_low']
    observation = snapshot['observation_price']
    if high < low or reference < low or reference > high:
        return _malformed()

    source = analyze_multi_timeframe(snapshot['frames'])
    gap_points = reference - previous_close
    range_points = high - low
    return _envelope(
        analysis_state=source['analysis_state'],
        previous_close=previous_close,
        premarket_reference_price=reference,
        premarket_high=high,
        premarket_low=low,
        observation_price=observation,
        gap_points=gap_points,
        gap_ratio=gap_points / abs(previous_close) if previous_close != 0 else None,
        gap_state=_gap_state(gap_points),
        premarket_range_points=range_points,
        premarket_range_ratio=(
            range_points / abs(previous_close)
            if previous_close != 0
            else None
        ),
        observation_vs_previous_close=_relation(
            observation,
            previous_close,
            above=OBSERVATION_ABOVE_PREVIOUS_CLOSE,
            below=OBSERVATION_BELOW_PREVIOUS_CLOSE,
            at=OBSERVATION_AT_PREVIOUS_CLOSE,
        ),
        observation_vs_premarket_reference=_relation(
            observation,
            reference,
            above=OBSERVATION_ABOVE_PREMARKET_REFERENCE,
            below=OBSERVATION_BELOW_PREMARKET_REFERENCE,
            at=OBSERVATION_AT_PREMARKET_REFERENCE,
        ),
        observation_vs_premarket_range=_range_relation(observation, high, low),
        timeframe_count=source['timeframe_count'],
        structure_alignment=source['structure_alignment'],
        structure_alignment_frame_count=source['structure_alignment_frame_count'],
        vwap_alignment=source['vwap_alignment'],
        vwap_alignment_frame_count=source['vwap_alignment_frame_count'],
        volume_state_counts=source['volume_state_counts'],
        source_multi_timeframe=source,
    )
