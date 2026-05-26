"""
Market day type + regime performance analytics for long-term calibration.

Uses daily review snapshots + signal outcome horizons — no external APIs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.storage.db_manager import get_connection, init_db
from backend.utils.config import ANALYSIS_EXPLANATIONS_FILE, DATA_DIR

DAILY_REVIEWS_DIR = DATA_DIR / 'daily_reviews'
REVIEW_INDEX_FILE = DAILY_REVIEWS_DIR / 'index.json'
EXECUTION_METRICS_FILE = DATA_DIR / 'execution_metrics.json'

MARKET_DAY_TYPES = [
    'TRENDING DAY',
    'SIDEWAYS CHOP',
    'PANIC VOLATILE',
    'REGIME TRANSITION',
    'MACRO SHOCK',
    'EXPIRY VOLATILITY',
    'LOW LIQUIDITY',
    'MIXED SESSION',
]

MIN_SAMPLES_DAY_TYPE = 4


def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if data is not None else default
    except Exception:
        return default


def _day_type_for_date(review_date: str) -> str:
    cached = _load_json(DAILY_REVIEWS_DIR / f'review_{review_date}.json', {})
    label = (cached.get('market_day_classification') or {}).get('label')
    if label:
        return str(label)
    return 'MIXED SESSION'


def _query_horizon_rows() -> List[dict]:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.event_date, e.signal_type, e.confidence, e.confidence_band,
                   e.contradiction_severity, h.hit_miss, h.change_pct
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE h.hit_miss IN ('HIT', 'MISS')
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_market_day_performance(min_samples: int = MIN_SAMPLES_DAY_TYPE) -> dict:
    """Performance grouped by classified market day type."""
    rows = _query_horizon_rows()
    buckets: Dict[str, dict] = defaultdict(
        lambda: {
            'hit': 0,
            'miss': 0,
            'telegram_hit': 0,
            'telegram_total': 0,
            'confidence_sum': 0.0,
            'confidence_count': 0,
            'contra_hit': 0,
            'contra_total': 0,
            'moves': [],
            'dates': set(),
        }
    )

    for row in rows:
        day_type = _day_type_for_date(row.get('event_date') or '')
        b = buckets[day_type]
        b['dates'].add(row.get('event_date'))
        if row['hit_miss'] == 'HIT':
            b['hit'] += 1
        else:
            b['miss'] += 1
        if row.get('signal_type') == 'telegram':
            b['telegram_total'] += 1
            if row['hit_miss'] == 'HIT':
                b['telegram_hit'] += 1
        conf = row.get('confidence')
        if conf is not None:
            try:
                c = float(conf)
                if c > 1.0:
                    c /= 10.0
                b['confidence_sum'] += c
                b['confidence_count'] += 1
            except (TypeError, ValueError):
                pass
        contra = row.get('contradiction_severity')
        if contra is not None:
            try:
                if float(contra) >= 0.35:
                    b['contra_total'] += 1
                    if row['hit_miss'] == 'HIT':
                        b['contra_hit'] += 1
            except (TypeError, ValueError):
                pass
        if row.get('change_pct') is not None:
            b['moves'].append(float(row['change_pct']))

    table = []
    for day_type in MARKET_DAY_TYPES:
        stats = buckets.get(day_type)
        if not stats:
            continue
        total = stats['hit'] + stats['miss']
        if total < min_samples:
            continue
        accuracy = round(stats['hit'] / total * 100, 1)
        fp_rate = round(stats['miss'] / total * 100, 1)
        tg_precision = (
            round(stats['telegram_hit'] / stats['telegram_total'] * 100, 1)
            if stats['telegram_total'] >= min_samples
            else None
        )
        avg_conf = (
            round(stats['confidence_sum'] / stats['confidence_count'], 2)
            if stats['confidence_count']
            else None
        )
        conf_realism = (
            round(100 - abs(accuracy - (avg_conf or 0.5) * 100), 1)
            if avg_conf is not None
            else None
        )
        contra_use = (
            round(stats['contra_hit'] / stats['contra_total'] * 100, 1)
            if stats['contra_total'] >= min_samples
            else None
        )
        table.append({
            'day_type': day_type,
            'samples': total,
            'signal_accuracy_pct': accuracy,
            'false_positive_rate_pct': fp_rate,
            'telegram_usefulness_pct': tg_precision,
            'confidence_realism_pct': conf_realism,
            'contradiction_usefulness_pct': contra_use,
            'avg_move_pct': round(sum(stats['moves']) / len(stats['moves']), 2) if stats['moves'] else 0,
            'session_count': len(stats['dates']),
            'statistically_meaningful': total >= min_samples,
        })

    return {
        'day_types': table,
        'min_samples_required': min_samples,
        'total_evaluated': len(rows),
    }


def get_calibration_health_scores() -> dict:
    """Composite health scores for AI calibration dashboard."""
    rows = _query_horizon_rows()
    explanations = _load_json(ANALYSIS_EXPLANATIONS_FILE, {})
    latest_q = (explanations.get('latest') or {}).get('quality') or {}
    metrics = _load_json(EXECUTION_METRICS_FILE, {})
    counters = metrics.get('counters') or {}

    hits = sum(1 for r in rows if r.get('hit_miss') == 'HIT')
    evaluated = len(rows)
    overall_accuracy = round(hits / evaluated * 100, 1) if evaluated >= 8 else None

    conf_rows = [r for r in rows if r.get('confidence') is not None]
    realism_errors = []
    for r in conf_rows:
        try:
            c = float(r['confidence'])
            if c > 1.0:
                c /= 10.0
            actual = 1.0 if r['hit_miss'] == 'HIT' else 0.0
            realism_errors.append(abs(c - actual))
        except (TypeError, ValueError):
            pass
    confidence_realism = (
        round(max(0.0, 1.0 - (sum(realism_errors) / len(realism_errors))) * 100, 1)
        if len(realism_errors) >= 8
        else None
    )

    contra_score = latest_q.get('contradiction_retention_score')
    if contra_score is None:
        high_contra = [r for r in rows if r.get('contradiction_severity') and float(r['contradiction_severity']) >= 0.35]
        if len(high_contra) >= 4:
            contra_hits = sum(1 for r in high_contra if r['hit_miss'] == 'HIT')
            contra_score = round(contra_hits / len(high_contra), 2)

    sentiment_score = latest_q.get('sentiment_preservation_score')
    regime_days = get_market_day_performance().get('day_types') or []
    regime_scores = [d['signal_accuracy_pct'] for d in regime_days if d.get('signal_accuracy_pct') is not None]
    regime_adaptation = None
    if len(regime_scores) >= 2:
        spread = max(regime_scores) - min(regime_scores)
        regime_adaptation = round(min(100.0, spread * 1.2), 1)

    iq_trend = _reliability_iq_trend()

    return {
        'confidence_realism_score': confidence_realism,
        'contradiction_handling_score': round(float(contra_score) * 100, 1) if contra_score is not None else None,
        'sentiment_preservation_score': round(float(sentiment_score) * 100, 1) if sentiment_score is not None else None,
        'regime_adaptation_score': regime_adaptation,
        'reliability_iq_trend': iq_trend,
        'overall_signal_accuracy_pct': overall_accuracy,
        'samples_evaluated': evaluated,
        'fallback_activations': counters.get('safe_fallbacks', 0),
        'hallucination_detections': counters.get('hallucination_detections', 0),
    }


def _reliability_iq_trend(limit: int = 14) -> List[dict]:
    index = _load_json(REVIEW_INDEX_FILE, {})
    dates = (index.get('dates') or [])[:limit]
    trend = []
    for d in reversed(dates):
        review = _load_json(DAILY_REVIEWS_DIR / f'review_{d}.json', {})
        iq = (review.get('daily_summary') or {}).get('quality_iq')
        if iq is None:
            iq = (review.get('performance_summary') or {}).get('quality_iq')
        if iq is not None:
            trend.append({'date': d, 'quality_iq': iq})
    return trend[-7:]


def build_calibration_dashboard() -> dict:
    """Aggregate all Stats tab calibration sections."""
    from backend.analytics.confidence_calibration import get_confidence_calibration_payload
    from backend.analytics.signal_performance_tracker import (
        get_signal_type_performance,
        get_telegram_precision_analytics,
    )

    try:
        return {
            'status': 'ok',
            'market_day_performance': get_market_day_performance(),
            'confidence_calibration': get_confidence_calibration_payload(),
            'signal_type_performance': get_signal_type_performance(),
            'telegram_precision': get_telegram_precision_analytics(),
            'calibration_health': get_calibration_health_scores(),
            'adaptive_calibration': _get_adaptive_dashboard_safe(),
        }
    except Exception as e:
        return {
            'status': 'degraded',
            'reason': str(e),
            'market_day_performance': {'day_types': []},
            'confidence_calibration': {'numeric_buckets': [], 'bands': []},
            'signal_type_performance': {'categories': []},
            'telegram_precision': {},
            'calibration_health': {},
            'adaptive_calibration': {'status': 'empty'},
        }


def _get_adaptive_dashboard_safe() -> dict:
    try:
        from backend.adaptive.adaptive_calibration_engine import get_adaptive_dashboard_payload
        return get_adaptive_dashboard_payload()
    except Exception as e:
        return {'status': 'degraded', 'reason': str(e)}
