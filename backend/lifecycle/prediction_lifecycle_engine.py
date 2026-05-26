"""
End-of-Day Intelligence Lifecycle Engine
========================================
Closes the prediction loop: evaluate outcomes, refresh brain, sync exports.

States: ACTIVE, PENDING, WIN, LOSS, PARTIAL, EXPIRED, INVALIDATED
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

from backend.lifecycle.lifecycle_rules import (
    ACTIVE_STATES,
    EXPIRE_AFTER_DAYS,
    TERMINAL_STATES,
    UNRESOLVED_STATE,
    infer_prediction_horizon,
    infer_signal_type,
    sessions_elapsed,
    should_expire,
    ttl_sessions,
)
from backend.lifecycle.lifecycle_evaluator import (
    build_confidence_realism_curve,
    build_regime_performance,
    build_signal_type_performance,
    evaluate_lifecycle_predictions,
)
from backend.lifecycle.lifecycle_tracing import (
    log_error,
    mark_stage_complete,
    pipeline_log,
    update_heartbeat,
)
from backend.storage.db_manager import get_connection, init_db
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR
from backend.utils.process_lock import release_lock, try_acquire_lock

IST = pytz.timezone('Asia/Kolkata')

ACTIVE_PREDICTIONS_FILE = DATA_DIR / 'active_predictions.json'
PREDICTION_HISTORY_FILE = DATA_DIR / 'prediction_history.json'
LIFECYCLE_STATE_FILE = DATA_DIR / 'lifecycle_state.json'
CALIBRATION_HISTORY_FILE = DATA_DIR / 'calibration_history.json'
INTELLIGENCE_FILE = DATA_DIR / 'unified_intelligence.json'
HIGH_CONVICTION_FILE = DATA_DIR / 'high_conviction_alerts.json'
STATS_FILE = DATA_DIR / 'stats_data.json'
HISTORY_FILE = DATA_DIR / 'history_data.json'
DAILY_REVIEWS_DIR = DATA_DIR / 'daily_reviews'

BEARISH_REGIMES = frozenset({'bearish', 'cautious', 'risk_off', 'defensive'})


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _today() -> str:
    return datetime.now(IST).strftime('%Y-%m-%d')


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if data is not None else default
    except Exception:
        return default


def load_lifecycle_state() -> dict:
    return _load_json(LIFECYCLE_STATE_FILE, {
        'pipeline_status': 'IDLE',
        'last_eod_cycle_date': None,
        'last_eod_cycle_at': None,
        'last_evaluation_at': None,
        'evaluation_cycle_complete': False,
        'brain_refresh_at': None,
        'exports_synced_at': None,
        'last_stats_export': None,
        'last_history_export': None,
        'last_calibration_export': None,
        'last_journal_generation': None,
        'last_brain_refresh': None,
        'last_successful_eod': None,
        'active_count': 0,
        'archived_count': 0,
        'stale_invalidated': 0,
        'cycles_today': 0,
        'errors': [],
    })


def save_lifecycle_state(state: dict):
    state['updated_at'] = _now_iso()
    atomic_write_json(LIFECYCLE_STATE_FILE, state)


def _file_age_minutes(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return int((datetime.now() - mtime).total_seconds() / 60)


def _run_script(script_name: str, extra_env: Optional[dict] = None):
    from backend.utils.runner import run_script
    run_script(script_name, check=False, extra_env=extra_env or {})


def _run_script_safe(script_name: str, extra_env: Optional[dict] = None) -> dict:
    """Run script without raising — optional lifecycle steps."""
    from backend.utils.safe_optional import run_optional
    return run_optional(
        script_name,
        lambda: _run_script(script_name, extra_env),
        log=lambda m: pipeline_log(m, stage=script_name),
    )


def expire_stale_pending() -> dict:
    """Mark aged PENDING outcomes as EXPIRED — never raises."""
    stats = {'expired': 0, 'skipped': 0, 'errors': 0}
    try:
        init_db()
        conn = get_connection()
        try:
            today = datetime.now().date()
            rows = conn.execute("""
                SELECT o.id, o.prediction_date, o.ticker, o.verdict,
                       p.signal_type, p.prediction_horizon
                FROM outcomes o
                LEFT JOIN predictions p ON o.source_type = 'prediction' AND o.source_id = p.id
                WHERE o.verdict IN ('PENDING', 'UNRESOLVED') OR o.verdict IS NULL
            """).fetchall()
            for row in rows:
                try:
                    pred_date_str = row['prediction_date']
                    if not pred_date_str:
                        stats['skipped'] += 1
                        continue
                    elapsed = sessions_elapsed(pred_date_str, today)
                    signal_type = row['signal_type'] or 'breakout'
                    verdict = row['verdict'] or 'PENDING'
                    max_days = max(ttl_sessions(signal_type), 1)
                    cap_days = EXPIRE_AFTER_DAYS
                    expire_at = min(max_days, cap_days) if signal_type != 'regime outlook' else cap_days
                    if should_expire(signal_type, elapsed, verdict) or elapsed >= expire_at:
                        conn.execute("""
                            UPDATE outcomes SET verdict = 'EXPIRED', last_checked = ?
                            WHERE id = ?
                        """, (_now_iso(), row['id']))
                        stats['expired'] += 1
                    else:
                        stats['skipped'] += 1
                except Exception:
                    stats['errors'] += 1
            conn.commit()
        finally:
            conn.close()
        if stats['expired']:
            pipeline_log(f"Expired {stats['expired']} stale pending outcomes", stage='expire_stale')
    except Exception as e:
        stats['errors'] += 1
        log_error('expire_stale_pending', e, stage='expire_stale')
        pipeline_log(f"expire_stale degraded (non-fatal): {e}", stage='expire_stale')
    return stats


def invalidate_contradicted_predictions() -> dict:
    """Invalidate active bullish opportunities under bearish regime."""
    intel = _load_json(INTELLIGENCE_FILE, {})
    mood = intel.get('market_mood') or {}
    regime = str(
        mood.get('india_outlook') or mood.get('global_mood') or intel.get('market_bias') or ''
    ).lower()
    if not any(r in regime for r in BEARISH_REGIMES):
        return {'invalidated': 0}

    init_db()
    conn = get_connection()
    stats = {'invalidated': 0}
    try:
        rows = conn.execute("""
            SELECT o.id, p.ticker, p.category, p.confidence
            FROM outcomes o
            INNER JOIN predictions p ON o.source_type = 'prediction' AND o.source_id = p.id
            WHERE o.verdict IN ('PENDING', 'NEUTRAL', 'PARTIAL')
              AND p.category = 'opportunity'
        """).fetchall()
        for row in rows:
            conn.execute("""
                UPDATE outcomes SET verdict = 'INVALIDATED', last_checked = ?
                WHERE id = ?
            """, (_now_iso(), row['id']))
            stats['invalidated'] += 1
        conn.commit()
    finally:
        conn.close()
    if stats['invalidated']:
        _log('LIFECYCLE', f"Invalidated {stats['invalidated']} regime-contradicted predictions")
    return stats


def _map_lifecycle_state(verdict: Optional[str], pred_date: str, in_brain: bool) -> str:
    v = (verdict or 'PENDING').upper()
    if v in TERMINAL_STATES:
        return v
    if v == 'NEUTRAL':
        return 'PARTIAL'
    if v == 'PENDING':
        if in_brain:
            return 'ACTIVE'
        return 'PENDING'
    return v


def load_active_predictions() -> List[dict]:
    """Load ACTIVE/PENDING predictions — lifecycle source of truth for Brain."""
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                p.id, p.ticker, p.category, p.confidence, p.prediction_date,
                p.entry_price, p.target_price, p.stop_loss, p.run_type,
                p.prediction_horizon, p.signal_type, p.reasoning,
                o.verdict, o.change_1d_pct, o.max_gain_pct, o.max_loss_pct,
                o.target_hit, o.stop_loss_hit
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type = 'prediction' AND o.source_id = p.id
            WHERE o.verdict IS NULL
               OR o.verdict IN ('PENDING', 'UNRESOLVED', 'NEUTRAL', 'PARTIAL', 'ACTIVE')
            ORDER BY p.prediction_date DESC, p.id DESC
            LIMIT 200
        """).fetchall()
    finally:
        conn.close()

    active = []
    for row in rows:
        d = dict(row)
        ticker = str(d.get('ticker') or '').upper()
        verdict = (d.get('verdict') or 'PENDING').upper()
        if verdict in TERMINAL_STATES:
            continue
        signal_type = d.get('signal_type') or infer_signal_type(d)
        horizon = d.get('prediction_horizon') or infer_prediction_horizon(d, signal_type)
        state = 'ACTIVE' if verdict in ('PENDING', 'UNRESOLVED', 'PARTIAL', 'NEUTRAL', None) else verdict
        if state == 'NEUTRAL':
            state = 'PARTIAL' if (d.get('change_1d_pct') or 0) >= 0.5 else 'PENDING'
        active.append({
            'prediction_id': d['id'],
            'ticker': ticker,
            'category': d.get('category'),
            'confidence': d.get('confidence'),
            'prediction_date': d.get('prediction_date'),
            'entry_price': d.get('entry_price'),
            'target_price': d.get('target_price'),
            'stop_loss': d.get('stop_loss'),
            'run_type': d.get('run_type'),
            'prediction_horizon': horizon,
            'signal_type': signal_type,
            'state': state if state in ACTIVE_STATES or state == 'PARTIAL' else 'ACTIVE',
            'change_1d_pct': d.get('change_1d_pct'),
            'max_gain_pct': d.get('max_gain_pct'),
            'max_loss_pct': d.get('max_loss_pct'),
            'target_hit': bool(d.get('target_hit')),
            'stop_loss_hit': bool(d.get('stop_loss_hit')),
        })
    return active


