"""
Rank and filter trading opportunities for Telegram /opps and brain pushes.

Enforces elite top-N limit, freshness, regime-aware quality, and ACTIVE/PENDING-only predictions.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

from backend.utils.config import ANALYSIS_STATE_FILE, DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
ACTIVE_PREDICTIONS_FILE = DATA_DIR / 'active_predictions.json'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'
ELITE_ALERTS_FILE = DATA_DIR / 'high_conviction_alerts.json'

DEFAULT_OPPS_LIMIT = int(os.environ.get('TELEGRAM_OPPS_LIMIT', '10'))
MAX_INTEL_AGE_HOURS = 24
ACTIVE_STATES = frozenset({'ACTIVE', 'PENDING'})
MIN_RANK_SCORE = 5.5
MIN_RANK_SCORE_PANIC = 11.0
ELITE_PROB_THRESHOLD = 0.72
PANIC_REGIMES = frozenset({'panic_volatile', 'macro_uncertainty', 'regime_transition'})
MACRO_CONFLICT_REGIMES = frozenset({'macro_uncertainty', 'regime_transition', 'panic_volatile'})

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
    pred_date = item.get('prediction_date') or item.get('date') or item.get('session_date')
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
    if 'VOLATILE' in india and action in ('BUY', 'LONG'):
        return 0.45
    return 0.3


def _load_quality_context(intel: dict) -> dict:
    ctx: dict = {
        'regime': '',
        'volatility_index': 0.0,
        'disagreement_score': 0.0,
        'safe_fallback_used': False,
        'schema_failures': 0,
    }
    if ANALYSIS_STATE_FILE.exists():
        try:
            state = json.loads(ANALYSIS_STATE_FILE.read_text(encoding='utf-8'))
            ctx['regime'] = str(state.get('last_regime') or '')
            qm = state.get('quality_metrics') or {}
            ctx['volatility_index'] = float(qm.get('volatility_index') or state.get('volatility_index') or 0)
            ctx['disagreement_score'] = float(
                qm.get('disagreement_score') or state.get('disagreement_score') or 0
            )
        except Exception:
            pass
    if not ctx['regime']:
        blob = ' '.join(
            str(intel.get(k) or '')
            for k in ('executive_summary', 'self_calibration', 'analysis')
        ).lower()
        if 'panic' in blob and 'volatile' in blob:
            ctx['regime'] = 'panic_volatile'
        elif 'macro uncertainty' in blob:
            ctx['regime'] = 'macro_uncertainty'
        elif 'regime transition' in blob:
            ctx['regime'] = 'regime_transition'
    try:
        from backend.ai.pipeline_observability import get_observability_summary
        obs = get_observability_summary() or {}
        rel = obs.get('reliability_execution') or {}
        ctx['safe_fallback_used'] = int(rel.get('safe_fallbacks') or 0) > 0
        ctx['schema_failures'] = int(rel.get('schema_failures') or 0)
        if not ctx['disagreement_score']:
            expl = obs.get('explanations') or {}
            ctx['disagreement_score'] = float(expl.get('disagreement_score') or 0)
    except Exception:
        pass
    return ctx


def _load_scanner_index() -> Dict[str, dict]:
    if not SCANNER_FILE.exists():
        return {}
    try:
        data = json.loads(SCANNER_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}
    index: Dict[str, dict] = {}
    for key in ('ultra_bullish', 'strong_bullish', 'moderate_bullish', 'ultra_bearish', 'strong_bearish'):
        for row in data.get(key) or []:
            if isinstance(row, dict):
                sym = str(row.get('ticker') or row.get('symbol') or '').upper()
                if sym:
                    index[sym] = {**row, '_bucket': key}
    for row in data.get('signals') or data.get('stocks') or []:
        if isinstance(row, dict):
            sym = str(row.get('ticker') or row.get('symbol') or '').upper()
            if sym and sym not in index:
                index[sym] = row
    return index


def _volume_anomaly_boost(item: dict, scanner_index: Dict[str, dict]) -> float:
    sym = str(item.get('symbol') or item.get('ticker') or '').upper()
    scan = scanner_index.get(sym) or {}
    try:
        vol_ratio = float(scan.get('volume_ratio') or scan.get('vol_ratio') or 0)
    except (TypeError, ValueError):
        vol_ratio = 0.0
    strength = str(scan.get('strength') or scan.get('_bucket') or '').upper()
    boost = 0.0
    if vol_ratio >= 5:
        boost += 2.5
    elif vol_ratio >= 3:
        boost += 1.5
    elif vol_ratio >= 2:
        boost += 0.8
    if 'ULTRA' in strength:
        boost += 1.5
    elif 'STRONG' in strength:
        boost += 0.8
    logic = str(item.get('logic') or item.get('signal_type') or '').upper()
    if 'ULTRA' in logic:
        boost += 0.5
    return boost


def _sector_strength_boost(item: dict, intel: dict, scanner_index: Dict[str, dict]) -> float:
    rotation = intel.get('sector_rotation') if isinstance(intel.get('sector_rotation'), dict) else {}
    bullish = [str(s).upper() for s in (rotation.get('bullish') or [])]
    bearish = [str(s).upper() for s in (rotation.get('bearish') or [])]
    sym = str(item.get('symbol') or item.get('ticker') or '').upper()
    sector = str(item.get('sector') or (scanner_index.get(sym) or {}).get('sector') or '').upper()
    action = str(item.get('action') or '').upper()

    def _in_list(sectors: List[str]) -> bool:
        if not sector:
            return False
        return any(s in sector or sector in s for s in sectors)

    if action in ('BUY', 'LONG', 'OPPORTUNITY'):
        if _in_list(bullish):
            return 1.8
        if _in_list(bearish):
            return -2.5
    if action in ('SELL', 'SHORT'):
        if _in_list(bearish):
            return 1.5
        if _in_list(bullish):
            return -2.0
    return 0.0


def _multi_source_boost(item: dict) -> float:
    sources = item.get('sources') or item.get('confirmation_sources') or []
    logic = str(item.get('logic') or item.get('signal_type') or '').lower()
    boost = 0.0
    if isinstance(sources, list) and len(sources) >= 2:
        boost += 1.0 + 0.25 * min(len(sources), 4)
    hits = sum(1 for token in ('govt', 'scanner', 'news', 'reddit', 'volume') if token in logic)
    if hits >= 2:
        boost += 1.2
    if item.get('_source') == 'active_predictions' and str(item.get('state') or '').upper() == 'ACTIVE':
        boost += 0.9
    if re.search(r'\bultra\b', logic):
        boost += 0.4
    return boost


def _contradiction_penalty(item: dict, ctx: dict) -> float:
    disagree = float(ctx.get('disagreement_score') or 0)
    item_contra = float(item.get('contradiction_severity') or 0)
    penalty = disagree * 4.5 + item_contra * 3.5
    logic = str(item.get('logic') or '').lower()
    if disagree >= 0.35:
        penalty += 1.2
    if disagree >= 0.45 and 'watch' in logic:
        penalty += 2.0
    if disagree >= 0.55 and _confidence_score(item.get('confidence')) >= 4:
        penalty += 2.5
    return penalty


def _macro_conflict_penalty(item: dict, ctx: dict) -> float:
    regime = str(ctx.get('regime') or '')
    if regime not in MACRO_CONFLICT_REGIMES:
        return 0.0
    action = str(item.get('action') or '').upper()
    penalty = 0.0
    if action in ('BUY', 'LONG', 'OPPORTUNITY') and regime == 'macro_uncertainty':
        penalty += 2.0
    if action in ('BUY', 'LONG') and regime == 'panic_volatile':
        penalty += 2.8
    if 'govt' not in str(item.get('logic') or '').lower() and regime == 'macro_uncertainty':
        penalty += 0.8
    return penalty


def _hallucination_penalty(item: dict, ctx: dict) -> float:
    penalty = 0.0
    if ctx.get('safe_fallback_used'):
        penalty += 1.8
    if int(ctx.get('schema_failures') or 0) > 0:
        penalty += 1.2
    logic = str(item.get('logic') or '').lower()
    if not logic or logic in ('no rationale provided.', 'signal'):
        penalty += 0.8
    return penalty


def _panic_overextension_penalty(item: dict, ctx: dict, scanner_index: Dict[str, dict]) -> float:
    regime = str(ctx.get('regime') or '')
    if regime not in PANIC_REGIMES:
        return 0.0
    sym = str(item.get('symbol') or item.get('ticker') or '').upper()
    scan = scanner_index.get(sym) or {}
    try:
        change = abs(float(scan.get('change_percent') or scan.get('change_pct') or 0))
    except (TypeError, ValueError):
        change = 0.0
    penalty = 0.0
    if change >= 9:
        penalty += 2.5
    elif change >= 6:
        penalty += 1.2
    if _confidence_score(item.get('confidence')) <= 3:
        penalty += 2.5
    return penalty


def _passes_elite_gate(item: dict, intel: dict, ctx: dict, scanner_index: Dict[str, dict]) -> bool:
    """Hard gate — weak setups never reach Telegram even if they sort high."""
    score = _rank_score(item, intel, _parse_ts(intel.get('timestamp')), ctx, scanner_index)
    regime = str(ctx.get('regime') or '')
    if regime not in PANIC_REGIMES:
        return score >= MIN_RANK_SCORE

    if _confidence_score(item.get('confidence')) < 4.0:
        return False

    vol_boost = _volume_anomaly_boost(item, scanner_index)
    sector_boost = _sector_strength_boost(item, intel, scanner_index)
    multi_boost = _multi_source_boost(item)
    strong_evidence = vol_boost >= 1.0 or sector_boost >= 1.0 or multi_boost >= 1.2
    if not strong_evidence:
        return False

    if float(ctx.get('disagreement_score') or 0) >= 0.4 and vol_boost < 1.5:
        return False

    return score >= MIN_RANK_SCORE_PANIC


def _rank_score(
    item: dict,
    intel: dict,
    intel_ts: Optional[datetime],
    ctx: dict,
    scanner_index: Dict[str, dict],
) -> float:
    base = (
        _confidence_score(item.get('confidence')) * 3.0
        + _impact_score(item) * 2.0
        + _freshness_score(item, intel_ts) * 2.5
        + _regime_alignment(item, intel) * 1.5
        + _volume_anomaly_boost(item, scanner_index)
        + _sector_strength_boost(item, intel, scanner_index)
        + _multi_source_boost(item)
    )
    penalties = (
        _contradiction_penalty(item, ctx)
        + _hallucination_penalty(item, ctx)
        + _panic_overextension_penalty(item, ctx, scanner_index)
        + _macro_conflict_penalty(item, ctx)
    )
    vol = float(ctx.get('volatility_index') or 0)
    if vol > 0.55:
        base *= max(0.78, 1.0 - (vol - 0.55) * 0.35)
    if str(ctx.get('regime') or '') in PANIC_REGIMES:
        base *= 0.80
        if _confidence_score(item.get('confidence')) >= 4:
            penalties += 1.5
    return max(0.0, base - penalties)


def _load_elite_index() -> Tuple[Dict[str, dict], bool]:
    """Symbol index from meta-labeler output; second value = file exists."""
    if not ELITE_ALERTS_FILE.exists():
        return {}, False
    try:
        data = json.loads(ELITE_ALERTS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}, False
    index: Dict[str, dict] = {}
    for row in data.get('elite_signals') or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get('symbol') or row.get('Stock') or row.get('ticker') or '').upper()
        if sym:
            index[sym] = row
    return index, True


def _align_display_confidence(item: dict, elite_index: Dict[str, dict]) -> dict:
    """Synchronize scanner labels with meta-labeler elite gate (>72%)."""
    sym = str(item.get('symbol') or item.get('ticker') or '').upper()
    raw_conf = str(item.get('confidence') or 'MEDIUM').strip().upper()
    elite = elite_index.get(sym)

    if elite:
        item['elite_verified'] = True
        item['display_confidence'] = 'HIGH'
        item['below_elite_threshold'] = False
        item['ml_confidence'] = elite.get('ml_confidence')
        item.pop('confidence_note', None)
        return item

    item['elite_verified'] = False
    if raw_conf in ('HIGH', 'ULTRA'):
        item['display_confidence'] = 'WATCHLIST'
        item['below_elite_threshold'] = True
        item['confidence_note'] = 'Below elite threshold (>72%)'
    elif raw_conf in ('MEDIUM', 'MODERATE'):
        item['display_confidence'] = 'MEDIUM'
        item['below_elite_threshold'] = False
    elif raw_conf in ('LOW', 'WATCH'):
        item['display_confidence'] = 'SPECULATIVE'
        item['below_elite_threshold'] = False
    else:
        item['display_confidence'] = raw_conf or 'MEDIUM'
        item['below_elite_threshold'] = False
    return item


def elite_alignment_summary(opps: List[dict]) -> dict:
    verified = sum(1 for o in opps if o.get('elite_verified'))
    watchlist = sum(1 for o in opps if o.get('below_elite_threshold'))
    return {
        'elite_verified_count': verified,
        'watchlist_count': watchlist,
        'has_elite_verified': verified > 0,
        'all_below_elite': verified == 0 and len(opps) > 0,
    }


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
            'sector': p.get('sector'),
            'signal_type': p.get('signal_type'),
        }, 'active_predictions'))
    return out


def _load_intel_opportunities(intel: dict) -> List[dict]:
    opps = intel.get('top_opportunities')
    if opps is None:
        opps = intel.get('opportunities')
    if not isinstance(opps, list):
        return []
    return [_normalize_opp(o, 'intelligence') for o in opps if isinstance(o, dict)]


def _load_scanner_ultra_candidates() -> List[dict]:
    """Seed ranked pool with scanner ULTRA anomalies (still subject to elite gates)."""
    if not SCANNER_FILE.exists():
        return []
    try:
        data = json.loads(SCANNER_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []
    out: List[dict] = []
    for sig in data.get('top_signals') or []:
        if not isinstance(sig, dict):
            continue
        if str(sig.get('strength') or '').upper() != 'ULTRA':
            continue
        ticker = str(sig.get('ticker') or '').upper()
        if not ticker:
            continue
        out.append(_normalize_opp({
            'symbol': ticker,
            'ticker': ticker,
            'action': 'WATCH',
            'confidence': 'MEDIUM',
            'logic': (
                f"Scanner ULTRA · vol {sig.get('volume_ratio', '?')}x · "
                f"{sig.get('change_percent', 0)}% move"
            ),
            'sector': sig.get('sector'),
            'signal_type': 'scanner_ultra',
            'display_tier': 'TACTICAL',
        }, 'scanner_ultra'))
    return out


def _load_intel(intel: Optional[dict]) -> dict:
    if intel is not None:
        return intel if isinstance(intel, dict) else {}
    try:
        from backend.intelligence.active_snapshot import get_canonical_intelligence
        return get_canonical_intelligence()
    except Exception:
        pass
    if INTEL_FILE.exists():
        try:
            return json.loads(INTEL_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def rank_opportunities(
    intel: Optional[dict] = None,
    *,
    limit: int = DEFAULT_OPPS_LIMIT,
    include_active: bool = True,
) -> List[dict]:
    """Return elite top-N ranked opportunities — fresh, high-conviction only."""
    intel = _load_intel(intel)
    intel_ts = _parse_ts(intel.get('timestamp') or intel.get('generation_time'))
    ctx = _load_quality_context(intel)
    scanner_index = _load_scanner_index()
    score_fn = lambda item: _rank_score(item, intel, intel_ts, ctx, scanner_index)

    merged: Dict[str, dict] = {}
    for item in _load_intel_opportunities(intel):
        sym = item['symbol']
        merged[sym] = item

    if include_active:
        for item in _load_active_opportunities():
            sym = item['symbol']
            if sym not in merged or score_fn(item) > score_fn(merged[sym]):
                merged[sym] = item

    for item in _load_scanner_ultra_candidates():
        sym = item['symbol']
        if sym not in merged or score_fn(item) > score_fn(merged[sym]):
            merged[sym] = item

    ranked = sorted(merged.values(), key=score_fn, reverse=True)

    filtered = [
        x for x in ranked
        if _freshness_score(x, intel_ts) > 0 and _passes_elite_gate(x, intel, ctx, scanner_index)
    ]

    elite = filtered[: max(1, int(limit))]
    elite_index, _ = _load_elite_index()
    for item in elite:
        item['_rank_score'] = round(score_fn(item), 2)
        _align_display_confidence(item, elite_index)
        if item.get('elite_verified'):
            item['display_tier'] = 'ELITE'
        elif item.get('below_elite_threshold'):
            item['display_tier'] = 'WATCHLIST'
        elif not item.get('display_tier'):
            item['display_tier'] = 'TACTICAL'
    return elite


def _passes_tactical_gate(item: dict, intel: dict, ctx: dict, scanner_index: Dict[str, dict]) -> bool:
    """Lighter gate for scanner-led tactical plays (below elite ML threshold)."""
    if str(item.get('signal_type') or '') == 'scanner_ultra':
        return True
    if str(item.get('_source') or '') == 'scanner_ultra':
        return True
    sym = str(item.get('symbol') or '').upper()
    scan = scanner_index.get(sym) or {}
    if str(scan.get('strength') or '').upper() == 'ULTRA':
        return True
    score = _rank_score(item, intel, _parse_ts(intel.get('timestamp')), ctx, scanner_index)
    sector_boost = _sector_strength_boost(item, intel, scanner_index)
    vol_boost = _volume_anomaly_boost(item, scanner_index)
    if sector_boost >= 0.8 and vol_boost >= 0.5:
        return score >= max(4.0, MIN_RANK_SCORE * 0.55)
    return score >= MIN_RANK_SCORE * 0.65


def rank_opportunities_tiered(
    intel: Optional[dict] = None,
    *,
    limit: int = DEFAULT_OPPS_LIMIT,
) -> Dict[str, List[dict]]:
    """
    Split opportunities into ELITE / TACTICAL / WATCHLIST tiers.
    Scanner ULTRA anomalies always populate TACTICAL when elite gate excludes them.
    """
    intel = _load_intel(intel)
    intel_ts = _parse_ts(intel.get('timestamp') or intel.get('generation_time'))
    ctx = _load_quality_context(intel)
    scanner_index = _load_scanner_index()
    score_fn = lambda item: _rank_score(item, intel, intel_ts, ctx, scanner_index)
    elite_index, _ = _load_elite_index()

    merged: Dict[str, dict] = {}
    for item in _load_intel_opportunities(intel):
        merged[item['symbol']] = item
    for item in _load_active_opportunities():
        sym = item['symbol']
        if sym not in merged or score_fn(item) > score_fn(merged[sym]):
            merged[sym] = item
    for item in _load_scanner_ultra_candidates():
        sym = item['symbol']
        if sym not in merged or score_fn(item) > score_fn(merged[sym]):
            merged[sym] = item

    ranked = sorted(merged.values(), key=score_fn, reverse=True)
    fresh = [x for x in ranked if _freshness_score(x, intel_ts) > 0]

    elite: List[dict] = []
    tactical: List[dict] = []
    watchlist: List[dict] = []
    seen: set = set()

    for item in fresh:
        sym = item['symbol']
        if sym in seen:
            continue
        _align_display_confidence(item, elite_index)
        item['_rank_score'] = round(score_fn(item), 2)

        if item.get('elite_verified'):
            item['display_tier'] = 'ELITE'
            elite.append(item)
            seen.add(sym)
            continue

        if _passes_elite_gate(item, intel, ctx, scanner_index):
            if item.get('below_elite_threshold'):
                item['display_tier'] = 'WATCHLIST'
                watchlist.append(item)
            else:
                item['display_tier'] = 'TACTICAL'
                tactical.append(item)
            seen.add(sym)
            continue

        if _passes_tactical_gate(item, intel, ctx, scanner_index):
            item['display_tier'] = 'TACTICAL'
            tactical.append(item)
            seen.add(sym)
            continue

        if score_fn(item) >= MIN_RANK_SCORE * 0.45:
            item['display_tier'] = 'WATCHLIST'
            watchlist.append(item)
            seen.add(sym)

    cap = max(1, int(limit))
    try:
        from backend.trading.tactical_trade_engine import attach_tactical_plans
        from backend.analytics.confidence_hierarchy import normalize_confidence
        tactical = attach_tactical_plans(tactical, scanner_index, intel)
        watchlist = attach_tactical_plans(watchlist, scanner_index, intel)
        for bucket in (elite, tactical, watchlist):
            for item in bucket:
                norm = normalize_confidence(item)
                item['confidence_hierarchy'] = norm
                item['display_confidence'] = norm.get('display_label') or item.get('display_confidence')
    except Exception:
        pass
    return {
        'elite': elite[:cap],
        'tactical': tactical[:cap],
        'watchlist': watchlist[:cap],
        'all': (elite + tactical + watchlist)[: cap * 3],
    }
