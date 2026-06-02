"""
Signal-type performance tracking for calibration dashboard.

Maps internal signal types to operator-friendly categories.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List, Optional

from backend.storage.db_manager import get_connection, init_db
from backend.utils.config import DATA_DIR, TELEGRAM_ALERT_OBS_FILE

MIN_SAMPLES = 5

SIGNAL_CATEGORY_RULES = [
    ('ULTRA breakouts', lambda r: r.get('signal_type') == 'scanner' and _is_ultra(r)),
    ('Scanner anomalies', lambda r: r.get('signal_type') == 'scanner'),
    ('Momentum continuation', lambda r: r.get('signal_type') == 'ai_opportunity' and _directional(r)),
    ('Reversals', lambda r: _has_tag(r, 'REVERSAL') or _has_tag(r, 'MEAN_REVERSION')),
    ('Bearish breakdowns', lambda r: str(r.get('direction') or '').upper() == 'BEARISH'),
    ('Macro alerts', lambda r: r.get('signal_type') == 'telegram' and _is_macro(r)),
    ('Telegram alerts', lambda r: r.get('signal_type') == 'telegram'),
    ('Regime shifts', lambda r: r.get('signal_type') == 'regime'),
]


def _load_json(path, default=None):
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


def _parse_metadata(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _is_ultra(row: dict) -> bool:
    summary = str(row.get('reasoning_summary') or '').upper()
    meta = _parse_metadata(row.get('metadata'))
    return 'ULTRA' in summary or meta.get('strength') == 'ULTRA'


def _directional(row: dict) -> bool:
    return str(row.get('direction') or '').upper() in ('BULLISH', 'BEARISH')


def _has_tag(row: dict, tag: str) -> bool:
    meta = _parse_metadata(row.get('metadata'))
    tags = meta.get('signal_types') or meta.get('tags') or []
    if isinstance(tags, str):
        tags = [tags]
    return tag in [str(t).upper() for t in tags]


def _is_macro(row: dict) -> bool:
    summary = str(row.get('reasoning_summary') or '').upper()
    return any(k in summary for k in ('MACRO', 'RBI', 'GOVT', 'POLICY', 'EMERGENCY'))


def _query_rows() -> List[dict]:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.signal_type, e.direction, e.reasoning_summary, e.metadata AS metadata,
                   h.hit_miss, h.change_pct
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE h.hit_miss IN ('HIT', 'MISS', 'NEUTRAL')
            """
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['metadata'] = d.get('metadata')
            out.append(d)
        return out
    finally:
        conn.close()


def get_signal_type_performance(min_samples: int = MIN_SAMPLES) -> dict:
    rows = _query_rows()
    categories: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0, 'moves': []})
    assigned = set()

    for label, matcher in SIGNAL_CATEGORY_RULES:
        for idx, row in enumerate(rows):
            if idx in assigned:
                continue
            if not matcher(row):
                continue
            assigned.add(idx)
            cat = categories[label]
            if row['hit_miss'] == 'HIT':
                cat['hit'] += 1
            elif row['hit_miss'] == 'MISS':
                cat['miss'] += 1
            if row.get('change_pct') is not None:
                cat['moves'].append(float(row['change_pct']))

    by_internal: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0, 'moves': []})
    for row in rows:
        st = row.get('signal_type') or 'unknown'
        if row['hit_miss'] == 'HIT':
            by_internal[st]['hit'] += 1
        elif row['hit_miss'] == 'MISS':
            by_internal[st]['miss'] += 1
        if row.get('change_pct') is not None:
            by_internal[st]['moves'].append(float(row['change_pct']))

    table = []
    for label, stats in categories.items():
        evaluated = stats['hit'] + stats['miss']
        if evaluated < min_samples:
            continue
        table.append({
            'category': label,
            'samples': evaluated,
            'accuracy_pct': round(stats['hit'] / evaluated * 100, 1),
            'avg_move_pct': round(sum(stats['moves']) / len(stats['moves']), 2) if stats['moves'] else 0,
            'statistically_meaningful': evaluated >= min_samples,
        })

    internal = []
    for st, stats in by_internal.items():
        evaluated = stats['hit'] + stats['miss']
        if evaluated < min_samples:
            continue
        internal.append({
            'signal_type': st,
            'samples': evaluated,
            'accuracy_pct': round(stats['hit'] / evaluated * 100, 1),
            'avg_move_pct': round(sum(stats['moves']) / len(stats['moves']), 2) if stats['moves'] else 0,
        })

    return {
        'categories': sorted(table, key=lambda x: x['accuracy_pct'], reverse=True),
        'by_signal_type': sorted(internal, key=lambda x: x['samples'], reverse=True),
        'min_samples_required': min_samples,
    }


def get_telegram_precision_analytics() -> dict:
    """Telegram filter effectiveness — measures usefulness, not spam volume."""
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT h.hit_miss FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE e.signal_type = 'telegram' AND h.hit_miss IN ('HIT', 'MISS')
            """
        ).fetchall()
    finally:
        conn.close()

    hits = sum(1 for r in rows if r['hit_miss'] == 'HIT')
    evaluated = len(rows)
    useful_pct = round(hits / evaluated * 100, 1) if evaluated >= 5 else None

    obs = _load_json(TELEGRAM_ALERT_OBS_FILE, {})
    sent = len(obs.get('sent_today') or obs.get('recent_sent') or [])
    suppressed = obs.get('suppressed_today') or obs.get('recent_suppressed') or []
    dupes = sum(1 for s in suppressed if s.get('reason') == 'duplicate')
    low_conf = sum(1 for s in suppressed if 'confidence' in str(s.get('reason', '')).lower())
    cooldown = sum(1 for s in suppressed if s.get('reason') == 'cooldown')
    total_blocks = len(suppressed)

    return {
        'useful_alerts_pct': useful_pct,
        'alerts_sent_today': sent,
        'alerts_suppressed_today': total_blocks,
        'suppression_effectiveness_pct': (
            round(total_blocks / max(1, total_blocks + sent) * 100, 1) if (total_blocks + sent) else None
        ),
        'duplicate_prevention': dupes,
        'low_confidence_filter': low_conf,
        'cooldown_blocks': cooldown,
        'spam_avoided_est': total_blocks,
        'samples_evaluated': evaluated,
    }