def load_prediction_history(limit: int = 500) -> List[dict]:
    """Load resolved prediction archive from SQLite."""
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                p.id, p.ticker, p.category, p.confidence, p.prediction_date,
                p.entry_price, p.target_price, p.stop_loss,
                p.prediction_horizon, p.signal_type, p.failure_reason,
                o.verdict, o.change_1d_pct, o.change_3d_pct, o.change_7d_pct,
                o.max_gain_pct, o.max_loss_pct, o.target_hit, o.stop_loss_hit,
                o.last_checked
            FROM predictions p
            INNER JOIN outcomes o ON o.source_type = 'prediction' AND o.source_id = p.id
            WHERE o.verdict IN ('WIN', 'LOSS', 'PARTIAL', 'NEUTRAL', 'EXPIRED', 'INVALIDATED', 'UNRESOLVED')
            ORDER BY o.last_checked DESC, p.prediction_date DESC
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()

    history = []
    for row in rows:
        d = dict(row)
        verdict = (d.get('verdict') or '').upper()
        if verdict == 'NEUTRAL':
            verdict = 'PARTIAL'
        gain_loss = d.get('change_1d_pct') or d.get('max_gain_pct') or d.get('max_loss_pct')
        history.append({
            'prediction_id': d['id'],
            'ticker': d.get('ticker'),
            'category': d.get('category'),
            'confidence': d.get('confidence'),
            'prediction_date': d.get('prediction_date'),
            'entry_price': d.get('entry_price'),
            'target_price': d.get('target_price'),
            'stop_loss': d.get('stop_loss'),
            'prediction_horizon': d.get('prediction_horizon'),
            'signal_type': d.get('signal_type'),
            'failure_reason': d.get('failure_reason'),
            'state': verdict,
            'change_1d_pct': d.get('change_1d_pct'),
            'change_3d_pct': d.get('change_3d_pct'),
            'change_7d_pct': d.get('change_7d_pct'),
            'max_gain_pct': d.get('max_gain_pct'),
            'max_loss_pct': d.get('max_loss_pct'),
            'gain_loss_pct': gain_loss,
            'target_hit': bool(d.get('target_hit')),
            'stop_loss_hit': bool(d.get('stop_loss_hit')),
            'resolved_at': d.get('last_checked'),
        })
    return history


