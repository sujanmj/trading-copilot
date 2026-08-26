"""AstraEdge 53F deterministic historical setup evidence.

Groups caller-supplied historical observations by an exact 53E2 factual
fingerprint and summarizes the recorded forward-return values. Descriptive
evidence only. No model, forecast, or trade interpretation.
"""

from __future__ import annotations

import math
import statistics
from fractions import Fraction
from typing import Any, Optional

from backend.analysis.premarket_structure import analyze_premarket_structure

SCHEMA_VERSION = '53F'
MATCH_SCOPE = 'EXACT_53E2_FACT_FINGERPRINT'
OUTCOME_SCOPE = 'CALLER_SUPPLIED_FORWARD_RETURN_RATIO'
FINGERPRINT_VERSION = '53F-1'

ANALYSIS_STATE_MALFORMED = 'MALFORMED'
ANALYSIS_STATE_SOURCE_NOT_READY = 'SOURCE_NOT_READY'
ANALYSIS_STATE_NO_MATCHES = 'NO_MATCHES'
ANALYSIS_STATE_OK = 'OK'

SOURCE_STATE_OK = 'OK'

OUTCOME_POSITIVE = 'POSITIVE'
OUTCOME_NEGATIVE = 'NEGATIVE'
OUTCOME_FLAT = 'FLAT'

OUTCOME_COUNT_KEYS = (
    OUTCOME_POSITIVE,
    OUTCOME_NEGATIVE,
    OUTCOME_FLAT,
)

VOLUME_STATE_COUNT_KEYS = (
    'HIGH_VOLUME',
    'NORMAL_VOLUME',
    'LOW_VOLUME',
    'UNDEFINED',
)

FINGERPRINT_KEYS = (
    'fingerprint_version',
    'gap_state',
    'observation_vs_previous_close',
    'observation_vs_premarket_reference',
    'observation_vs_premarket_range',
    'timeframe_count',
    'structure_alignment',
    'structure_alignment_frame_count',
    'vwap_alignment',
    'vwap_alignment_frame_count',
    'volume_state_counts',
)

HISTORY_RECORD_KEYS = (
    'history_index',
    'forward_return_ratio',
    'outcome_state',
    'source_state',
    'eligible',
    'fingerprint',
    'matched',
    'source_premarket',
)

MATCHED_EVIDENCE_KEYS = (
    'history_index',
    'forward_return_ratio',
    'outcome_state',
)

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'match_scope',
    'outcome_scope',
    'outcome_horizon',
    'fingerprint_version',
    'history_count',
    'history_eligible_count',
    'history_excluded_count',
    'matched_sample_count',
    'current_fingerprint',
    'outcome_counts',
    'mean_forward_return_ratio',
    'median_forward_return_ratio',
    'min_forward_return_ratio',
    'max_forward_return_ratio',
    'matched_evidence',
    'source_current',
    'history_records',
)


def _zero_outcome_counts() -> dict[str, int]:
    return {key: 0 for key in OUTCOME_COUNT_KEYS}


def _envelope(
    *,
    analysis_state: str,
    outcome_horizon: Optional[str],
    history_count: int,
    history_eligible_count: int,
    history_excluded_count: int,
    matched_sample_count: int,
    current_fingerprint: Optional[dict[str, Any]],
    outcome_counts: dict[str, int],
    mean_forward_return_ratio: Optional[float],
    median_forward_return_ratio: Optional[float],
    min_forward_return_ratio: Optional[float],
    max_forward_return_ratio: Optional[float],
    matched_evidence: list[dict[str, Any]],
    source_current: Optional[dict[str, Any]],
    history_records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'analysis_state': analysis_state,
        'match_scope': MATCH_SCOPE,
        'outcome_scope': OUTCOME_SCOPE,
        'outcome_horizon': outcome_horizon,
        'fingerprint_version': FINGERPRINT_VERSION,
        'history_count': history_count,
        'history_eligible_count': history_eligible_count,
        'history_excluded_count': history_excluded_count,
        'matched_sample_count': matched_sample_count,
        'current_fingerprint': current_fingerprint,
        'outcome_counts': outcome_counts,
        'mean_forward_return_ratio': mean_forward_return_ratio,
        'median_forward_return_ratio': median_forward_return_ratio,
        'min_forward_return_ratio': min_forward_return_ratio,
        'max_forward_return_ratio': max_forward_return_ratio,
        'matched_evidence': list(matched_evidence),
        'source_current': source_current,
        'history_records': list(history_records),
    }


def _malformed() -> dict[str, Any]:
    return _envelope(
        analysis_state=ANALYSIS_STATE_MALFORMED,
        outcome_horizon=None,
        history_count=0,
        history_eligible_count=0,
        history_excluded_count=0,
        matched_sample_count=0,
        current_fingerprint=None,
        outcome_counts=_zero_outcome_counts(),
        mean_forward_return_ratio=None,
        median_forward_return_ratio=None,
        min_forward_return_ratio=None,
        max_forward_return_ratio=None,
        matched_evidence=[],
        source_current=None,
        history_records=[],
    )


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _outer_payload_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if 'current_snapshot' not in payload:
        return False
    if not isinstance(payload['current_snapshot'], dict):
        return False
    if 'outcome_horizon' not in payload:
        return False
    horizon = payload['outcome_horizon']
    if not isinstance(horizon, str) or not horizon.strip():
        return False
    if 'history' not in payload:
        return False
    history = payload['history']
    if not isinstance(history, list):
        return False
    for item in history:
        if not isinstance(item, dict):
            return False
        if 'snapshot' not in item:
            return False
        if not isinstance(item['snapshot'], dict):
            return False
        if 'forward_return_ratio' not in item:
            return False
        if not _finite_number(item['forward_return_ratio']):
            return False
    return True


