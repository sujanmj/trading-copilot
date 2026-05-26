"""
Rank and filter trading opportunities for Telegram /opps and brain pushes.

Enforces top-N limit, freshness, and ACTIVE/PENDING-only predictions.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
ACTIVE_PREDICTIONS_FILE = DATA_DIR / 'active_predictions.json'

DEFAULT_OPPS_LIMIT = 20
MAX_INTEL_AGE_HOURS = 24
ACTIVE_STATES = frozenset({'ACTIVE', 'PENDING'})

CONFIDENCE_RANK = {
    'ULTRA': 5,
    'HIGH': 4,
    'MEDIUM': 3,
    'LOW': 2,
    'WATCH': 1,
}


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        if isinstance(value, str) and 'T' in value:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(str(value)[:19], '%Y-%m-%d %H:%M:%S')
            dt = IST.localize(dt) if dt.tzinfo is None else dt
        return dt
    except Exception:
        return None


def _confidence_score(value: Any) -> float:
    if value is None:
        return 2.0
    key = str(value).strip().upper()
    return float(CONFIDENCE_RANK.get(key, 2))


def _impact_score(item: dict) -> float:
    for key in ('impact', 'impact_score', 'score', 'conviction'):
        val = item.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return 0.0


def _freshness_score(item: dict, intel_ts: Optional[datetime]) -> float:
    pred_date = item.get('prediction_date') or item.get('date')
    if pred_date:
        try:
            pd = datetime.strptime(str(pred_date)[:10], '%Y-%m-%d').date()
            age_days = (datetime.now(IST).date() - pd).days
            if age_days > 3:
                return 0.0
            return max(0.0, 3.0 - age_days)
        except ValueError:
            pass
    if intel_ts:
        age_h = (datetime.now(IST) - intel_ts.astimezone(IST)).total_seconds() / 3600
        if age_h > MAX_INTEL_AGE_HOURS:
            return 0.0
        return max(0.0, 3.0 - age_h / 8)
    return 1.0


def _regime_alignment(item: dict, intel: dict) -> float:
    mood = intel.get('market_mood') if isinstance(intel.get('market_mood'), dict) else {}
    india = str(mood.get('india_outlook') or mood.get('global_mood') or '').upper()
    action = str(item.get('action') or item.get('category') or '').upper()
    if not india or india == 'NEUTRAL':
        return 0.5
    if action in ('BUY', 'OPPORTUNITY', 'LONG') and 'BULL' in india:
        return 1.0
    if action in ('SELL', 'SHORT', 'RISK') and 'BEAR' in india:
        return 1.0
    if action in ('WATCH', 'MEDIUM'):
        return 0.6
    return 0.3


def _rank_score(item: dict, intel: dict, intel_ts: Optional[datetime]) -> float:
    return (
        _confidence_score(item.get('confidence')) * 3.0
        + _impact_score(item) * 2.0
        + _freshness_score(item, intel_ts) * 2.5
        + _regime_alignment(item, intel) * 1.5
    )


def _normalize_opp(item: dict, source: str) -> dict:
    sym = item.get('symbol') or item.get('ticker') or 'UNKNOWN'
    out = dict(item)
    out['symbol'] = str(sym).upper()
    out['_source'] = source
    return out


def _load_active_opportunities() -> List[dict]:
    if not ACTIVE_PREDICTIONS_FILE.exists():
        return []
    try:
        data = json.loads(ACTIVE_PREDICTIONS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []
    preds = data.get('predictions') or []
    out = []
    today = datetime.now(IST).date()
    for p in preds:
        if not isinstance(p, dict):
            continue
        state = str(p.get('state') or '').upper()
        if state and state not in ACTIVE_STATES:
            continue
        cat = str(p.get('category') or '').lower()
        if cat == 'risk':
            continue
        pd = p.get('prediction_date')
        if pd:
            try:
                if datetime.strptime(str(pd)[:10], '%Y-%m-%d').date() < today - timedelta(days=3):
                    continue
            except ValueError:
                pass
        out.append(_normalize_opp({
            'symbol': p.get('ticker'),
            'action': 'BUY' if cat in ('opportunity', 'elite', 'long') else 'WATCH',
            'confidence': p.get('confidence'),
            'entry_zone': p.get('entry_price'),
            'target': p.get('target_price'),
            'stop_loss': p.get('stop_loss'),
            'logic': p.get('signal_type') or p.get('category'),
            'prediction_date': pd,
            'state': state or 'ACTIVE',
        }, 'active_predictions'))
    return out


def _load_intel_opportunities(intel: dict) -> List[dict]:
    opps = intel.get('top_opportunities')
    if opps is None:
        opps = intel.get('opportunities')
    if not isinstance(opps, list):
        return []
    return [_normalize_opp(o, 'intelligence') for o in opps if isinstance(o, dict)]


def rank_opportunities(
    intel: Optional[dict] = None,
    *,
    limit: int = DEFAULT_OPPS_LIMIT,
    include_active: bool = True,
) -> List[dict]:
    """Return top-N ranked opportunities — fresh, active only."""
    if intel is None:
        if INTEL_FILE.exists():
            try:
                intel = json.loads(INTEL_FILE.read_text(encoding='utf-8'))
            except Exception:
                intel = {}
        else:
            intel = {}

    intel = intel if isinstance(intel, dict) else {}
    intel_ts = _parse_ts(intel.get('timestamp') or intel.get('generation_time'))

    merged: Dict[str, dict] = {}
    for item in _load_intel_opportunities(intel):
        sym = item['symbol']
        merged[sym] = item

    if include_active:
        for item in _load_active_opportunities():
            sym = item['symbol']
            if sym not in merged or _rank_score(item, intel, intel_ts) > _rank_score(merged[sym], intel, intel_ts):
                merged[sym] = item

    ranked = sorted(
        merged.values(),
        key=lambda x: _rank_score(x, intel, intel_ts),
        reverse=True,
    )

    filtered = [x for x in ranked if _freshness_score(x, intel_ts) > 0 or _rank_score(x, intel, intel_ts) >= 4]
    return filtered[: max(1, int(limit))]
