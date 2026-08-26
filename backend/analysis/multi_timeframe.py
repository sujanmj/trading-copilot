"""AstraEdge 53E deterministic caller-supplied multi-timeframe facts."""

from __future__ import annotations

from typing import Any, Optional

from backend.analysis.key_levels_supply_demand import analyze_key_levels
from backend.analysis.volume_vwap import analyze_volume_vwap

SCHEMA_VERSION = '53E'

MIN_TIMEFRAMES = 2
MIN_ALIGNMENT_FRAMES = 2
ALIGNMENT_SCOPE = 'CALLER_SUPPLIED_WINDOWS'

ANALYSIS_STATE_OK = 'OK'
ANALYSIS_STATE_PARTIAL = 'PARTIAL'
ANALYSIS_STATE_INSUFFICIENT = 'INSUFFICIENT_TIMEFRAMES'
ANALYSIS_STATE_MALFORMED = 'MALFORMED'

FRAME_STATE_OK = 'OK'
FRAME_STATE_PARTIAL = 'PARTIAL'

SOURCE_STATE_OK = 'OK'
UNDEFINED = 'UNDEFINED'
DIVERGENT = 'DIVERGENT'

STRUCTURE_BIAS_BULLISH = 'BULLISH'
STRUCTURE_BIAS_BEARISH = 'BEARISH'
STRUCTURE_BIAS_MIXED = 'MIXED'
STRUCTURE_BIAS_VALUES = (
    STRUCTURE_BIAS_BULLISH,
    STRUCTURE_BIAS_BEARISH,
    STRUCTURE_BIAS_MIXED,
)

STRUCTURE_ALIGNMENT_BY_BIAS = {
    STRUCTURE_BIAS_BULLISH: 'ALIGNED_BULLISH',
    STRUCTURE_BIAS_BEARISH: 'ALIGNED_BEARISH',
    STRUCTURE_BIAS_MIXED: 'ALIGNED_MIXED',
}

VWAP_RELATION_ABOVE = 'ABOVE_VWAP'
VWAP_RELATION_BELOW = 'BELOW_VWAP'
VWAP_RELATION_AT = 'AT_VWAP'
VWAP_RELATION_VALUES = (
    VWAP_RELATION_ABOVE,
    VWAP_RELATION_BELOW,
    VWAP_RELATION_AT,
)

VWAP_ALIGNMENT_BY_RELATION = {
    VWAP_RELATION_ABOVE: 'ALIGNED_ABOVE_VWAP',
    VWAP_RELATION_BELOW: 'ALIGNED_BELOW_VWAP',
    VWAP_RELATION_AT: 'ALIGNED_AT_VWAP',
}

VOLUME_STATE_HIGH = 'HIGH_VOLUME'
VOLUME_STATE_NORMAL = 'NORMAL_VOLUME'
VOLUME_STATE_LOW = 'LOW_VOLUME'
VOLUME_STATE_VALUES = (
    VOLUME_STATE_HIGH,
    VOLUME_STATE_NORMAL,
    VOLUME_STATE_LOW,
    UNDEFINED,
)

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'timeframe_count',
    'alignment_scope',
    'min_timeframes',
    'min_alignment_frames',
    'structure_alignment',
    'structure_alignment_frame_count',
    'vwap_alignment',
    'vwap_alignment_frame_count',
    'volume_state_counts',
    'frames',
)

FRAME_KEYS = (
    'timeframe',
    'candle_count',
    'frame_state',
    'structure_state',
    'structure_bias',
    'confirmed_swing_count',
    'break_event_count',
    'key_level_count',
    'level_group_count',
    'active_zone_count',
    'invalidated_zone_count',
    'volume_vwap_state',
    'latest_vwap',
    'latest_vwap_relation',
    'latest_volume_ratio',
    'latest_volume_state',
    'source_key_levels',
    'source_volume_vwap',
)


def _volume_state_counts() -> dict[str, int]:
    return {state: 0 for state in VOLUME_STATE_VALUES}


def _envelope(
    *,
    analysis_state: str,
    timeframe_count: int,
    structure_alignment: str,
    structure_alignment_frame_count: int,
    vwap_alignment: str,
    vwap_alignment_frame_count: int,
    volume_state_counts: dict[str, int],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'analysis_state': analysis_state,
        'timeframe_count': timeframe_count,
        'alignment_scope': ALIGNMENT_SCOPE,
        'min_timeframes': MIN_TIMEFRAMES,
        'min_alignment_frames': MIN_ALIGNMENT_FRAMES,
        'structure_alignment': structure_alignment,
        'structure_alignment_frame_count': structure_alignment_frame_count,
        'vwap_alignment': vwap_alignment,
        'vwap_alignment_frame_count': vwap_alignment_frame_count,
        'volume_state_counts': dict(volume_state_counts),
        'frames': list(frames),
    }


def _non_analyzed(analysis_state: str, timeframe_count: int) -> dict[str, Any]:
    return _envelope(
        analysis_state=analysis_state,
        timeframe_count=timeframe_count,
        structure_alignment=UNDEFINED,
        structure_alignment_frame_count=0,
        vwap_alignment=UNDEFINED,
        vwap_alignment_frame_count=0,
        volume_state_counts=_volume_state_counts(),
        frames=[],
    )


def _valid_frame_envelopes(frames: list[dict]) -> bool:
    labels: set[str] = set()
    for frame in frames:
        if not isinstance(frame, dict):
            return False
        if 'timeframe' not in frame or 'candles' not in frame:
            return False
        timeframe = frame['timeframe']
        if not isinstance(timeframe, str) or not timeframe.strip():
            return False
        normalized = timeframe.strip()
        if normalized in labels:
            return False
        labels.add(normalized)
        if not isinstance(frame['candles'], list):
            return False
    return True


