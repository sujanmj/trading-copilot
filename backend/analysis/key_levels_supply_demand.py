"""AstraEdge 53C deterministic key-level and zone facts.

Consumes the confirmation-aware 53B structure projection. This module adds
exact levels, anchored near-equal groups, and geometric zone lifecycle facts
without recalculating pivots or structural breaks.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.analysis.price_action_structure import (
    STRUCTURE_BIAS_UNDEFINED,
    STRUCTURE_STATE_MALFORMED,
    STRUCTURE_STATE_OK,
    SWING_KIND_HIGH,
    SWING_KIND_LOW,
    analyze_price_action_structure,
)

SCHEMA_VERSION = '53C'

MIN_LEVEL_CANDLES = 5
LEVEL_CLUSTER_TOLERANCE_RATIO = 0.0025
MIN_LEVEL_GROUP_MEMBERS = 2

LEVEL_STATE_OK = 'OK'
LEVEL_STATE_INSUFFICIENT = 'INSUFFICIENT_CANDLES'
LEVEL_STATE_MALFORMED = 'MALFORMED'

LEVEL_KIND_SWING_HIGH = 'SWING_HIGH_LEVEL'
LEVEL_KIND_SWING_LOW = 'SWING_LOW_LEVEL'

BREAK_STATE_UNBROKEN = 'UNBROKEN'
BREAK_STATE_BROKEN_ABOVE = 'BROKEN_ABOVE'
BREAK_STATE_BROKEN_BELOW = 'BROKEN_BELOW'

ZONE_KIND_SUPPLY_LIKE = 'SUPPLY_LIKE'
ZONE_KIND_DEMAND_LIKE = 'DEMAND_LIKE'

ZONE_STATE_ACTIVE = 'ACTIVE'
ZONE_STATE_INVALIDATED = 'INVALIDATED'

KIND_ORDER = (SWING_KIND_HIGH, SWING_KIND_LOW)

OUTPUT_KEYS = (
    'schema_version',
    'level_state',
    'candle_count',
    'cluster_tolerance_ratio',
    'structure_bias',
    'key_levels',
    'level_groups',
    'zones',
    'source_structure',
)

KEY_LEVEL_KEYS = (
    'level_id',
    'swing_id',
    'index',
    'kind',
    'level_kind',
    'price',
    'confirmed_at_index',
    'relation',
    'break_state',
    'broken_at_index',
)

LEVEL_GROUP_KEYS = (
    'group_id',
    'kind',
    'anchor_price',
    'representative_price',
    'member_count',
    'member_level_ids',
    'member_swing_ids',
    'first_confirmed_at_index',
    'last_confirmed_at_index',
)

ZONE_KEYS = (
    'zone_id',
    'swing_id',
    'index',
    'kind',
    'zone_kind',
    'zone_low',
    'zone_high',
    'zone_width',
    'confirmed_at_index',
    'zone_state',
    'invalidated_at_index',
)


def _envelope(
    *,
    level_state: str,
    candle_count: int,
    structure_bias: str,
    key_levels: list[dict[str, Any]],
    level_groups: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    source_structure: Optional[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'level_state': level_state,
        'candle_count': candle_count,
        'cluster_tolerance_ratio': LEVEL_CLUSTER_TOLERANCE_RATIO,
        'structure_bias': structure_bias,
        'key_levels': list(key_levels),
        'level_groups': list(level_groups),
        'zones': list(zones),
        'source_structure': source_structure,
    }


def _kind_rank(kind: str) -> int:
    return KIND_ORDER.index(kind)


def _ordered_swings(source_structure: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        source_structure['swing_points'],
        key=lambda row: (row['index'], _kind_rank(row['kind'])),
    )


def _key_levels(
    source_structure: dict[str, Any],
    swings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    breaks_by_swing: dict[str, dict[str, Any]] = {}
    for event in source_structure['break_events']:
        swing_id = event['reference_swing_id']
        if swing_id not in breaks_by_swing:
            breaks_by_swing[swing_id] = event

    levels: list[dict[str, Any]] = []
    for swing in swings:
        kind = swing['kind']
        event = breaks_by_swing.get(swing['swing_id'])
        if kind == SWING_KIND_HIGH:
            level_kind = LEVEL_KIND_SWING_HIGH
            break_state = BREAK_STATE_BROKEN_ABOVE if event else BREAK_STATE_UNBROKEN
        else:
            level_kind = LEVEL_KIND_SWING_LOW
            break_state = BREAK_STATE_BROKEN_BELOW if event else BREAK_STATE_UNBROKEN

        levels.append({
            'level_id': f'LEVEL:{kind}:{swing["index"]}',
            'swing_id': swing['swing_id'],
            'index': swing['index'],
            'kind': kind,
            'level_kind': level_kind,
            'price': swing['price'],
            'confirmed_at_index': swing['confirmed_at_index'],
            'relation': swing['relation'],
            'break_state': break_state,
            'broken_at_index': event['index'] if event else None,
        })
    return levels


def _normalized_difference(left: float, right: float) -> float:
    scale = max(abs(left), abs(right))
    if scale == 0:
        return 0.0 if left == right else float('inf')
    return abs(left - right) / scale


def _within_cluster_tolerance(left: float, right: float) -> bool:
    return _normalized_difference(left, right) <= LEVEL_CLUSTER_TOLERANCE_RATIO


def _level_groups(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups_by_kind: dict[str, list[dict[str, Any]]] = {
        SWING_KIND_HIGH: [],
        SWING_KIND_LOW: [],
    }
    counters = {SWING_KIND_HIGH: 0, SWING_KIND_LOW: 0}
    creation_order = 0

    for level in levels:
        kind = level['kind']
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        for group_index, group in enumerate(groups_by_kind[kind]):
            anchor = group['anchor_price']
            if _within_cluster_tolerance(level['price'], anchor):
                candidates.append((
                    _normalized_difference(level['price'], anchor),
                    group_index,
                    group,
                ))

        if candidates:
            group = min(candidates, key=lambda item: (item[0], item[1]))[2]
            group['members'].append(level)
            continue

        counters[kind] += 1
        creation_order += 1
        prefix = 'HIGH_GROUP' if kind == SWING_KIND_HIGH else 'LOW_GROUP'
        groups_by_kind[kind].append({
            'group_id': f'{prefix}:{counters[kind]}',
            'kind': kind,
            'anchor_price': level['price'],
            'members': [level],
            'creation_order': creation_order,
        })

    visible = [
        group
        for kind in KIND_ORDER
        for group in groups_by_kind[kind]
        if len(group['members']) >= MIN_LEVEL_GROUP_MEMBERS
    ]
    visible.sort(key=lambda group: (
        group['members'][0]['index'],
        _kind_rank(group['kind']),
        group['creation_order'],
    ))

    output: list[dict[str, Any]] = []
    for group in visible:
        members = group['members']
        prices = [row['price'] for row in members]
        output.append({
            'group_id': group['group_id'],
            'kind': group['kind'],
            'anchor_price': group['anchor_price'],
            'representative_price': sum(prices) / len(prices),
            'member_count': len(members),
            'member_level_ids': [row['level_id'] for row in members],
            'member_swing_ids': [row['swing_id'] for row in members],
            'first_confirmed_at_index': members[0]['confirmed_at_index'],
            'last_confirmed_at_index': members[-1]['confirmed_at_index'],
        })
    return output


def _first_invalidation_index(
    anatomy: list[dict[str, Any]],
    *,
    confirmed_at_index: int,
    kind: str,
    distal_boundary: float,
) -> Optional[int]:
    for index in range(confirmed_at_index, len(anatomy)):
        close = anatomy[index]['close']
        if kind == SWING_KIND_HIGH and close > distal_boundary:
            return index
        if kind == SWING_KIND_LOW and close < distal_boundary:
            return index
    return None


def _zones(
    source_structure: dict[str, Any],
    swings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    anatomy = source_structure['candle_anatomy']
    zones: list[dict[str, Any]] = []

    for swing in swings:
        index = swing['index']
        kind = swing['kind']
        pivot = anatomy[index]
        if kind == SWING_KIND_HIGH:
            zone_kind = ZONE_KIND_SUPPLY_LIKE
            zone_id = f'ZONE:SUPPLY:{index}'
            zone_low = max(pivot['open'], pivot['close'])
            zone_high = pivot['high']
            distal_boundary = zone_high
        else:
            zone_kind = ZONE_KIND_DEMAND_LIKE
            zone_id = f'ZONE:DEMAND:{index}'
            zone_low = pivot['low']
            zone_high = min(pivot['open'], pivot['close'])
            distal_boundary = zone_low

        invalidated_at = _first_invalidation_index(
            anatomy,
            confirmed_at_index=swing['confirmed_at_index'],
            kind=kind,
            distal_boundary=distal_boundary,
        )
        zones.append({
            'zone_id': zone_id,
            'swing_id': swing['swing_id'],
            'index': index,
            'kind': kind,
            'zone_kind': zone_kind,
            'zone_low': zone_low,
            'zone_high': zone_high,
            'zone_width': zone_high - zone_low,
            'confirmed_at_index': swing['confirmed_at_index'],
            'zone_state': ZONE_STATE_INVALIDATED if invalidated_at is not None else ZONE_STATE_ACTIVE,
            'invalidated_at_index': invalidated_at,
        })
    return zones


def analyze_key_levels(candles: list[dict]) -> dict:
    """Project exact levels, anchored groups, and geometric zones from 53B."""
    if not isinstance(candles, list):
        return _envelope(
            level_state=LEVEL_STATE_MALFORMED,
            candle_count=0,
            structure_bias=STRUCTURE_BIAS_UNDEFINED,
            key_levels=[],
            level_groups=[],
            zones=[],
            source_structure=None,
        )

    candle_count = len(candles)
    if candle_count < MIN_LEVEL_CANDLES:
        return _envelope(
            level_state=LEVEL_STATE_INSUFFICIENT,
            candle_count=candle_count,
            structure_bias=STRUCTURE_BIAS_UNDEFINED,
            key_levels=[],
            level_groups=[],
            zones=[],
            source_structure=None,
        )

    source_structure = analyze_price_action_structure(candles)
    if source_structure['structure_state'] == STRUCTURE_STATE_MALFORMED:
        return _envelope(
            level_state=LEVEL_STATE_MALFORMED,
            candle_count=candle_count,
            structure_bias=STRUCTURE_BIAS_UNDEFINED,
            key_levels=[],
            level_groups=[],
            zones=[],
            source_structure=source_structure,
        )
    if source_structure['structure_state'] != STRUCTURE_STATE_OK:
        return _envelope(
            level_state=LEVEL_STATE_MALFORMED,
            candle_count=candle_count,
            structure_bias=STRUCTURE_BIAS_UNDEFINED,
            key_levels=[],
            level_groups=[],
            zones=[],
            source_structure=source_structure,
        )

    swings = _ordered_swings(source_structure)
    levels = _key_levels(source_structure, swings)
    return _envelope(
        level_state=LEVEL_STATE_OK,
        candle_count=candle_count,
        structure_bias=source_structure['structure_bias'],
        key_levels=levels,
        level_groups=_level_groups(levels),
        zones=_zones(source_structure, swings),
        source_structure=source_structure,
    )
