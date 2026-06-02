"""
Numeric + band confidence calibration analytics.

Measures whether AI confidence scores are statistically meaningful.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from backend.analytics.signal_outcomes import get_confidence_calibration, MIN_SAMPLES_CONF_BUCKET
from backend.storage.db_manager import get_connection, init_db

NUMERIC_BUCKETS = [
    ('0.8–1.0', 0.8, 1.01),
    ('0.6–0.8', 0.6, 0.8),
    ('0.4–0.6', 0.4, 0.6),
    ('0.0–0.4', 0.0, 0.4),
]


def _query_confidence_rows() -> List[dict]:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.confidence, e.confidence_band, h.hit_miss, h.change_pct
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE h.hit_miss IN ('HIT', 'MISS') AND e.confidence IS NOT NULL
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _normalize_confidence(value) -> Optional[float]:
    if value is None:
        return None
    try:
        c = float(value)
        if c > 1.0:
            c /= 10.0
        return max(0.0, min(1.0, c))
    except (TypeError, ValueError):
        return None


def get_numeric_confidence_calibration(min_samples: int = MIN_SAMPLES_CONF_BUCKET) -> dict:
    rows = _query_confidence_rows()
    buckets: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0, 'moves': []})

    for row in rows:
        conf = _normalize_confidence(row.get('confidence'))
        if conf is None:
            continue
        label = None
        for name, lo, hi in NUMERIC_BUCKETS:
            if lo <= conf < hi:
                label = name
                break
        if not label:
            continue
        if row['hit_miss'] == 'HIT':
            buckets[label]['hit'] += 1
        else:
            buckets[label]['miss'] += 1
        if row.get('change_pct') is not None:
            buckets[label]['moves'].append(float(row['change_pct']))

    calibration = []
    for name, lo, hi in NUMERIC_BUCKETS:
        stats = buckets.get(name) or {'hit': 0, 'miss': 0, 'moves': []}
        total = stats['hit'] + stats['miss']
        entry = {
            'bucket': name,
            'range_min': lo,
            'range_max': min(hi, 1.0),
            'samples': total,
            'accuracy_pct': round(stats['hit'] / total * 100, 1) if total else None,
            'avg_move_pct': round(sum(stats['moves']) / len(stats['moves']), 2) if stats['moves'] else None,
            'statistically_meaningful': total >= min_samples,
        }
        calibration.append(entry)

    meaningful = [c for c in calibration if c.get('statistically_meaningful') and c.get('accuracy_pct') is not None]
    realism_score = None
    if len(meaningful) >= 2:
        errors = []
        for c in meaningful:
            mid = (c['range_min'] + c['range_max']) / 2
            errors.append(abs(c['accuracy_pct'] / 100 - mid))
        realism_score = round(max(0.0, 1.0 - (sum(errors) / len(errors))) * 100, 1)

    return {
        'numeric_buckets': calibration,
        'confidence_realism_score': realism_score,
        'min_samples_required': min_samples,
    }


def get_confidence_calibration_payload() -> dict:
    """Combined band + numeric calibration for Stats dashboard."""
    band_data = get_confidence_calibration()
    numeric_data = get_numeric_confidence_calibration()
    return {
        'bands': band_data.get('bands') or [],
        'band_summary': band_data.get('summary') or {},
        'numeric_buckets': numeric_data.get('numeric_buckets') or [],
        'confidence_realism_score': numeric_data.get('confidence_realism_score'),
        'min_samples_required': band_data.get('min_samples_required', MIN_SAMPLES_CONF_BUCKET),
    }
