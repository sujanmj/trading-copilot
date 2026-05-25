"""
Daily Intelligence Review Engine — end-of-day strategic summary.

Aggregates existing SQLite + JSON signals only. No external APIs.
Separates strategic review from OPS debug observability.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.storage.db_manager import get_connection, init_db
from backend.storage.json_io import atomic_write_json
from backend.utils.config import (
    ANALYSIS_EXPLANATIONS_FILE,
    ANALYSIS_STATE_FILE,
    DATA_DIR,
    MARKET_SOURCE_STATUS_FILE,
    TELEGRAM_ALERT_OBS_FILE,
)

DAILY_REVIEWS_DIR = DATA_DIR / 'daily_reviews'
REVIEW_INDEX_FILE = DAILY_REVIEWS_DIR / 'index.json'
EXECUTION_METRICS_FILE = DATA_DIR / 'execution_metrics.json'
INTELLIGENCE_FILE = DATA_DIR / 'unified_intelligence.json'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'

MIN_SAMPLES_OBSERVATION = 5


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_features(review_date: str) -> dict:
    state = _load_json(ANALYSIS_STATE_FILE, {})
    intel = _load_json(INTELLIGENCE_FILE, {})
    scanner = _load_json(SCANNER_FILE, {})
    explanations = _load_json(ANALYSIS_EXPLANATIONS_FILE, {})
    market_src = _load_json(MARKET_SOURCE_STATUS_FILE, {})
    latest_q = (explanations.get('latest') or {}).get('quality') or state.get('quality_metrics') or {}

    signals = scanner.get('top_signals') or []
    changes = [_safe_float(s.get('change_percent')) for s in signals if isinstance(s, dict)]
    vol_ratios = [_safe_float(s.get('volume_ratio'), 1.0) for s in signals if isinstance(s, dict)]
    bullish = sum(1 for s in signals if str(s.get('direction', '')).upper() == 'BULLISH')
    bearish = sum(1 for s in signals if str(s.get('direction', '')).upper() == 'BEARISH')
    total_sig = max(1, len(signals))

    sectors = intel.get('sector_rotation') or {}
    govt_count = _safe_float(state.get('metrics', {}).get('govt_high_impact'))
    news_count = _safe_float(state.get('metrics', {}).get('news_count'))

    return {
        'review_date': review_date,
        'regime': state.get('last_regime') or 'unknown',
        'volatility_index': _safe_float(state.get('volatility_index'), 0.4),
        'disagreement_score': _safe_float(state.get('disagreement_score'), 0.0),
        'sentiment_diversity': _safe_float(latest_q.get('sentiment_diversity_score'), 0.5),
        'quality_iq': _safe_float(latest_q.get('intelligence_quality_score')),
        'breadth': abs(bullish - bearish) / total_sig,
        'scanner_dispersion': (
            (max(changes) - min(changes)) if len(changes) >= 2 else 0.0
        ),
        'avg_volume_ratio': sum(vol_ratios) / len(vol_ratios) if vol_ratios else 1.0,
        'macro_pressure': min(1.0, (govt_count / 5.0) + (news_count / 30.0)),
        'market_source_degraded': bool(market_src.get('degraded')),
        'delta_reasons': state.get('last_delta_reasons') or [],
        'india_avg_change': _safe_float(state.get('metrics', {}).get('india_avg_change')),
    }


def classify_market_day(features: dict) -> dict:
    """Rule-based day classification from existing intelligence signals."""
    vol = features.get('volatility_index', 0.4)
    disagree = features.get('disagreement_score', 0.0)
    regime = features.get('regime', 'unknown')
    breadth = features.get('breadth', 0.0)
    dispersion = features.get('scanner_dispersion', 0.0)
    avg_vol = features.get('avg_volume_ratio', 1.0)
    macro = features.get('macro_pressure', 0.0)
    india_chg = abs(features.get('india_avg_change', 0.0))

    dt = datetime.strptime(features['review_date'], '%Y-%m-%d')
    is_thursday = dt.weekday() == 3
    is_month_end = dt.day >= 25

    scores: List[Tuple[str, float, str]] = []

    if vol >= 0.62 and disagree >= 0.48:
        scores.append(('PANIC VOLATILE', 0.95, 'High volatility with elevated contradictions'))
    if regime in ('panic_volatile', 'macro_uncertainty'):
        scores.append(('PANIC VOLATILE', 0.88, f'Regime flagged as {regime}'))
    if regime == 'regime_transition':
        scores.append(('REGIME TRANSITION', 0.92, 'Active regime transition detected'))
    if macro >= 0.55 or 'govt_change' in features.get('delta_reasons', []):
        scores.append(('MACRO SHOCK', 0.85, 'Elevated macro/news pressure'))
    if is_thursday or (is_month_end and is_thursday):
        scores.append(('EXPIRY VOLATILITY', 0.75, 'Expiry-week session dynamics'))
    if avg_vol < 0.85 and dispersion < 1.2 and vol < 0.42:
        scores.append(('LOW LIQUIDITY', 0.7, 'Muted volume and narrow scanner dispersion'))
    if india_chg >= 0.8 and breadth >= 0.35:
        scores.append(('TRENDING DAY', 0.82, 'Directional breadth with meaningful index move'))
    if vol < 0.48 and dispersion < 2.0 and breadth < 0.35:
        scores.append(('SIDEWAYS CHOP', 0.78, 'Low volatility range-bound action'))

    if not scores:
        label = 'MIXED SESSION'
        reason = 'No dominant day archetype — blended signals'
        confidence = 0.5
    else:
        scores.sort(key=lambda x: x[1], reverse=True)
        label, confidence, reason = scores[0]

    return {
        'label': label,
        'confidence': round(confidence, 2),
        'reason': reason,
        'regime': regime,
        'drivers': {
            'volatility': round(vol, 2),
            'contradiction_intensity': round(disagree, 2),
            'scanner_dispersion': round(dispersion, 2),
            'breadth': round(breadth, 2),
            'macro_pressure': round(macro, 2),
            'avg_volume_ratio': round(avg_vol, 2),
        },
    }


def _signal_stats_for_date(review_date: str) -> dict:
    init_db()
    conn = get_connection()
    try:
        events = conn.execute(
            "SELECT COUNT(*) AS c FROM signal_events WHERE event_date = ?",
            (review_date,),
        ).fetchone()
        high_conf = conn.execute(
            """
            SELECT COUNT(*) AS c FROM signal_events
            WHERE event_date = ? AND confidence_band = 'HIGH'
            """,
            (review_date,),
        ).fetchone()
        horizon_rows = conn.execute(
            """
            SELECT h.hit_miss, h.change_pct, e.confidence_band, e.signal_type, e.ticker, e.direction
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE e.event_date = ? AND h.hit_miss IN ('HIT', 'MISS', 'NEUTRAL')
            """,
            (review_date,),
        ).fetchall()
    finally:
        conn.close()

    useful = false_pos = failed = 0
    rows = [dict(r) for r in horizon_rows]
    for row in rows:
        if row['hit_miss'] == 'HIT':
            useful += 1
        elif row['hit_miss'] == 'MISS':
            failed += 1
            if row.get('confidence_band') == 'HIGH':
                false_pos += 1

    evaluated = useful + failed
    return {
        'signals_generated': int(events['c'] if events else 0),
        'high_confidence_signals': int(high_conf['c'] if high_conf else 0),
        'useful_signals': useful,
        'failed_signals': failed,
        'false_positives': false_pos,
        'evaluated_signals': evaluated,
        'horizon_rows': rows,
    }


def _legacy_outcome_stats(review_date: str) -> List[dict]:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT p.ticker, p.recommendation, p.confidence, o.verdict,
                   o.max_gain_pct, o.max_loss_pct, o.change_1d_pct
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_id = p.id AND o.source_type = 'prediction'
            WHERE p.prediction_date = ?
            """,
            (review_date,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _top_highlights(review_date: str, horizon_rows: List[dict], legacy: List[dict]) -> dict:
    candidates = []

    for row in horizon_rows:
        if row.get('change_pct') is None:
            continue
        chg = float(row['change_pct'])
        candidates.append({
            'ticker': row.get('ticker') or '?',
            'change_pct': chg,
            'direction': str(row.get('direction') or '').upper(),
            'hit_miss': row.get('hit_miss'),
            'confidence_band': row.get('confidence_band'),
        })

    for row in legacy:
        chg = row.get('max_gain_pct') or row.get('change_1d_pct')
        if chg is None:
            continue
        candidates.append({
            'ticker': row.get('ticker'),
            'change_pct': float(chg),
            'direction': str(row.get('recommendation') or '').upper(),
            'hit_miss': row.get('verdict'),
            'confidence_band': str(row.get('confidence') or '').upper(),
        })

    bullish = [c for c in candidates if c['change_pct'] > 0]
    bearish = [c for c in candidates if c['change_pct'] < 0]
    misses = [c for c in candidates if c.get('hit_miss') in ('MISS', 'LOSS')]
    high_conf_wins = [
        c for c in candidates
        if c.get('hit_miss') in ('HIT', 'WIN') and c.get('confidence_band') == 'HIGH'
    ]
    false_pos = [
        c for c in candidates
        if c.get('hit_miss') in ('MISS', 'LOSS') and c.get('confidence_band') == 'HIGH'
    ]

    def _fmt(c):
        if not c:
            return None
        sign = '+' if c['change_pct'] >= 0 else ''
        return {
            'ticker': c['ticker'],
            'move': f"{sign}{c['change_pct']:.1f}%",
            'change_pct': c['change_pct'],
            'label': f"{c['ticker']} {sign}{c['change_pct']:.1f}%",
        }

    best_bull = max(bullish, key=lambda x: x['change_pct']) if bullish else None
    best_bear = min(bearish, key=lambda x: x['change_pct']) if bearish else None
    biggest_miss = None
    if misses:
        biggest_miss = max(misses, key=lambda x: abs(x['change_pct']))

    return {
        'best_bullish': _fmt(best_bull),
        'best_bearish': _fmt(best_bear),
        'biggest_miss': _fmt(biggest_miss),
        'highest_confidence_winner': _fmt(max(high_conf_wins, key=lambda x: x['change_pct'])) if high_conf_wins else None,
        'worst_false_positive': _fmt(false_pos[0]) if false_pos else None,
        'strongest_contradiction': _load_strongest_contradiction(),
    }


def _load_strongest_contradiction() -> Optional[dict]:
    explanations = _load_json(ANALYSIS_EXPLANATIONS_FILE, {})
    warnings = (explanations.get('latest') or {}).get('warnings') or []
    if warnings:
        w = warnings[0]
        return {'summary': w.get('code', 'quality_warning'), 'detail': w.get('message') or str(w.get('value', ''))}
    state = _load_json(ANALYSIS_STATE_FILE, {})
    if _safe_float(state.get('disagreement_score')) >= 0.45:
        return {
            'summary': 'Elevated contradictions',
            'detail': f"Disagreement score {_safe_float(state.get('disagreement_score')):.2f}",
        }
    return None


def _regime_timeline(review_date: str, features: dict) -> List[dict]:
    init_db()
    conn = get_connection()
    timeline = []
    try:
        rows = conn.execute(
            """
            SELECT event_ts, regime, reasoning_summary
            FROM signal_events
            WHERE event_date = ? AND signal_type = 'regime'
            ORDER BY event_ts ASC
            """,
            (review_date,),
        ).fetchall()
        prev_regime = None
        for row in rows:
            r = dict(row)
            regime = r.get('regime') or 'unknown'
            ts = r.get('event_ts') or ''
            time_label = ts[11:16] if len(ts) >= 16 else '—'
            if prev_regime and prev_regime != regime:
                timeline.append({
                    'time': time_label,
                    'transition': f"{prev_regime} → {regime}",
                    'note': (r.get('reasoning_summary') or '')[:120],
                })
            prev_regime = regime
    finally:
        conn.close()

    if not timeline and features.get('regime'):
        timeline.append({
            'time': '—',
            'transition': str(features.get('regime')),
            'note': 'Stable regime through session (no intraday shift logged)',
        })

    explanations = _load_json(ANALYSIS_EXPLANATIONS_FILE, {})
    expl = (explanations.get('latest') or {}).get('explanations') or {}
    if expl.get('why_regime_changed'):
        timeline.append({
            'time': '—',
            'transition': 'regime shift',
            'note': expl.get('why_regime_changed'),
        })
    return timeline[:8]


def _reliability_warnings(features: dict) -> List[dict]:
    warnings = []
    explanations = _load_json(ANALYSIS_EXPLANATIONS_FILE, {})
    latest_q = (explanations.get('latest') or {}).get('quality') or {}
    code_map = {
        'overtruncation_risk': 'Truncation risk — intelligence compression may have dropped nuance',
        'low_novelty': 'Low novelty — signals repeating without fresh evidence',
        'sentiment_collapse_risk': 'Weak sentiment preservation — mood diversity collapsed',
    }
    for w in (explanations.get('latest') or {}).get('warnings') or []:
        code = w.get('code', '')
        warnings.append({
            'code': code,
            'message': code_map.get(code, code.replace('_', ' ')),
            'severity': 'medium',
        })

    if _safe_float(latest_q.get('contradiction_retention_score'), 1) < 0.55:
        warnings.append({
            'code': 'contradiction_retention_drop',
            'message': 'Contradiction retention below target — opposing signals may be flattened',
            'severity': 'high',
        })
    if _safe_float(latest_q.get('sentiment_diversity_score'), 1) < 0.45:
        warnings.append({
            'code': 'weak_sentiment_preservation',
            'message': 'Sentiment diversity weak — mood calibration may be unreliable',
            'severity': 'medium',
        })

    metrics = _load_json(EXECUTION_METRICS_FILE, {})
    counters = metrics.get('counters') or {}
    if counters.get('safe_fallbacks', 0) > 0:
        warnings.append({
            'code': 'fallback_activations',
            'message': f"Safe fallback used {counters.get('safe_fallbacks')} time(s) — degraded intelligence served",
            'severity': 'high',
        })
    if counters.get('hallucination_detections', 0) > 0:
        warnings.append({
            'code': 'hallucination_detections',
            'message': f"Hallucination guard triggered {counters.get('hallucination_detections')} time(s)",
            'severity': 'medium',
        })
    if counters.get('schema_failures', 0) > 0:
        warnings.append({
            'code': 'schema_failures',
            'message': f"Schema validation failures: {counters.get('schema_failures')}",
            'severity': 'medium',
        })

    cache_hits = counters.get('cache_hits', 0)
    cache_miss = counters.get('cache_misses', 0)
    total_cache = cache_hits + cache_miss
    if total_cache >= 10 and cache_hits / total_cache < 0.15:
        warnings.append({
            'code': 'low_cache_reuse',
            'message': 'Low semantic cache reuse — higher AI cost and less stable outputs',
            'severity': 'low',
        })

    if features.get('market_source_degraded'):
        warnings.append({
            'code': 'degraded_market_source',
            'message': 'Market feed degraded — Angel One fallback / preserved snapshots in use',
            'severity': 'high',
        })

    return warnings[:10]


def _telegram_effectiveness(review_date: str) -> dict:
    obs = _load_json(TELEGRAM_ALERT_OBS_FILE, {})
    if obs.get('date') != review_date:
        obs = {'sent_today': [], 'suppressed_today': []}

    sent = obs.get('sent_today') or obs.get('recent_sent') or []
    suppressed = obs.get('suppressed_today') or obs.get('recent_suppressed') or []

    dupes = sum(1 for s in suppressed if s.get('reason') == 'duplicate')
    low_conf = sum(1 for s in suppressed if 'confidence' in str(s.get('reason', '')).lower())
    cooldown = sum(1 for s in suppressed if s.get('reason') == 'cooldown')
    emergency = sum(1 for s in sent if 'EMERGENCY' in str(s.get('category', '')).upper())

    try:
        from backend.analytics.signal_outcomes import _telegram_precision
        precision = _telegram_precision()
    except Exception:
        precision = None

    useful_est = None
    if precision is not None and sent:
        useful_est = max(0, round(len(sent) * precision / 100))

    return {
        'alerts_sent': len(sent),
        'alerts_suppressed': len(suppressed),
        'duplicate_blocks': dupes,
        'low_confidence_skips': low_conf,
        'cooldown_blocks': cooldown,
        'emergency_alerts': emergency,
        'estimated_useful_alerts': useful_est,
        'telegram_precision_pct': precision,
    }


def _build_observation(features: dict, classification: dict, perf: dict, tg: dict) -> str:
    vol = features.get('volatility_index', 0.4)
    disagree = features.get('disagreement_score', 0)
    parts = []

    if classification.get('label') == 'PANIC VOLATILE':
        parts.append('AI correctly leaned cautious during elevated volatility and contradictions.')
    elif classification.get('label') == 'TRENDING DAY':
        parts.append('Directional session — scanner and opportunity signals carried more predictive weight.')
    elif classification.get('label') == 'SIDEWAYS CHOP':
        parts.append('Range-bound chop — high-confidence intraday breakouts should be treated skeptically.')
    else:
        parts.append('Mixed session — selective signal filtering outperformed broad aggression.')

    if perf.get('false_positives', 0) > perf.get('useful_signals', 0) and perf.get('evaluated_signals', 0) >= MIN_SAMPLES_OBSERVATION:
        parts.append('False positives elevated; tighten HIGH confidence gates tomorrow.')
    elif tg.get('telegram_precision_pct') and tg['telegram_precision_pct'] >= 70:
        parts.append('Telegram alerts demonstrated useful precision for this archetype.')

    if vol >= 0.55 and disagree >= 0.4:
        parts.append('Contradiction intensity rose — preservation layer likely prevented overconfidence.')

    return ' '.join(parts)


def _build_copy_text(review: dict) -> str:
    c = review.get('market_day_classification') or {}
    p = review.get('performance_summary') or {}
    h = review.get('highlights') or {}
    tg = review.get('telegram') or {}
    w = review.get('warnings') or []
    s = review.get('daily_summary') or {}

    lines = [
        f"DAILY INTELLIGENCE REVIEW — {review.get('date', '')}",
        '',
        f"DAY TYPE: {c.get('label', '—')}",
        f"REGIME: {s.get('regime', '—')}",
        f"QUALITY IQ: {s.get('quality_iq', '—')}",
        '',
        'PERFORMANCE',
        f"Signals: {p.get('signals_generated', 0)} | Useful: {p.get('useful_signals', 0)} | "
        f"False positives: {p.get('false_positives', 0)} | Suppressed alerts: {p.get('suppressed_alerts', 0)}",
        f"Telegram precision: {p.get('telegram_precision_pct') or '—'}%",
        '',
        'HIGHLIGHTS',
    ]
    if h.get('best_bullish'):
        lines.append(f"BEST BULLISH: {h['best_bullish'].get('label', '—')}")
    if h.get('best_bearish'):
        lines.append(f"BEST BEARISH: {h['best_bearish'].get('label', '—')}")
    if h.get('biggest_miss'):
        lines.append(f"FAILED: {h['biggest_miss'].get('label', '—')}")
    lines.extend(['', 'TELEGRAM', f"Sent: {tg.get('alerts_sent', 0)} | Useful est: {tg.get('estimated_useful_alerts', '—')}"])
    if w:
        lines.extend(['', 'WARNINGS'] + [f"- {x.get('message', x.get('code', ''))}" for x in w[:5]])
    if review.get('observation'):
        lines.extend(['', 'OBSERVATION', review['observation']])
    return '\n'.join(lines)


def build_daily_review(review_date: Optional[str] = None, *, persist: bool = True) -> dict:
    """Build and optionally persist the daily intelligence review snapshot."""
    date = review_date or _today()
    features = _extract_features(date)
    classification = classify_market_day(features)
    signal_stats = _signal_stats_for_date(date)
    legacy = _legacy_outcome_stats(date)
    horizon_rows = signal_stats.pop('horizon_rows', [])
    highlights = _top_highlights(date, horizon_rows, legacy)
    regime_timeline = _regime_timeline(date, features)
    warnings = _reliability_warnings(features)
    telegram = _telegram_effectiveness(date)

    tg_precision = telegram.get('telegram_precision_pct')

    performance_summary = {
        'signals_generated': signal_stats.get('signals_generated', 0),
        'high_confidence_signals': signal_stats.get('high_confidence_signals', 0),
        'useful_signals': signal_stats.get('useful_signals', 0),
        'failed_signals': signal_stats.get('failed_signals', 0),
        'false_positives': signal_stats.get('false_positives', 0),
        'suppressed_alerts': telegram.get('alerts_suppressed', 0),
        'missed_opportunities': signal_stats.get('failed_signals', 0),
        'telegram_precision_pct': tg_precision,
        'evaluated_signals': signal_stats.get('evaluated_signals', 0),
        'confidence_calibration_quality': (
            'insufficient_data' if signal_stats.get('evaluated_signals', 0) < MIN_SAMPLES_OBSERVATION
            else ('strong' if signal_stats.get('false_positives', 0) <= signal_stats.get('useful_signals', 0)
                  else 'needs_tuning')
        ),
    }

    daily_summary = {
        'regime': features.get('regime'),
        'quality_iq': round(features.get('quality_iq'), 2) if features.get('quality_iq') else None,
        'day_type': classification.get('label'),
        'best_signal': (highlights.get('best_bullish') or {}).get('label'),
        'failed_signal': (highlights.get('biggest_miss') or {}).get('label'),
        'telegram_sent': telegram.get('alerts_sent', 0),
        'telegram_useful_est': telegram.get('estimated_useful_alerts'),
        'warnings_count': len(warnings),
    }

    observation = _build_observation(features, classification, performance_summary, telegram)

    review = {
        'status': 'ok',
        'date': date,
        'generated_at': datetime.now().isoformat(),
        'market_day_classification': classification,
        'performance_summary': performance_summary,
        'highlights': highlights,
        'regime_analysis': {
            'timeline': regime_timeline,
            'final_regime': features.get('regime'),
            'contradiction_intensity': round(features.get('disagreement_score', 0), 2),
            'sentiment_diversity': round(features.get('sentiment_diversity', 0), 2),
        },
        'warnings': warnings,
        'telegram': telegram,
        'daily_summary': daily_summary,
        'observation': observation,
    }
    review['copy_text'] = _build_copy_text(review)

    if persist:
        DAILY_REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(DAILY_REVIEWS_DIR / f'review_{date}.json', review)
        index = _load_json(REVIEW_INDEX_FILE, {'dates': []})
        dates = [d for d in (index.get('dates') or []) if d != date]
        dates.insert(0, date)
        index['dates'] = dates[:60]
        index['latest'] = date
        atomic_write_json(REVIEW_INDEX_FILE, index)
        _log('DAILY REVIEW', f'snapshot saved for {date}')

    return review


def get_daily_review(review_date: Optional[str] = None, *, rebuild: bool = False) -> dict:
    """Load cached review or build fresh."""
    date = review_date or _today()
    path = DAILY_REVIEWS_DIR / f'review_{date}.json'
    if not rebuild and path.exists():
        cached = _load_json(path, {})
        if cached.get('date') == date and cached.get('copy_text'):
            cached.setdefault('status', 'ok')
            return cached
    try:
        return build_daily_review(date, persist=True)
    except Exception as e:
        _log('DAILY REVIEW', f'degraded: {e}')
        return {
            'status': 'degraded',
            'date': date,
            'reason': str(e),
            'market_day_classification': {'label': 'UNKNOWN', 'reason': 'Review build failed'},
            'performance_summary': {},
            'highlights': {},
            'regime_analysis': {'timeline': []},
            'warnings': [{'code': 'review_error', 'message': str(e), 'severity': 'high'}],
            'telegram': {},
            'daily_summary': {},
            'observation': '',
            'copy_text': f'Daily review unavailable for {date}: {e}',
        }


def list_review_dates(limit: int = 14) -> List[str]:
    index = _load_json(REVIEW_INDEX_FILE, {})
    return (index.get('dates') or [])[:limit]
