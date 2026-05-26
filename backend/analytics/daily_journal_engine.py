"""
Intelligence Journal — historical daily review memory for Hist tab.

Wraps daily review snapshots into journal cards. No external APIs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.config import DATA_DIR

DAILY_REVIEWS_DIR = DATA_DIR / 'daily_reviews'
REVIEW_INDEX_FILE = DAILY_REVIEWS_DIR / 'index.json'
JOURNAL_INDEX_FILE = DATA_DIR / 'intelligence_journal_index.json'


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


def _format_journal_card(review: dict) -> dict:
    if not review or review.get('status') == 'degraded':
        return {
            'date': review.get('date'),
            'status': 'degraded',
            'reason': review.get('reason', 'Review unavailable'),
            'copy_text': review.get('copy_text') or '',
        }

    classification = review.get('market_day_classification') or {}
    summary = review.get('daily_summary') or {}
    highlights = review.get('highlights') or {}
    tg = review.get('telegram') or {}
    perf = review.get('performance_summary') or {}
    regime = review.get('regime_analysis') or {}
    warnings = review.get('warnings') or []

    tg_sent = tg.get('alerts_sent', 0)
    tg_useful = tg.get('estimated_useful_alerts')
    if tg_useful is None and tg.get('telegram_precision_pct') and tg_sent:
        tg_useful = max(0, round(tg_sent * tg['telegram_precision_pct'] / 100))

    runtime_notes = []
    review_date = review.get('date')
    if review_date:
        try:
            from backend.analytics.provider_analytics import get_daily_runtime_notes
            runtime_notes = get_daily_runtime_notes(review_date)
        except Exception:
            runtime_notes = []

    return {
        'date': review.get('date'),
        'status': review.get('status', 'ok'),
        'day_type': classification.get('label') or summary.get('day_type'),
        'day_type_reason': classification.get('reason'),
        'regime': summary.get('regime') or regime.get('final_regime'),
        'quality_iq': summary.get('quality_iq'),
        'best_signal': (highlights.get('best_bullish') or {}).get('label') or summary.get('best_signal'),
        'best_bearish': (highlights.get('best_bearish') or {}).get('label'),
        'false_positive': (highlights.get('worst_false_positive') or {}).get('label'),
        'biggest_miss': (highlights.get('biggest_miss') or {}).get('label'),
        'highest_confidence_winner': (highlights.get('highest_confidence_winner') or {}).get('label'),
        'strongest_contradiction': highlights.get('strongest_contradiction'),
        'telegram_summary': f"{tg_useful or '?'}/{tg_sent} useful" if tg_sent else '—',
        'telegram_sent': tg_sent,
        'telegram_useful_est': tg_useful,
        'observation': review.get('observation') or '',
        'runtime_notes': runtime_notes,
        'runtime_summary': '\n'.join(runtime_notes) if runtime_notes else '',
        'regime_timeline': regime.get('timeline') or [],
        'warnings': warnings[:8],
        'highlights': highlights,
        'performance': {
            'signals': perf.get('signals_generated', 0),
            'useful': perf.get('useful_signals', 0),
            'false_positives': perf.get('false_positives', 0),
            'telegram_precision_pct': perf.get('telegram_precision_pct'),
        },
        'copy_text': review.get('copy_text') or '',
        'generated_at': review.get('generated_at'),
    }


def build_intelligence_journal(limit: int = 21, *, persist_index: bool = True) -> dict:
    """Build journal payload from persisted daily review snapshots."""
    from backend.analytics.daily_review_engine import build_daily_review, get_daily_review, list_review_dates

    index = _load_json(REVIEW_INDEX_FILE, {'dates': []})
    dates = list(index.get('dates') or [])

    if not dates:
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            build_daily_review(today, persist=True)
            dates = list_review_dates(limit)
        except Exception:
            dates = []

    entries = []
    for d in dates[:limit]:
        review = get_daily_review(d, rebuild=False)
        entries.append(_format_journal_card(review))

    payload = {
        'status': 'ok',
        'generated_at': datetime.now().isoformat(),
        'entries': entries,
        'dates': [e.get('date') for e in entries if e.get('date')],
        'latest': entries[0].get('date') if entries else None,
        'entry_count': len(entries),
    }

    if persist_index:
        from backend.storage.json_io import atomic_write_json
        atomic_write_json(JOURNAL_INDEX_FILE, {
            'updated_at': payload['generated_at'],
            'dates': payload['dates'],
            'latest': payload['latest'],
        })

    return payload


def get_journal_entry(review_date: str) -> dict:
    from backend.analytics.daily_review_engine import get_daily_review
    review = get_daily_review(review_date, rebuild=False)
    return _format_journal_card(review)
