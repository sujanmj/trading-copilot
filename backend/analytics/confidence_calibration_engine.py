"""
Confidence Calibration / Accuracy Tuning Engine — read-only shadow analytics.

Analyzes whether final confidence scores are realistic vs actual WIN/LOSS outcomes.
Never modifies canonical outcomes or live trading decisions.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.analytics.market_memory_learning import _safe_win_rate
from backend.utils.config import DATA_DIR

SHADOW_MODE = True
DISCLAIMER = 'Calibration is analysis only — it does not execute trades.'
REPORT_TYPE = 'confidence_calibration'
FINAL_CONFIDENCE_REPORT_PATH = DATA_DIR / 'final_confidence_report.json'
CALIBRATION_REPORT_PATH = DATA_DIR / 'confidence_calibration_report.json'

BUCKET_SIZE_DEFAULT = 10
MIN_TRUSTED_SAMPLE = 10
OVERCONFIDENT_ERROR = -0.15
UNDERCONFIDENT_ERROR = 0.15

WIN_TOKENS = frozenset({'WIN'})
LOSS_TOKENS = frozenset({'LOSS'})


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_win(resolved_as: str | None) -> bool:
    if not resolved_as:
        return False
    token = str(resolved_as).strip().upper()
    return token in WIN_TOKENS or token.startswith('WIN')


def _is_loss(resolved_as: str | None) -> bool:
    if not resolved_as:
        return False
    token = str(resolved_as).strip().upper()
    return token in LOSS_TOKENS or token.startswith('LOSS')


def _score_bucket_label(score: int | float | None, bucket_size: int = BUCKET_SIZE_DEFAULT) -> str | None:
    if score is None:
        return None
    try:
        value = int(round(float(score)))
    except (TypeError, ValueError):
        return None
    value = max(0, min(100, value))
    low = (value // bucket_size) * bucket_size
    high = min(low + bucket_size - 1, 100)
    return f'{low}-{high}'


def _bucket_keys(bucket_size: int = BUCKET_SIZE_DEFAULT) -> list[str]:
    keys: list[str] = []
    for low in range(0, 100, bucket_size):
        high = min(low + bucket_size - 1, 99 if low < 90 else 100)
        if low == 90:
            high = 100
        keys.append(f'{low}-{high}')
    return keys


def _init_bucket_store(bucket_size: int = BUCKET_SIZE_DEFAULT) -> dict[str, dict[str, Any]]:
    store: dict[str, dict[str, Any]] = {}
    for label in _bucket_keys(bucket_size):
        store[label] = {
            'bucket': label,
            'candidates': 0,
            'resolved_live': 0,
            'resolved_historical': 0,
            'wins': 0,
            'losses': 0,
            'score_sum': 0.0,
            'score_count': 0,
            'warning_counts': Counter(),
        }
    return store


def _finalize_bucket(raw: dict[str, Any]) -> dict[str, Any]:
    wins = int(raw.get('wins') or 0)
    losses = int(raw.get('losses') or 0)
    resolved = wins + losses
    score_count = int(raw.get('score_count') or 0)
    avg_score = round(raw['score_sum'] / score_count, 2) if score_count else None
    win_rate = _safe_win_rate(wins, losses)
    expected = round(avg_score / 100, 4) if avg_score is not None else None
    calibration_error = (
        round(win_rate - expected, 4)
        if win_rate is not None and expected is not None
        else None
    )
    sample_warning = 'ok' if resolved >= MIN_TRUSTED_SAMPLE else 'low_sample'
    warning_counts: Counter = raw.get('warning_counts') or Counter()
    common_warnings = [
        name for name, _count in warning_counts.most_common(5)
        if name
    ]
    return {
        'bucket': raw['bucket'],
        'candidates': int(raw.get('candidates') or 0),
        'resolved_live': int(raw.get('resolved_live') or 0),
        'resolved_historical': int(raw.get('resolved_historical') or 0),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_score': avg_score,
        'expected_win_rate': expected,
        'calibration_error': calibration_error,
        'sample_warning': sample_warning,
        'common_warnings': common_warnings,
    }


def _load_json_report(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_scored_rows(*, limit: int = 500) -> list[dict[str, Any]]:
    """Load scored candidate rows from report JSON or live scoring."""
    rows_by_id: dict[str, dict[str, Any]] = {}

    report = _load_json_report(FINAL_CONFIDENCE_REPORT_PATH)
    if report and report.get('ok') is True:
        for row in (report.get('rows') or []) + (report.get('top_candidates') or []):
            if not isinstance(row, dict):
                continue
            pid = str(row.get('prediction_id') or '').strip()
            if pid:
                rows_by_id[pid] = row

    try:
        from backend.analytics.final_confidence_fusion import score_all_candidates

        batch = score_all_candidates(limit=limit, include_resolved=True)
        for row in batch.get('rows') or []:
            if not isinstance(row, dict):
                continue
            pid = str(row.get('prediction_id') or '').strip()
            if pid:
                rows_by_id[pid] = row
    except Exception:
        if not rows_by_id and report:
            for row in (report.get('rows') or []):
                pid = str(row.get('prediction_id') or '').strip()
                if pid:
                    rows_by_id[pid] = row

    if not rows_by_id:
        try:
            from backend.analytics.final_confidence_fusion import build_final_confidence_report

            built = build_final_confidence_report(limit=min(limit, 100))
            for row in (built.get('rows') or []):
                pid = str(row.get('prediction_id') or '').strip()
                if pid:
                    rows_by_id[pid] = row
        except Exception:
            pass

    return list(rows_by_id.values())


def _fetch_live_outcomes() -> dict[str, str]:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    init_market_memory_db()
    conn = get_connection()
    outcomes: dict[str, str] = {}
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = conn.execute(
            """
            SELECT prediction_id, resolved_as
            FROM outcomes
            WHERE resolved_as IS NOT NULL AND TRIM(resolved_as) != ''
            """
        ).fetchall()
        for row in rows:
            pid = str(row['prediction_id'] or '').strip()
            resolved = str(row['resolved_as'] or '').strip()
            if not pid or not resolved:
                continue
            if _is_win(resolved) or _is_loss(resolved):
                outcomes[pid] = resolved
    finally:
        conn.close()
    return outcomes


def _fetch_historical_replay_outcomes() -> dict[str, str]:
    from backend.storage.historical_market_store import get_connection, init_db

    init_db()
    conn = get_connection()
    outcomes: dict[str, str] = {}
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = conn.execute(
            """
            SELECT prediction_id, resolved_as
            FROM historical_outcome_replay
            WHERE resolved_as IS NOT NULL AND TRIM(resolved_as) != ''
            """
        ).fetchall()
        for row in rows:
            pid = str(row['prediction_id'] or '').strip()
            resolved = str(row['resolved_as'] or '').strip()
            if not pid or not resolved:
                continue
            if _is_win(resolved) or _is_loss(resolved):
                outcomes[pid] = resolved
    finally:
        conn.close()
    return outcomes


def _row_warnings(row: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for key in ('hard_warnings', 'warnings', 'soft_warnings'):
        value = row.get(key)
        if isinstance(value, list):
            warnings.extend(str(item).strip() for item in value if str(item).strip())
    return warnings


def _enrich_rows(
    rows: list[dict[str, Any]],
    *,
    live_outcomes: dict[str, str] | None = None,
    historical_outcomes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    live_map = live_outcomes if live_outcomes is not None else _fetch_live_outcomes()
    hist_map = historical_outcomes if historical_outcomes is not None else _fetch_historical_replay_outcomes()

    enriched: list[dict[str, Any]] = []
    for row in rows:
        pid = str(row.get('prediction_id') or '').strip()
        live_resolved = live_map.get(pid)
        hist_resolved = hist_map.get(pid)
        combined_resolved = live_resolved or hist_resolved
        enriched.append({
            **row,
            'prediction_id': pid,
            'live_resolved_as': live_resolved,
            'historical_resolved_as': hist_resolved,
            'combined_resolved_as': combined_resolved,
            'resolved_source': (
                'live' if live_resolved else ('historical' if hist_resolved else None)
            ),
            'all_warnings': _row_warnings(row),
        })
    return enriched


def _accumulate_bucket(
    store: dict[str, dict[str, Any]],
    *,
    label: str,
    row: dict[str, Any],
    resolved_as: str | None,
    resolved_kind: str | None,
) -> None:
    bucket = store.setdefault(label, {
        'bucket': label,
        'candidates': 0,
        'resolved_live': 0,
        'resolved_historical': 0,
        'wins': 0,
        'losses': 0,
        'score_sum': 0.0,
        'score_count': 0,
        'warning_counts': Counter(),
    })
    bucket['candidates'] += 1
    score = row.get('final_score')
    if score is not None:
        try:
            bucket['score_sum'] += float(score)
            bucket['score_count'] += 1
        except (TypeError, ValueError):
            pass
    for warning in row.get('all_warnings') or []:
        bucket['warning_counts'][warning] += 1

    if not resolved_as:
        return

    if resolved_kind == 'live':
        bucket['resolved_live'] += 1
    elif resolved_kind == 'historical':
        bucket['resolved_historical'] += 1

    if _is_win(resolved_as):
        bucket['wins'] += 1
    elif _is_loss(resolved_as):
        bucket['losses'] += 1


def _build_buckets_for_rows(
    rows: list[dict[str, Any]],
    *,
    mode: str,
    bucket_size: int = BUCKET_SIZE_DEFAULT,
) -> list[dict[str, Any]]:
    store = _init_bucket_store(bucket_size)
    for row in rows:
        label = _score_bucket_label(row.get('final_score'), bucket_size)
        if not label:
            continue
        if mode == 'live':
            resolved = row.get('live_resolved_as')
            kind = 'live' if resolved else None
        elif mode == 'historical':
            resolved = row.get('historical_resolved_as')
            kind = 'historical' if resolved else None
        else:
            resolved = row.get('combined_resolved_as')
            kind = row.get('resolved_source')
        _accumulate_bucket(store, label=label, row=row, resolved_as=resolved, resolved_kind=kind)

    return [_finalize_bucket(store[key]) for key in _bucket_keys(bucket_size)]


def _optional_broker_enrichment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from backend.analytics.broker_prediction_intelligence import get_broker_prediction_intelligence_summary

        summary = get_broker_prediction_intelligence_summary()
        return {
            'available': summary.get('ok') is True,
            'broker_pick_count': summary.get('pick_count'),
            'relationship_counts': summary.get('relationship_counts') or {},
            'matched_rows': sum(
                1 for row in rows if any(
                    token in (row.get('all_warnings') or [])
                    for token in ('broker_conflict', 'mixed_broker_signals', 'broker_intelligence_conflict')
                )
            ),
        }
    except Exception:
        return {'available': False}


def _dataset_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    live_outcomes = _fetch_live_outcomes()
    historical_outcomes = _fetch_historical_replay_outcomes()
    enriched = _enrich_rows(rows, live_outcomes=live_outcomes, historical_outcomes=historical_outcomes)
    return {
        'rows': enriched,
        'live_outcomes': live_outcomes,
        'historical_outcomes': historical_outcomes,
        'live_resolved': sum(1 for row in enriched if row.get('live_resolved_as')),
        'historical_resolved': sum(1 for row in enriched if row.get('historical_resolved_as')),
        'combined_resolved': sum(1 for row in enriched if row.get('combined_resolved_as')),
        'broker_enrichment': _optional_broker_enrichment(enriched),
    }


def bucket_final_confidence_scores(bucket_size: int = BUCKET_SIZE_DEFAULT) -> dict[str, Any]:
    ctx = _dataset_context(_load_scored_rows())
    rows = ctx['rows']
    return {
        'ok': True,
        'bucket_size': bucket_size,
        'candidates': len(rows),
        'live': {
            'resolved': ctx['live_resolved'],
            'buckets': _build_buckets_for_rows(rows, mode='live', bucket_size=bucket_size),
        },
        'historical': {
            'resolved': ctx['historical_resolved'],
            'buckets': _build_buckets_for_rows(rows, mode='historical', bucket_size=bucket_size),
        },
        'combined': {
            'label': 'live first, historical fallback',
            'resolved': ctx['combined_resolved'],
            'buckets': _build_buckets_for_rows(rows, mode='combined', bucket_size=bucket_size),
        },
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def compare_score_vs_live_outcomes() -> dict[str, Any]:
    ctx = _dataset_context(_load_scored_rows())
    rows = ctx['rows']
    buckets = _build_buckets_for_rows(rows, mode='live')
    resolved_rows = [row for row in rows if row.get('live_resolved_as')]
    wins = sum(1 for row in resolved_rows if _is_win(row.get('live_resolved_as')))
    losses = sum(1 for row in resolved_rows if _is_loss(row.get('live_resolved_as')))
    scores = [float(row['final_score']) for row in resolved_rows if row.get('final_score') is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None
    win_rate = _safe_win_rate(wins, losses)
    expected = round(avg_score / 100, 4) if avg_score is not None else None
    return {
        'ok': True,
        'source': 'canonical_market_memory.outcomes',
        'resolved': len(resolved_rows),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_score': avg_score,
        'expected_win_rate': expected,
        'calibration_error': (
            round(win_rate - expected, 4)
            if win_rate is not None and expected is not None
            else None
        ),
        'buckets': buckets,
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def compare_score_vs_historical_replay() -> dict[str, Any]:
    ctx = _dataset_context(_load_scored_rows())
    rows = ctx['rows']
    buckets = _build_buckets_for_rows(rows, mode='historical')
    resolved_rows = [row for row in rows if row.get('historical_resolved_as')]
    wins = sum(1 for row in resolved_rows if _is_win(row.get('historical_resolved_as')))
    losses = sum(1 for row in resolved_rows if _is_loss(row.get('historical_resolved_as')))
    scores = [float(row['final_score']) for row in resolved_rows if row.get('final_score') is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None
    win_rate = _safe_win_rate(wins, losses)
    expected = round(avg_score / 100, 4) if avg_score is not None else None
    return {
        'ok': True,
        'source': 'historical_market_memory.historical_outcome_replay',
        'resolved': len(resolved_rows),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_score': avg_score,
        'expected_win_rate': expected,
        'calibration_error': (
            round(win_rate - expected, 4)
            if win_rate is not None and expected is not None
            else None
        ),
        'buckets': buckets,
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def identify_overconfident_buckets(
    *,
    buckets: list[dict[str, Any]] | None = None,
    mode: str = 'combined',
) -> dict[str, Any]:
    if buckets is None:
        payload = bucket_final_confidence_scores()
        section = payload.get(mode) or payload.get('combined') or {}
        buckets = section.get('buckets') or []

    flagged: list[dict[str, Any]] = []
    for bucket in buckets:
        if bucket.get('sample_warning') != 'ok':
            continue
        error = bucket.get('calibration_error')
        if error is None or error >= OVERCONFIDENT_ERROR:
            continue
        flagged.append({
            **bucket,
            'issue': 'overconfident',
            'detail': 'actual win rate materially below score-implied expectation',
        })

    return {
        'ok': True,
        'mode': mode,
        'threshold': OVERCONFIDENT_ERROR,
        'count': len(flagged),
        'buckets': flagged,
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def identify_underconfident_buckets(
    *,
    buckets: list[dict[str, Any]] | None = None,
    mode: str = 'combined',
) -> dict[str, Any]:
    if buckets is None:
        payload = bucket_final_confidence_scores()
        section = payload.get(mode) or payload.get('combined') or {}
        buckets = section.get('buckets') or []

    flagged: list[dict[str, Any]] = []
    for bucket in buckets:
        if bucket.get('sample_warning') != 'ok':
            continue
        error = bucket.get('calibration_error')
        if error is None or error <= UNDERCONFIDENT_ERROR:
            continue
        flagged.append({
            **bucket,
            'issue': 'underconfident',
            'detail': 'actual win rate materially above score-implied expectation',
        })

    return {
        'ok': True,
        'mode': mode,
        'threshold': UNDERCONFIDENT_ERROR,
        'count': len(flagged),
        'buckets': flagged,
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def _recommendation_strength(sample: int, error: float) -> str:
    magnitude = abs(error)
    if sample >= 30 and magnitude >= 0.25:
        return 'strong'
    if sample >= 20 and magnitude >= 0.20:
        return 'medium'
    if sample >= MIN_TRUSTED_SAMPLE and magnitude >= 0.15:
        return 'weak'
    return 'weak'


def recommend_score_adjustments(
    *,
    mode: str = 'combined',
    buckets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if buckets is None:
        bucket_payload = bucket_final_confidence_scores()
        section = bucket_payload.get(mode) or bucket_payload.get('combined') or {}
        buckets = section.get('buckets') or []

    over = identify_overconfident_buckets(buckets=buckets, mode=mode).get('buckets') or []
    under = identify_underconfident_buckets(buckets=buckets, mode=mode).get('buckets') or []

    recommendations: list[dict[str, Any]] = []
    for bucket in over:
        sample = int(bucket.get('wins') or 0) + int(bucket.get('losses') or 0)
        error = float(bucket.get('calibration_error') or 0)
        recommendations.append({
            'bucket': bucket.get('bucket'),
            'type': 'reduce_score',
            'strength': _recommendation_strength(sample, error),
            'calibration_error': bucket.get('calibration_error'),
            'win_rate': bucket.get('win_rate'),
            'expected_win_rate': bucket.get('expected_win_rate'),
            'sample_size': sample,
            'rationale': 'Scores in this bucket exceed realized win rate.',
        })
        for warning in bucket.get('common_warnings') or []:
            recommendations.append({
                'bucket': bucket.get('bucket'),
                'type': 'warning_weight',
                'strength': 'weak',
                'warning': warning,
                'sample_size': sample,
                'rationale': f'Common warning {warning} appears in miscalibrated bucket.',
            })

    for bucket in under:
        sample = int(bucket.get('wins') or 0) + int(bucket.get('losses') or 0)
        error = float(bucket.get('calibration_error') or 0)
        recommendations.append({
            'bucket': bucket.get('bucket'),
            'type': 'increase_score',
            'strength': _recommendation_strength(sample, error),
            'calibration_error': bucket.get('calibration_error'),
            'win_rate': bucket.get('win_rate'),
            'expected_win_rate': bucket.get('expected_win_rate'),
            'sample_size': sample,
            'rationale': 'Realized win rate exceeds score-implied expectation.',
        })

    return {
        'ok': True,
        'mode': mode,
        'count': len(recommendations),
        'recommendations': recommendations,
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def get_confidence_calibration_summary() -> dict[str, Any]:
    ctx = _dataset_context(_load_scored_rows())
    live_cmp = compare_score_vs_live_outcomes()
    hist_cmp = compare_score_vs_historical_replay()
    combined_buckets = _build_buckets_for_rows(ctx['rows'], mode='combined')
    over = identify_overconfident_buckets(buckets=combined_buckets, mode='combined')
    under = identify_underconfident_buckets(buckets=combined_buckets, mode='combined')
    recs = recommend_score_adjustments(mode='combined')

    warnings: list[str] = []
    if ctx['live_resolved'] < MIN_TRUSTED_SAMPLE:
        warnings.append('low_live_sample')
    if ctx['historical_resolved'] < MIN_TRUSTED_SAMPLE:
        warnings.append('low_historical_sample')
    if not ctx['rows']:
        warnings.append('no_scored_candidates')

    return {
        'ok': True,
        'generated_at': _now_iso(),
        'candidates': len(ctx['rows']),
        'live_resolved': ctx['live_resolved'],
        'historical_resolved': ctx['historical_resolved'],
        'combined_resolved': ctx['combined_resolved'],
        'live_win_rate': live_cmp.get('win_rate'),
        'historical_win_rate': hist_cmp.get('win_rate'),
        'combined_calibration_error': live_cmp.get('calibration_error'),
        'overconfident_buckets': over.get('count', 0),
        'underconfident_buckets': under.get('count', 0),
        'recommendations': recs.get('count', 0),
        'warnings': warnings,
        'broker_enrichment': ctx.get('broker_enrichment') or {},
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def build_confidence_calibration_report(*, bucket_size: int = BUCKET_SIZE_DEFAULT) -> dict[str, Any]:
    """Full calibration report payload for JSON export."""
    bucket_payload = bucket_final_confidence_scores(bucket_size=bucket_size)
    live = compare_score_vs_live_outcomes()
    historical = compare_score_vs_historical_replay()
    combined_section = bucket_payload.get('combined') or {}
    combined_buckets = combined_section.get('buckets') or []
    over = identify_overconfident_buckets(buckets=combined_buckets, mode='combined')
    under = identify_underconfident_buckets(buckets=combined_buckets, mode='combined')
    recommendations = recommend_score_adjustments(mode='combined')
    summary = get_confidence_calibration_summary()

    warnings = list(summary.get('warnings') or [])
    if summary.get('live_resolved', 0) < MIN_TRUSTED_SAMPLE:
        warnings.append('live_buckets_not_fully_trusted')
    if summary.get('historical_resolved', 0) < MIN_TRUSTED_SAMPLE:
        warnings.append('historical_buckets_not_fully_trusted')

    return {
        'ok': True,
        'report_type': REPORT_TYPE,
        'generated_at': _now_iso(),
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
        'summary': summary,
        'live': {
            'resolved': live.get('resolved', 0),
            'win_rate': live.get('win_rate'),
            'calibration_error': live.get('calibration_error'),
            'buckets': live.get('buckets') or [],
            'overconfident': identify_overconfident_buckets(
                buckets=live.get('buckets') or [], mode='live'
            ).get('buckets') or [],
            'underconfident': identify_underconfident_buckets(
                buckets=live.get('buckets') or [], mode='live'
            ).get('buckets') or [],
        },
        'historical': {
            'resolved': historical.get('resolved', 0),
            'win_rate': historical.get('win_rate'),
            'calibration_error': historical.get('calibration_error'),
            'buckets': historical.get('buckets') or [],
            'overconfident': identify_overconfident_buckets(
                buckets=historical.get('buckets') or [], mode='historical'
            ).get('buckets') or [],
            'underconfident': identify_underconfident_buckets(
                buckets=historical.get('buckets') or [], mode='historical'
            ).get('buckets') or [],
        },
        'combined': {
            'label': combined_section.get('label') or 'live first, historical fallback',
            'resolved': combined_section.get('resolved', 0),
            'buckets': combined_buckets,
            'overconfident': over.get('buckets') or [],
            'underconfident': under.get('buckets') or [],
        },
        'recommendations': recommendations.get('recommendations') or [],
        'warnings': sorted(set(warnings)),
        'broker_enrichment': summary.get('broker_enrichment') or {},
    }


def get_calibration_dashboard() -> dict[str, Any]:
    """API/dashboard payload mirroring the calibration report."""
    report = build_confidence_calibration_report()
    return {
        **report,
        'dashboard': True,
    }