def _outcome_state(value: float) -> str:
    if value > 0:
        return OUTCOME_POSITIVE
    if value < 0:
        return OUTCOME_NEGATIVE
    return OUTCOME_FLAT


def _volume_state_counts(source: dict[str, Any]) -> dict[str, int]:
    counts = source['volume_state_counts']
    return {key: counts[key] for key in VOLUME_STATE_COUNT_KEYS}


def _fingerprint(source: dict[str, Any]) -> dict[str, Any]:
    return {
        'fingerprint_version': FINGERPRINT_VERSION,
        'gap_state': source['gap_state'],
        'observation_vs_previous_close': source['observation_vs_previous_close'],
        'observation_vs_premarket_reference': source['observation_vs_premarket_reference'],
        'observation_vs_premarket_range': source['observation_vs_premarket_range'],
        'timeframe_count': source['timeframe_count'],
        'structure_alignment': source['structure_alignment'],
        'structure_alignment_frame_count': source['structure_alignment_frame_count'],
        'vwap_alignment': source['vwap_alignment'],
        'vwap_alignment_frame_count': source['vwap_alignment_frame_count'],
        'volume_state_counts': _volume_state_counts(source),
    }


def _mean(values: list[Any]) -> Any:
    count = len(values)
    if count == 1:
        return values[0]
    try:
        return sum(values) / count
    except OverflowError:
        return sum((Fraction(value) for value in values), start=Fraction(0)) / count


def _median(values: list[Any]) -> Any:
    try:
        return statistics.median(values)
    except OverflowError:
        ordered = sorted(values)
        count = len(ordered)
        if count % 2:
            return ordered[count // 2]
        return (
            Fraction(ordered[count // 2 - 1]) + Fraction(ordered[count // 2])
        ) / 2


def _summary(values: list[Any]) -> tuple[Any, Any, Any, Any]:
    if not values:
        return None, None, None, None
    if len(values) == 1:
        only = values[0]
        return only, only, only, only
    return (
        _mean(values),
        _median(values),
        min(values),
        max(values),
    )


def analyze_historical_setup_evidence(payload: dict) -> dict:
    """Summarize caller-supplied historical outcomes for one exact 53E2 fingerprint."""
    if not _outer_payload_valid(payload):
        return _malformed()

    current_source = analyze_premarket_structure(payload['current_snapshot'])
    history_records: list[dict[str, Any]] = []
    eligible_count = 0
    for index, item in enumerate(payload['history']):
        source = analyze_premarket_structure(item['snapshot'])
        source_state = source['analysis_state']
        eligible = source_state == SOURCE_STATE_OK
        if eligible:
            eligible_count += 1
        ratio = item['forward_return_ratio']
        history_records.append({
            'history_index': index,
            'forward_return_ratio': ratio,
            'outcome_state': _outcome_state(ratio),
            'source_state': source_state,
            'eligible': eligible,
            'fingerprint': _fingerprint(source) if eligible else None,
            'matched': False,
            'source_premarket': source,
        })

    history_count = len(history_records)
    excluded_count = history_count - eligible_count
    current_ok = current_source['analysis_state'] == SOURCE_STATE_OK
    current_fingerprint = _fingerprint(current_source) if current_ok else None

    matched_evidence: list[dict[str, Any]] = []
    matched_values: list[float] = []
    outcome_counts = _zero_outcome_counts()
    if current_ok:
        for record in history_records:
            if record['eligible'] and record['fingerprint'] == current_fingerprint:
                record['matched'] = True
                matched_values.append(record['forward_return_ratio'])
                outcome_counts[record['outcome_state']] += 1
                matched_evidence.append({
                    'history_index': record['history_index'],
                    'forward_return_ratio': record['forward_return_ratio'],
                    'outcome_state': record['outcome_state'],
                })

    matched_sample_count = len(matched_evidence)
    mean_value, median_value, min_value, max_value = _summary(matched_values)
    if not current_ok:
        analysis_state = ANALYSIS_STATE_SOURCE_NOT_READY
    elif matched_sample_count == 0:
        analysis_state = ANALYSIS_STATE_NO_MATCHES
    else:
        analysis_state = ANALYSIS_STATE_OK

    return _envelope(
        analysis_state=analysis_state,
        outcome_horizon=payload['outcome_horizon'],
        history_count=history_count,
        history_eligible_count=eligible_count,
        history_excluded_count=excluded_count,
        matched_sample_count=matched_sample_count,
        current_fingerprint=current_fingerprint,
        outcome_counts=outcome_counts,
        mean_forward_return_ratio=mean_value,
        median_forward_return_ratio=median_value,
        min_forward_return_ratio=min_value,
        max_forward_return_ratio=max_value,
        matched_evidence=matched_evidence,
        source_current=current_source,
        history_records=history_records,
    )