def sync_prediction_json_files() -> dict:
    """Persist active_predictions.json and prediction_history.json."""
    active = load_active_predictions()
    history = load_prediction_history()
    payload_active = {
        'updated_at': _now_iso(),
        'count': len(active),
        'predictions': active,
    }
    payload_history = {
        'updated_at': _now_iso(),
        'count': len(history),
        'predictions': history,
    }
    atomic_write_json(ACTIVE_PREDICTIONS_FILE, payload_active)
    atomic_write_json(PREDICTION_HISTORY_FILE, payload_history)
    return {'active': len(active), 'archived': len(history)}


def refresh_brain_opportunities() -> dict:
    """
    Brain displays ONLY active_predictions.json opportunities.
    Preserves intel context (mood, sectors) but replaces opportunity lists.
    """
    sync_prediction_json_files()
    active = load_active_predictions()
    prior_count = len(_load_json(INTELLIGENCE_FILE, {}).get('top_opportunities') or [])

    intel = _load_json(INTELLIGENCE_FILE, {})
    if not intel or intel.get('error'):
        intel = {'timestamp': _now_iso(), 'generated_date': _today()}

    opps = []
    for p in active:
        state = (p.get('state') or '').upper()
        if state not in ('ACTIVE', 'PENDING'):
            continue
        if p.get('category') != 'opportunity':
            continue
        opps.append({
            'symbol': p.get('ticker'),
            'ticker': p.get('ticker'),
            'action': 'BUY',
            'confidence': p.get('confidence', 'MEDIUM'),
            'entry_zone': p.get('entry_price'),
            'target': p.get('target_price'),
            'stop_loss': p.get('stop_loss'),
            'logic': f"{p.get('signal_type', 'signal')} · {p.get('prediction_horizon', 'next_day')} horizon",
            'session_date': _today(),
            'prediction_horizon': p.get('prediction_horizon'),
            'signal_type': p.get('signal_type'),
            'lifecycle_state': p.get('state', 'ACTIVE'),
        })

    intel['top_opportunities'] = opps
    intel['timestamp'] = _now_iso()
    intel['generated_date'] = _today()
    intel['active_predictions_source'] = str(ACTIVE_PREDICTIONS_FILE.name)
    intel['lifecycle'] = {
        'refreshed_at': _now_iso(),
        'active_opportunities': len(opps),
        'stale_removed': max(0, prior_count - len(opps)),
        'active_prediction_count': len(active),
        'session_date': _today(),
        'source': 'active_predictions.json',
    }
    atomic_write_json(INTELLIGENCE_FILE, intel)
    _log('LIFECYCLE', f"Brain refresh from active store: {len(opps)} opportunities")
    return {
        'removed': intel['lifecycle']['stale_removed'],
        'kept': len(opps),
        'status': 'ok',
        'active_count': len(active),
    }