def _source_structure_facts(
    source_key_levels: dict[str, Any],
) -> tuple[str, str, Optional[int], Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    structure_bias = source_key_levels['structure_bias']
    if source_key_levels['level_state'] != SOURCE_STATE_OK:
        source_structure = source_key_levels.get('source_structure')
        structure_state = (
            source_structure.get('structure_state', UNDEFINED)
            if isinstance(source_structure, dict)
            else UNDEFINED
        )
        return structure_state, structure_bias, None, None, None, None, None, None

    source_structure = source_key_levels['source_structure']
    zones = source_key_levels['zones']
    return (
        source_structure['structure_state'],
        structure_bias,
        len(source_structure['swing_points']),
        len(source_structure['break_events']),
        len(source_key_levels['key_levels']),
        len(source_key_levels['level_groups']),
        sum(1 for zone in zones if zone['zone_state'] == 'ACTIVE'),
        sum(1 for zone in zones if zone['zone_state'] == 'INVALIDATED'),
    )


def _frame_record(
    timeframe: str,
    candle_count: int,
    source_key_levels: dict[str, Any],
    source_volume_vwap: dict[str, Any],
) -> dict[str, Any]:
    (
        structure_state,
        structure_bias,
        confirmed_swing_count,
        break_event_count,
        key_level_count,
        level_group_count,
        active_zone_count,
        invalidated_zone_count,
    ) = _source_structure_facts(source_key_levels)

    volume_vwap_state = source_volume_vwap['analysis_state']
    frame_state = (
        FRAME_STATE_OK
        if source_key_levels['level_state'] == SOURCE_STATE_OK
        and volume_vwap_state == SOURCE_STATE_OK
        else FRAME_STATE_PARTIAL
    )
    return {
        'timeframe': timeframe,
        'candle_count': candle_count,
        'frame_state': frame_state,
        'structure_state': structure_state,
        'structure_bias': structure_bias,
        'confirmed_swing_count': confirmed_swing_count,
        'break_event_count': break_event_count,
        'key_level_count': key_level_count,
        'level_group_count': level_group_count,
        'active_zone_count': active_zone_count,
        'invalidated_zone_count': invalidated_zone_count,
        'volume_vwap_state': volume_vwap_state,
        'latest_vwap': source_volume_vwap['latest_vwap'],
        'latest_vwap_relation': source_volume_vwap['latest_vwap_relation'],
        'latest_volume_ratio': source_volume_vwap['latest_volume_ratio'],
        'latest_volume_state': source_volume_vwap['latest_volume_state'],
        'source_key_levels': source_key_levels,
        'source_volume_vwap': source_volume_vwap,
    }


def _alignment(values: list[str], aligned_values: dict[str, str]) -> tuple[str, int]:
    frame_count = len(values)
    if frame_count < MIN_ALIGNMENT_FRAMES:
        return UNDEFINED, frame_count
    first = values[0]
    if all(value == first for value in values):
        return aligned_values[first], frame_count
    return DIVERGENT, frame_count


def analyze_multi_timeframe(frames: list[dict]) -> dict:
    """Compare deterministic facts across caller-supplied candle windows."""
    if not isinstance(frames, list):
        return _non_analyzed(ANALYSIS_STATE_MALFORMED, 0)

    timeframe_count = len(frames)
    if timeframe_count < MIN_TIMEFRAMES:
        return _non_analyzed(ANALYSIS_STATE_INSUFFICIENT, timeframe_count)

    if not _valid_frame_envelopes(frames):
        return _non_analyzed(ANALYSIS_STATE_MALFORMED, timeframe_count)

    frame_records: list[dict[str, Any]] = []
    for frame in frames:
        candles = frame['candles']
        source_key_levels = analyze_key_levels(candles)
        source_volume_vwap = analyze_volume_vwap(candles)
        frame_records.append(_frame_record(
            frame['timeframe'],
            len(candles),
            source_key_levels,
            source_volume_vwap,
        ))

    usable_structure = [
        frame['structure_bias']
        for frame in frame_records
        if frame['source_key_levels']['level_state'] == SOURCE_STATE_OK
        and frame['structure_bias'] in STRUCTURE_BIAS_VALUES
    ]
    structure_alignment, structure_count = _alignment(
        usable_structure,
        STRUCTURE_ALIGNMENT_BY_BIAS,
    )

    usable_vwap = [
        frame['latest_vwap_relation']
        for frame in frame_records
        if frame['volume_vwap_state'] == SOURCE_STATE_OK
        and frame['latest_vwap_relation'] in VWAP_RELATION_VALUES
    ]
    vwap_alignment, vwap_count = _alignment(usable_vwap, VWAP_ALIGNMENT_BY_RELATION)

    volume_counts = _volume_state_counts()
    for frame in frame_records:
        state = frame['latest_volume_state']
        volume_counts[state if state in volume_counts else UNDEFINED] += 1

    analysis_state = (
        ANALYSIS_STATE_OK
        if all(frame['frame_state'] == FRAME_STATE_OK for frame in frame_records)
        else ANALYSIS_STATE_PARTIAL
    )
    return _envelope(
        analysis_state=analysis_state,
        timeframe_count=timeframe_count,
        structure_alignment=structure_alignment,
        structure_alignment_frame_count=structure_count,
        vwap_alignment=vwap_alignment,
        vwap_alignment_frame_count=vwap_count,
        volume_state_counts=volume_counts,
        frames=frame_records,
    )