def build_calibration_snapshot() -> dict:
    """Generate calibration metrics from resolved predictions."""
    init_db()
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN o.verdict='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN o.verdict='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN o.verdict IN ('PARTIAL','NEUTRAL') THEN 1 ELSE 0 END) as partials,
                SUM(CASE WHEN o.verdict='EXPIRED' THEN 1 ELSE 0 END) as expired,
                SUM(CASE WHEN o.verdict='INVALIDATED' THEN 1 ELSE 0 END) as invalidated,
                SUM(CASE WHEN o.verdict='UNRESOLVED' THEN 1 ELSE 0 END) as unresolved,
                SUM(CASE WHEN o.verdict='PENDING' OR o.verdict IS NULL THEN 1 ELSE 0 END) as pending,
                AVG(CASE WHEN o.verdict='WIN' THEN o.max_gain_pct END) as avg_gain,
                AVG(CASE WHEN o.verdict='LOSS' THEN ABS(o.max_loss_pct) END) as avg_loss,
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict='WIN' THEN 1 ELSE 0 END) as high_wins,
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict IS NOT NULL AND o.verdict != 'PENDING' THEN 1 ELSE 0 END) as high_total,
                SUM(CASE WHEN o.verdict='LOSS' AND p.confidence IN ('HIGH','MEDIUM') THEN 1 ELSE 0 END) as false_positives
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
        """).fetchone()
    finally:
        conn.close()

    d = dict(row) if row else {}
    evaluated = (d.get('wins') or 0) + (d.get('losses') or 0) + (d.get('partials') or 0)
    wins = d.get('wins') or 0
    losses = d.get('losses') or 0
    avg_gain = d.get('avg_gain') or 0
    avg_loss = d.get('avg_loss') or 1
    high_total = d.get('high_total') or 0
    high_wins = d.get('high_wins') or 0

    snapshot = {
        'generated_at': _now_iso(),
        'date': _today(),
        'win_rate': round(wins / evaluated * 100, 2) if evaluated else 0,
        'loss_rate': round(losses / evaluated * 100, 2) if evaluated else 0,
        'partial_rate': round((d.get('partials') or 0) / evaluated * 100, 2) if evaluated else 0,
        'avg_gain_pct': round(avg_gain, 2),
        'avg_loss_pct': round(avg_loss, 2),
        'profit_factor': round(avg_gain / avg_loss, 2) if avg_loss else 0,
        'confidence_realism': round(high_wins / high_total * 100, 2) if high_total else None,
        'false_positive_rate': round((d.get('false_positives') or 0) / evaluated * 100, 2) if evaluated else 0,
        'total_evaluated': evaluated,
        'pending': d.get('pending') or 0,
        'expired': d.get('expired') or 0,
        'invalidated': d.get('invalidated') or 0,
        'unresolved': d.get('unresolved') or 0,
        'message': (
            'Awaiting evaluated prediction sample size.'
            if evaluated < 30
            else 'Calibration metrics from lifecycle evaluations.'
        ),
        'confidence_realism_curve': build_confidence_realism_curve(),
        'signal_type_performance': build_signal_type_performance(),
        'regime_performance': build_regime_performance(),
    }

    try:
        from backend.analytics.regime_analytics import build_calibration_dashboard
        snapshot['dashboard'] = build_calibration_dashboard()
    except Exception as e:
        snapshot['dashboard'] = {'status': 'degraded', 'reason': str(e)}

    history = _load_json(CALIBRATION_HISTORY_FILE, {'entries': []})
    entries = history.get('entries') or []
    entries = [e for e in entries if e.get('date') != _today()]
    entries.insert(0, snapshot)
    atomic_write_json(CALIBRATION_HISTORY_FILE, {
        'updated_at': _now_iso(),
        'entries': entries[:90],
        'latest': snapshot,
    })
    return snapshot


def get_daily_lifecycle_summary() -> dict:
    """Summary block for daily review / journal enrichment."""
    history = load_prediction_history(limit=50)
    today = _today()
    today_resolved = [h for h in history if str(h.get('resolved_at') or '').startswith(today)
                      or str(h.get('prediction_date') or '') == today]
    wins = [h for h in today_resolved if h.get('state') == 'WIN']
    losses = [h for h in today_resolved if h.get('state') == 'LOSS']
    partials = [h for h in today_resolved if h.get('state') == 'PARTIAL']
    state = load_lifecycle_state()
    cal = _load_json(CALIBRATION_HISTORY_FILE, {}).get('latest') or {}

    return {
        'evaluation_complete': state.get('evaluation_cycle_complete'),
        'last_cycle_at': state.get('last_eod_cycle_at'),
        'resolved_today': len(today_resolved),
        'wins_today': len(wins),
        'losses_today': len(losses),
        'partials_today': len(partials),
        'best_prediction': wins[0] if wins else None,
        'worst_prediction': losses[0] if losses else None,
        'win_rate': cal.get('win_rate'),
        'confidence_realism': cal.get('confidence_realism'),
        'false_positive_rate': cal.get('false_positive_rate'),
        'active_count': state.get('active_count', 0),
        'stale_invalidated': state.get('stale_invalidated', 0),
        'tomorrow_outlook': 'Fresh post-market intelligence generated' if state.get('brain_refresh_at') else 'Pending refresh',
    }


def persist_immutable_daily_review() -> dict:
    """Write daily review once — never mutate existing immutable snapshots."""
    review_path = DAILY_REVIEWS_DIR / f'review_{_today()}.json'
    if review_path.exists():
        cached = _load_json(review_path, {})
        if cached.get('immutable') and cached.get('date') == _today():
            cached['lifecycle_summary'] = get_daily_lifecycle_summary()
            return {'date': _today(), 'status': 'cached', 'immutable': True}

    from backend.analytics.daily_review_engine import build_daily_review
    review = build_daily_review(persist=False)
    review['lifecycle_summary'] = get_daily_lifecycle_summary()
    review['immutable'] = True
    review['lifecycle_engine'] = 'prediction_lifecycle_engine_v1'
    DAILY_REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(review_path, review)

    index_path = DAILY_REVIEWS_DIR / 'index.json'
    index = _load_json(index_path, {'dates': []})
    dates = [d for d in (index.get('dates') or []) if d != _today()]
    dates.insert(0, _today())
    index['dates'] = dates[:60]
    index['latest'] = _today()
    atomic_write_json(index_path, index)
    return {'date': _today(), 'status': review.get('status'), 'immutable': True, 'review': review}


def send_telegram_daily_review(review: dict, lifecycle_summary: dict) -> dict:
    """Send ONE concise post-market review to Telegram."""
    try:
        from backend.orchestration.telegram_listener import send_message
    except Exception as e:
        return {'sent': False, 'reason': str(e)}

    perf = review.get('performance_summary') or {}
    summary = review.get('daily_summary') or {}
    lc = lifecycle_summary or review.get('lifecycle_summary') or {}
    highlights = review.get('highlights') or {}

    wins = lc.get('wins_today', 0)
    losses = lc.get('losses_today', 0)
    partials = lc.get('partials_today', 0)
    signals = perf.get('signals_generated') or lc.get('resolved_today') or 0

    best = highlights.get('best_bullish') or lc.get('best_prediction') or {}
    worst = highlights.get('biggest_miss') or lc.get('worst_prediction') or {}

    best_line = '—'
    if isinstance(best, dict):
        ticker = best.get('ticker') or best.get('label') or ''
        pct = best.get('gain_loss_pct') or best.get('max_gain_pct') or best.get('change_1d_pct')
        if ticker:
            best_line = f"{ticker} {pct:+.1f}%" if pct is not None else ticker
    elif best:
        best_line = str(best)

    worst_line = '—'
    if isinstance(worst, dict):
        ticker = worst.get('ticker') or worst.get('label') or ''
        pct = worst.get('gain_loss_pct') or worst.get('max_loss_pct') or worst.get('change_1d_pct')
        if ticker:
            worst_line = f"{ticker} {pct:+.1f}%" if pct is not None else ticker

    regime = summary.get('regime') or (review.get('regime_analysis') or {}).get('final_regime') or 'unknown'
    tomorrow = lc.get('tomorrow_outlook') or review.get('observation') or 'Fresh scanner-led opportunities pending open.'

    msg = (
        f"<b>📘 DAILY REVIEW</b>\n\n"
        f"Signals: {signals}\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Partial: {partials}\n\n"
        f"<b>Best:</b>\n{best_line}\n\n"
        f"<b>Worst:</b>\n{worst_line}\n\n"
        f"<b>Regime:</b>\n{regime}\n\n"
        f"<b>Tomorrow:</b>\n{str(tomorrow)[:280]}"
    )
    send_message(msg)
    return {'sent': True}


def get_active_predictions_payload() -> dict:
    """Public read API for Brain — active store only."""
    data = _load_json(ACTIVE_PREDICTIONS_FILE, {})
    if not data.get('predictions'):
        active = load_active_predictions()
        return {
            'updated_at': _now_iso(),
            'count': len(active),
            'predictions': active,
            'source': 'lifecycle_engine',
        }
    data['source'] = 'active_predictions.json'
    return data


def _evaluate_outcomes() -> dict:
    eval_stats = evaluate_lifecycle_predictions(verbose=True, backfill=True, use_cache_only=True)
    pipeline_log(
        f"eval processed={eval_stats.get('processed', 0)} "
        f"terminal={eval_stats.get('evaluated', 0) + eval_stats.get('expired', 0)} "
        f"errors={eval_stats.get('errors', 0)} avg={eval_stats.get('avg_time_sec', 0)}s",
        stage='evaluate_outcomes',
    )
    sig = {'evaluated': 0, 'skipped': 'cache_only_eod'}
    try:
        from backend.analyzers.outcome_tracker import evaluate_signals_outcomes
        sig = evaluate_signals_outcomes(verbose=False)
    except Exception as e:
        sig = {'evaluated': 0, 'error': str(e)}
    try:
        from backend.analytics.signal_outcomes import evaluate_due_horizons
        hr = evaluate_due_horizons()
    except Exception as e:
        hr = {'evaluated': 0, 'error': str(e)}
    adaptive = {'status': 'deferred', 'message': 'Adaptive runs after calibration snapshot'}
    return {'lifecycle': eval_stats, 'signals': sig, 'horizons': hr, 'adaptive': adaptive}


def _run_adaptive_calibration():
    from backend.adaptive.adaptive_calibration_engine import run_adaptive_calibration_cycle
    return run_adaptive_calibration_cycle()


CRITICAL_STAGES = frozenset({
    'evaluate_outcomes',
    'sync_predictions',
    'brain_refresh',
    'daily_review',
    'calibration_snapshot',
    'stats_export',
    'history_export',
})


def run_end_of_day_cycle(force: bool = False) -> dict:
    """
    Full post-market lifecycle pipeline with single-execution guard.
    Must fully complete OR fail loudly — never silent partial success.
    """
    lock_name = 'eod_lifecycle'
    if not try_acquire_lock(lock_name):
        pipeline_log('Skipped — another EOD cycle is running', stage='lock')
        return {'status': 'skipped', 'reason': 'lock_held'}

    result: Dict[str, Any] = {'status': 'running', 'stages': [], 'started_at': _now_iso()}
    state = load_lifecycle_state()
    today = _today()

    if not force and state.get('last_eod_cycle_date') == today and state.get('evaluation_cycle_complete'):
        if state.get('pipeline_status') == 'COMPLETE':
            release_lock(lock_name)
            pipeline_log('Already completed today — skip', stage='lock')
            return {'status': 'skipped', 'reason': 'already_completed_today', 'last_at': state.get('last_eod_cycle_at')}

    errors: List[str] = []
    failed_critical = False

    update_heartbeat(
        pipeline_status='RUNNING',
        current_stage='starting',
        extra={
            'evaluation_cycle_complete': False,
            'last_eod_attempt_at': _now_iso(),
            'last_eod_cycle_date': today,
        },
    )
    pipeline_log('starting evaluation cycle', stage='start')
    os.environ['LIFECYCLE_CACHE_ONLY'] = '1'

    def _stage(name: str, fn, *, critical: bool = True):
        nonlocal failed_critical
        pipeline_log(f'begin {name}', stage=name)
        update_heartbeat(pipeline_status='RUNNING', current_stage=name)
        try:
            out = fn()
            result['stages'].append({'name': name, 'status': 'ok', 'result': out})
            mark_stage_complete(name)
            pipeline_log(f'completed {name}', stage=name)
            return out
        except Exception as e:
            msg = f"{name}: {e}"
            errors.append(msg)
            log_error(name, e, stage=name)
            result['stages'].append({'name': name, 'status': 'error', 'error': str(e)})
            pipeline_log(f'FAILED {name}: {e}', stage=name)
            if critical and name in CRITICAL_STAGES:
                failed_critical = True
            return None

    try:
        _stage('evaluate_outcomes', _evaluate_outcomes)
        pipeline_log('evaluating predictions complete', stage='evaluate_outcomes')
        expire_stats = _stage('expire_stale', expire_stale_pending, critical=False) or {}
        inv_stats = _stage('invalidate_contradicted', invalidate_contradicted_predictions, critical=False) or {}
        sync_stats = _stage('sync_predictions', sync_prediction_json_files)
        pipeline_log('refreshing active predictions', stage='sync_predictions')

        _stage('meta_labeler', lambda: _run_script_safe('meta_labeler.py'), critical=False)

        def _post_market_intel():
            os.environ['AI_USE_CASE'] = 'post_close'
            from backend.orchestration.master_scheduler import run_all_collectors_parallel
            run_all_collectors_parallel(push_telegram_brain=False, run_analyzer=True)
            return {'use_case': 'post_close'}

        _stage('tomorrow_intelligence', _post_market_intel)
        _stage('prediction_logger', lambda: _run_script('prediction_logger.py', {'AI_USE_CASE': 'post_close'}), critical=False)
        brain = _stage('brain_refresh', refresh_brain_opportunities) or {}
        _stage('sync_predictions_post_brain', sync_prediction_json_files, critical=False)

        pipeline_log('generating daily review', stage='daily_review')
        _stage('daily_review', lambda: persist_immutable_daily_review())
        _stage('calibration_snapshot', build_calibration_snapshot)
        _stage('adaptive_calibration', _run_adaptive_calibration, critical=False)
        pipeline_log('exporting stats', stage='stats_export')
        _stage('stats_export', lambda: _run_script('stats_exporter.py'))
        pipeline_log('exporting history', stage='history_export')
        _stage('history_export', lambda: _run_script('history_exporter.py'))

        review_result = next((s.get('result') for s in result['stages'] if s.get('name') == 'daily_review'), {}) or {}
        review = (review_result.get('review') or _load_json(DAILY_REVIEWS_DIR / f'review_{_today()}.json', {}))
        if review:
            _stage('telegram_daily_review', lambda: send_telegram_daily_review(review, review.get('lifecycle_summary') or {}), critical=False)

        if failed_critical:
            state.update({
                'pipeline_status': 'FAILED',
                'evaluation_cycle_complete': False,
                'last_failure_at': _now_iso(),
                'last_failure_reason': errors[-1] if errors else 'critical stage failed',
                'errors': errors[-10:],
            })
            save_lifecycle_state(state)
            update_heartbeat(pipeline_status='FAILED', current_stage='failed', extra=state)
            result['status'] = 'failed'
            result['completed_at'] = _now_iso()
            result['errors'] = errors
            pipeline_log(f"FAILED — {errors[-1] if errors else 'critical stage failed'}", stage='complete')
            return result

        state.update({
            'last_eod_cycle_date': today,
            'last_eod_cycle_at': _now_iso(),
            'last_evaluation_at': _now_iso(),
            'evaluation_cycle_complete': True,
            'pipeline_status': 'COMPLETE',
            'brain_refresh_at': _now_iso(),
            'exports_synced_at': _now_iso(),
            'last_successful_eod': _now_iso(),
            'last_stats_export': _now_iso(),
            'last_history_export': _now_iso(),
            'last_calibration_export': _now_iso(),
            'last_journal_generation': _now_iso(),
            'last_brain_refresh': _now_iso(),
            'recovery_reason': None,
            'active_count': sync_stats.get('active', 0) if sync_stats else state.get('active_count', 0),
            'archived_count': sync_stats.get('archived', 0) if sync_stats else state.get('archived_count', 0),
            'stale_invalidated': (inv_stats.get('invalidated') or 0) + (brain.get('removed') or 0),
            'cycles_today': (state.get('cycles_today') or 0) + 1,
            'errors': errors[-10:],
        })
        save_lifecycle_state(state)
        update_heartbeat(pipeline_status='COMPLETE', current_stage='completed', extra=state)

        result['status'] = 'ok' if not errors else 'partial'
        result['completed_at'] = _now_iso()
        result['lifecycle_state'] = state
        result['errors'] = errors
        pipeline_log(
            f"completed successfully — active={state['active_count']} archived={state['archived_count']}",
            stage='complete',
        )
        return result
    except Exception as e:
        log_error('run_end_of_day_cycle', e, stage='fatal')
        state = load_lifecycle_state()
        state.update({
            'pipeline_status': 'FAILED',
            'evaluation_cycle_complete': False,
            'last_failure_at': _now_iso(),
            'last_failure_reason': str(e),
        })
        save_lifecycle_state(state)
        update_heartbeat(pipeline_status='FAILED', current_stage='fatal', extra={'last_failure_reason': str(e)})
        result['status'] = 'failed'
        result['error'] = str(e)
        pipeline_log(f"fatal error: {e}", stage='complete')
        return result
    finally:
        os.environ.pop('LIFECYCLE_CACHE_ONLY', None)
        release_lock(lock_name)


def get_lifecycle_status() -> dict:
    """Runtime freshness payload for OPS / UI."""
    state = load_lifecycle_state()
    today = _today()
    cycle_today = state.get('last_eod_cycle_date') == today
    stats_age = _file_age_minutes(STATS_FILE)
    history_age = _file_age_minutes(HISTORY_FILE)
    cal_age = _file_age_minutes(CALIBRATION_HISTORY_FILE)
    brain_age = _file_age_minutes(INTELLIGENCE_FILE)

    review_age = _file_age_minutes(DAILY_REVIEWS_DIR / f'review_{_today()}.json')
    active_file = _load_json(ACTIVE_PREDICTIONS_FILE, {})
    history_file = _load_json(PREDICTION_HISTORY_FILE, {})
    unresolved = sum(1 for p in (active_file.get('predictions') or []) if p.get('state') == UNRESOLVED_STATE)

    pipeline_status = state.get('pipeline_status') or 'IDLE'
    if pipeline_status == 'RUNNING':
        display_status = 'RUNNING'
    elif pipeline_status == 'RECOVERING':
        display_status = 'RECOVERING'
    elif pipeline_status == 'FAILED':
        display_status = 'FAILED'
    elif cycle_today and state.get('evaluation_cycle_complete') and pipeline_status == 'COMPLETE':
        display_status = 'COMPLETE'
    else:
        display_status = 'STALE'

    return {
        'status': 'healthy' if display_status == 'COMPLETE' else display_status.lower(),
        'pipeline_status': display_status,
        'evaluation_cycle_complete': bool(state.get('evaluation_cycle_complete')),
        'last_eod_cycle_date': state.get('last_eod_cycle_date'),
        'last_eod_cycle_at': state.get('last_eod_cycle_at'),
        'last_evaluation_at': state.get('last_evaluation_at'),
        'brain_refresh_at': state.get('brain_refresh_at'),
        'exports_synced_at': state.get('exports_synced_at'),
        'last_stats_export': state.get('last_stats_export'),
        'last_history_export': state.get('last_history_export'),
        'last_calibration_export': state.get('last_calibration_export'),
        'last_journal_generation': state.get('last_journal_generation'),
        'last_successful_eod': state.get('last_successful_eod'),
        'recovery_reason': state.get('recovery_reason'),
        'active_predictions': state.get('active_count', active_file.get('count', 0)),
        'archived_predictions': state.get('archived_count', history_file.get('count', 0)),
        'unresolved_predictions': unresolved,
        'stale_invalidated': state.get('stale_invalidated', 0),
        'stats_age_minutes': stats_age,
        'history_age_minutes': history_age,
        'calibration_age_minutes': cal_age,
        'review_age_minutes': review_age,
        'brain_age_minutes': brain_age,
        'exports_fresh': stats_age is not None and stats_age < 360 and cycle_today,
        'calibration_fresh': cal_age is not None and cal_age < 360 and cycle_today,
        'review_fresh': review_age is not None and review_age < 720 and cycle_today,
        'message': (
            'Recovering missed post-market EOD cycle…'
            if display_status == 'RECOVERING'
            else (
                f'Lifecycle {display_status}'
                if display_status != 'COMPLETE'
                else 'Post-market evaluation complete'
            )
        ),
        'calibration_message': (
            'Awaiting evaluated prediction sample size.'
            if (_load_json(CALIBRATION_HISTORY_FILE, {}).get('latest') or {}).get('total_evaluated', 0) < 30
            else 'Calibration metrics synchronized from lifecycle.'
        ),
        'current_stage': state.get('current_stage'),
        'last_failure_reason': state.get('last_failure_reason'),
        'stage_history': (state.get('stage_history') or [])[-5:],
    }


def get_lifecycle_ops_payload() -> dict:
    """Extended OPS debug payload — operational heartbeat."""
    status = get_lifecycle_status()
    cal = _load_json(CALIBRATION_HISTORY_FILE, {}).get('latest') or {}
    active = _load_json(ACTIVE_PREDICTIONS_FILE, {})
    ml = get_ml_core_status()
    try:
        from backend.orchestration.schedule_registry import get_task_registry
        scheduler_tasks = get_task_registry()
    except Exception:
        scheduler_tasks = {}
    return {
        **status,
        'ml_core': ml,
        'scheduler_tasks': scheduler_tasks,
        'calibration': cal,
        'active_predictions_file': {
            'count': active.get('count', 0),
            'updated_at': active.get('updated_at'),
            'path': str(ACTIVE_PREDICTIONS_FILE.name),
        },
        'archived_predictions_file': {
            'count': _load_json(PREDICTION_HISTORY_FILE, {}).get('count', 0),
            'updated_at': _load_json(PREDICTION_HISTORY_FILE, {}).get('updated_at'),
            'path': str(PREDICTION_HISTORY_FILE.name),
        },
        'prediction_states': _count_states_from_history(),
        'adaptive_ready': (cal.get('confidence_realism_curve') or {}).get('adaptive_ready', False),
    }


def _count_states_from_history() -> dict:
    history = _load_json(PREDICTION_HISTORY_FILE, {}).get('predictions') or []
    counts: Dict[str, int] = {}
    for p in history:
        st = p.get('state') or 'UNKNOWN'
        counts[st] = counts.get(st, 0) + 1
    active = _load_json(ACTIVE_PREDICTIONS_FILE, {}).get('predictions') or []
    for p in active:
        st = p.get('state') or 'ACTIVE'
        counts[st] = counts.get(st, 0) + 1
    return counts


def get_ml_core_status() -> dict:
    """
    ML Core health — meta labeler + lifecycle + calibration freshness.
    Replaces simple file-existence check in Telegram /status.
    """
    hc_exists = HIGH_CONVICTION_FILE.exists()
    hc_age = _file_age_minutes(HIGH_CONVICTION_FILE)
    lifecycle = get_lifecycle_status()
    cal = _load_json(CALIBRATION_HISTORY_FILE, {}).get('latest') or {}

    meta_ok = hc_exists and hc_age is not None and hc_age < 1440
    lifecycle_ok = lifecycle.get('evaluation_cycle_complete') and lifecycle.get('status') == 'healthy'
    cal_ok = lifecycle.get('calibration_fresh') or bool(cal.get('total_evaluated'))
    exports_ok = lifecycle.get('exports_fresh')

    if meta_ok and lifecycle_ok and exports_ok:
        status = 'healthy'
        emoji = '✅'
    elif meta_ok or lifecycle_ok or hc_exists or exports_ok:
        status = 'degraded'
        emoji = '⚠️'
    else:
        status = 'missing'
        emoji = '❌'

    parts = []
    if hc_exists and hc_age is not None:
        parts.append(f'meta {hc_age}m')
    if lifecycle_ok:
        parts.append('lifecycle ok')
    if exports_ok:
        parts.append('exports synced')
    detail = ' · '.join(parts) if parts else 'pending first EOD cycle'
    return {
        'status': status,
        'emoji': emoji,
        'label': 'ML Core',
        'display': f"{emoji} ML Core: {detail}",
        'meta_labeler_fresh': meta_ok,
        'lifecycle_engine_healthy': lifecycle_ok,
        'calibration_engine_fresh': cal_ok,
        'exporter_fresh': exports_ok,
        'high_conviction_age_minutes': hc_age,
        'lifecycle': lifecycle,
    }


if __name__ == '__main__':
    import sys
    force = '--force' in sys.argv
    out = run_end_of_day_cycle(force=force)
    print(out)
