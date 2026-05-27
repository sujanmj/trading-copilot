"""
Canonical metrics service — SQLite is the ONLY source of truth.

State rules (global):
  evaluated     = WIN + LOSS + EXPIRED + NEUTRAL
  pending       = ACTIVE + PENDING + UNRESOLVED + predictions without outcome row
  prediction_total = evaluated + pending  (= COUNT(predictions) when partition closes)

All Telegram, API, OPS, GUI, and JSON exports MUST use this module only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from backend.storage.db_manager import get_connection, get_db_stats, init_db

EVALUATED_VERDICTS = ('WIN', 'LOSS', 'EXPIRED', 'NEUTRAL', 'CANCELLED')
PENDING_VERDICTS = ('ACTIVE', 'PENDING')


def _date_filter(metric_type: str, prefix: str = 'p') -> str:
    if metric_type == 'daily':
        return f"AND {prefix}.prediction_date = date('now')"
    if metric_type == 'weekly':
        return f"AND {prefix}.prediction_date >= date('now', '-7 days')"
    return ''


def _empty(metric_type: str = 'all_time') -> Dict[str, Any]:
    return {
        'metric_date': datetime.now().date().isoformat(),
        'metric_type': metric_type,
        'source': 'sqlite_unified_metrics',
        'total_predictions': 0,
        'prediction_total': 0,
        'evaluated': 0,
        'total_evaluated': 0,
        'pending': 0,
        'wins': 0,
        'losses': 0,
        'neutral': 0,
        'partials': 0,
        'expired': 0,
        'invalidated': 0,
        'cancelled': 0,
        'unresolved': 0,
        'active': 0,
        'predictions_without_outcome': 0,
        'win_rate': 0.0,
        'avg_gain_pct': 0.0,
        'avg_loss_pct': 0.0,
        'profit_factor': 0.0,
        'opportunity_win_rate': 0.0,
        'risk_avoidance_rate': 0.0,
        'high_conf_win_rate': 0.0,
        'medium_conf_win_rate': 0.0,
        'low_conf_win_rate': 0.0,
    }


def _query_row(metric_type: str = 'all_time') -> Dict[str, Any]:
    init_db()
    conn = get_connection()
    date_filter = _date_filter(metric_type)
    try:
        row = conn.execute(
            f"""
            SELECT
                COUNT(p.id) AS total_predictions,
                SUM(CASE WHEN o.verdict='WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN o.verdict='LOSS' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN o.verdict='NEUTRAL' THEN 1 ELSE 0 END) AS neutral,
                SUM(CASE WHEN o.verdict='PARTIAL' THEN 1 ELSE 0 END) AS partials,
                SUM(CASE WHEN o.verdict='EXPIRED' THEN 1 ELSE 0 END) AS expired,
                SUM(CASE WHEN o.verdict='CANCELLED' THEN 1 ELSE 0 END) AS cancelled,
                SUM(CASE WHEN o.verdict='INVALIDATED' THEN 1 ELSE 0 END) AS invalidated,
                SUM(CASE WHEN o.verdict='UNRESOLVED' THEN 1 ELSE 0 END) AS unresolved,
                SUM(CASE WHEN o.verdict='ACTIVE' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN o.verdict='PENDING' THEN 1 ELSE 0 END) AS pending_verdict,
                SUM(CASE WHEN o.id IS NULL THEN 1 ELSE 0 END) AS predictions_without_outcome,
                AVG(CASE WHEN o.verdict='WIN' THEN o.max_gain_pct END) AS avg_gain,
                AVG(CASE WHEN o.verdict='LOSS' THEN o.max_loss_pct END) AS avg_loss,
                SUM(CASE WHEN p.category='opportunity' AND o.verdict='WIN' THEN 1 ELSE 0 END) AS opp_wins,
                SUM(CASE WHEN p.category='opportunity' AND o.verdict IS NOT NULL
                    AND o.verdict NOT IN ('PENDING','UNRESOLVED','ACTIVE') THEN 1 ELSE 0 END) AS opp_total,
                SUM(CASE WHEN p.category='risk' AND o.verdict='LOSS' THEN 1 ELSE 0 END) AS risk_correct,
                SUM(CASE WHEN p.category='risk' AND o.verdict IS NOT NULL
                    AND o.verdict NOT IN ('PENDING','UNRESOLVED','ACTIVE') THEN 1 ELSE 0 END) AS risk_total,
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict='WIN' THEN 1 ELSE 0 END) AS high_wins,
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict IS NOT NULL
                    AND o.verdict NOT IN ('PENDING','UNRESOLVED','ACTIVE') THEN 1 ELSE 0 END) AS high_total,
                SUM(CASE WHEN p.confidence='MEDIUM' AND o.verdict='WIN' THEN 1 ELSE 0 END) AS med_wins,
                SUM(CASE WHEN p.confidence='MEDIUM' AND o.verdict IS NOT NULL
                    AND o.verdict NOT IN ('PENDING','UNRESOLVED','ACTIVE') THEN 1 ELSE 0 END) AS med_total,
                SUM(CASE WHEN p.confidence='LOW' AND o.verdict='WIN' THEN 1 ELSE 0 END) AS low_wins,
                SUM(CASE WHEN p.confidence='LOW' AND o.verdict IS NOT NULL
                    AND o.verdict NOT IN ('PENDING','UNRESOLVED','ACTIVE') THEN 1 ELSE 0 END) AS low_total
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE 1=1 {date_filter}
            """
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def _build_from_row(row: Dict[str, Any], metric_type: str = 'all_time') -> Dict[str, Any]:
    if not row:
        return _empty(metric_type)

    wins = int(row.get('wins') or 0)
    losses = int(row.get('losses') or 0)
    neutral = int(row.get('neutral') or 0)
    expired = int(row.get('expired') or 0)
    cancelled = int(row.get('cancelled') or 0)
    partials = int(row.get('partials') or 0)
    invalidated = int(row.get('invalidated') or 0)
    unresolved = int(row.get('unresolved') or 0)
    active = int(row.get('active') or 0)
    pending_verdict = int(row.get('pending_verdict') or 0)
    without_outcome = int(row.get('predictions_without_outcome') or 0)
    total_predictions = int(row.get('total_predictions') or 0)

    evaluated = wins + losses + expired + neutral + cancelled
    pending = active + pending_verdict + unresolved + without_outcome
    prediction_total = evaluated + pending

    remainder = total_predictions - prediction_total - partials - invalidated
    if remainder > 0:
        pending += remainder
        prediction_total = evaluated + pending

    actionable = wins + losses + neutral
    avg_gain = float(row.get('avg_gain') or 0)
    avg_loss = abs(float(row.get('avg_loss') or 0))
    profit_factor = avg_gain / avg_loss if avg_loss > 0 else 0.0

    metrics = _empty(metric_type)
    metrics.update({
        'total_predictions': total_predictions,
        'prediction_total': prediction_total,
        'evaluated': evaluated,
        'total_evaluated': evaluated,
        'pending': pending,
        'wins': wins,
        'losses': losses,
        'neutral': neutral,
        'partials': partials,
        'expired': expired,
        'cancelled': cancelled,
        'invalidated': invalidated,
        'unresolved': unresolved,
        'active': active,
        'predictions_without_outcome': without_outcome,
        'win_rate': round((wins / actionable * 100) if actionable > 0 else 0.0, 2),
        'avg_gain_pct': round(avg_gain, 2),
        'avg_loss_pct': round(avg_loss, 2),
        'profit_factor': round(profit_factor, 2),
        'opportunity_win_rate': round((row.get('opp_wins') or 0) / (row.get('opp_total') or 1) * 100, 2)
            if row.get('opp_total') else 0.0,
        'risk_avoidance_rate': round((row.get('risk_correct') or 0) / (row.get('risk_total') or 1) * 100, 2)
            if row.get('risk_total') else 0.0,
        'high_conf_win_rate': round((row.get('high_wins') or 0) / (row.get('high_total') or 1) * 100, 2)
            if row.get('high_total') else 0.0,
        'medium_conf_win_rate': round((row.get('med_wins') or 0) / (row.get('med_total') or 1) * 100, 2)
            if row.get('med_total') else 0.0,
        'low_conf_win_rate': round((row.get('low_wins') or 0) / (row.get('low_total') or 1) * 100, 2)
            if row.get('low_total') else 0.0,
    })
    return metrics


def get_outcome_metrics(metric_type: str = 'all_time') -> Dict[str, Any]:
    """Canonical outcome counters — SQLite only."""
    return _build_from_row(_query_row(metric_type), metric_type)


def get_prediction_metrics(metric_type: str = 'all_time') -> Dict[str, Any]:
    """Prediction-level rollup using canonical outcome metrics."""
    om = get_outcome_metrics(metric_type)
    return {
        'metric_date': om['metric_date'],
        'metric_type': metric_type,
        'source': om['source'],
        'prediction_total': om['prediction_total'],
        'total_predictions': om['total_predictions'],
        'evaluated': om['evaluated'],
        'pending': om['pending'],
        'wins': om['wins'],
        'losses': om['losses'],
        'neutral': om['neutral'],
        'win_rate': om['win_rate'],
        'avg_gain_pct': om['avg_gain_pct'],
        'avg_loss_pct': om['avg_loss_pct'],
        'profit_factor': om['profit_factor'],
    }


def get_calibration_metrics() -> Dict[str, Any]:
    """Calibration snapshot — same core counts as outcome metrics."""
    from backend.calibration.calibration_state import build_calibration_display

    core = get_outcome_metrics('all_time')
    actionable = (core.get('wins') or 0) + (core.get('losses') or 0) + (core.get('neutral') or 0)
    phase_info = build_calibration_display(core)
    return {
        'generated_at': datetime.now().isoformat(),
        'date': datetime.now().date().isoformat(),
        'source': 'sqlite_unified_metrics',
        'prediction_total': core['prediction_total'],
        'total_predictions': core['total_predictions'],
        'evaluated': core['evaluated'],
        'total_evaluated': core['evaluated'],
        'pending': core['pending'],
        'wins': core['wins'],
        'losses': core['losses'],
        'neutral': core['neutral'],
        'partials': core['partials'],
        'expired': core['expired'],
        'cancelled': core.get('cancelled', 0),
        'invalidated': core['invalidated'],
        'win_rate': core['win_rate'] if phase_info.get('show_win_rate') else None,
        'loss_rate': round((core['losses'] / actionable * 100) if actionable and phase_info.get('show_win_rate') else 0.0, 2),
        'avg_gain_pct': core['avg_gain_pct'],
        'avg_loss_pct': core['avg_loss_pct'],
        'profit_factor': core['profit_factor'],
        'calibration_phase': phase_info.get('phase'),
        'resolved_sample': phase_info.get('resolved_sample'),
        'suppress_adaptive': phase_info.get('suppress_adaptive'),
        'message': phase_info.get('message') or _calibration_status_message(actionable),
    }


def _calibration_status_message(actionable: int) -> str:
    if actionable < 5:
        return 'Adaptive learning still collecting statistically meaningful samples.'
    if actionable < 20:
        return 'Low-confidence calibration — sample still developing.'
    if actionable >= 50:
        return 'Adaptive confidence enabled — metrics synchronized from SQLite.'
    return 'Calibration metrics synchronized from SQLite.'


def get_unified_snapshot() -> Dict[str, Any]:
    """Full metrics bundle for exports, API runtime, and Telegram."""
    init_db()
    return {
        'generated_at': datetime.now().isoformat(),
        'source': 'sqlite_unified_metrics',
        'db_stats': get_db_stats(),
        'predictions': get_prediction_metrics('all_time'),
        'metrics_all_time': get_outcome_metrics('all_time'),
        'metrics_weekly': get_outcome_metrics('weekly'),
        'metrics_daily': get_outcome_metrics('daily'),
        'calibration': get_calibration_metrics(),
        'partition_validation': __import__(
            'backend.lifecycle.eod_reconciliation_engine', fromlist=['validate_metrics_partition']
        ).validate_metrics_partition(),
    }


def get_metrics_for_telegram() -> Dict[str, Any]:
    """Identical snapshot for /stats, /outcomes, /calibration, /summary."""
    snap = get_unified_snapshot()
    pending_classification = _get_pending_classification_safe()
    return {
        'snapshot': snap,
        'metrics': snap['metrics_all_time'],
        'metrics_daily': snap['metrics_daily'],
        'metrics_all_time': snap['metrics_all_time'],
        'calibration': snap['calibration'],
        'predictions': snap['predictions'],
        'pending_classification': pending_classification,
    }


def _get_pending_classification_safe() -> Dict[str, Any]:
    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_pending_classification
        return get_pending_classification()
    except Exception:
        return {
            'active_pending': 0,
            'expired_pending': 0,
            'low_data_pending': 0,
            'neutralized_today': 0,
            'pending_active': 0,
            'expired': 0,
            'neutralized': 0,
            'total_open': 0,
        }


def get_pending_classification_metrics() -> Dict[str, Any]:
    """Public alias for pending bucket counts."""
    return _get_pending_classification_safe()


def _win_rate_line(m: dict, actionable: int) -> str:
    if actionable < 5:
        if (m.get('wins') or 0) > 0 and actionable > 0:
            return '<i>Early positive sample detected.</i>\n'
        return '<i>Win rate withheld — sample below minimum threshold.</i>\n'
    return f"<b>Win Rate:</b> {m.get('win_rate', 0):.1f}%\n"


def format_stats_telegram(metrics: Optional[dict] = None, *, session: str = 'today') -> str:
    snap = get_unified_snapshot()
    if metrics is not None:
        m = metrics
        label = 'TODAY SESSION' if session == 'today' else 'HISTORICAL LEARNING'
    elif session == 'historical':
        m = snap['metrics_all_time']
        label = 'HISTORICAL LEARNING'
    else:
        m = snap['metrics_daily']
        label = 'TODAY SESSION'

    actionable = (m.get('wins') or 0) + (m.get('losses') or 0) + (m.get('neutral') or 0)
    pending_cls = _get_pending_classification_safe()
    msg = f"<b>📊 Trading Copilot Stats</b>\n<b>{label}</b>\n\n"
    msg += f"<b>Predictions:</b> {m.get('prediction_total', m.get('total_predictions', 0))}\n"
    msg += f"<b>Evaluated:</b> {m.get('evaluated', m.get('total_evaluated', 0))}\n"
    msg += f"<b>Pending Active:</b> {pending_cls.get('pending_active', m.get('pending', 0))}\n"
    if pending_cls.get('expired') or pending_cls.get('low_data_pending'):
        msg += (
            f"<i>Expired: {pending_cls.get('expired', 0)} · "
            f"Low-data: {pending_cls.get('low_data_pending', 0)} · "
            f"Neutralized today: {pending_cls.get('neutralized_today', 0)}</i>\n"
        )
    if m.get('wins') or m.get('losses') or m.get('evaluated'):
        msg += _win_rate_line(m, actionable)
        msg += f"  ✅ Wins: {m.get('wins', 0)}\n"
        msg += f"  ❌ Losses: {m.get('losses', 0)}\n"
        if actionable >= 5:
            msg += f"<b>Avg Gain:</b> +{m.get('avg_gain_pct', 0):.2f}%\n"
            msg += f"<b>Avg Loss:</b> -{m.get('avg_loss_pct', 0):.2f}%\n"
            msg += f"<b>Profit Factor:</b> {m.get('profit_factor', 0):.2f}\n"
    else:
        msg += "\n<i>⏳ No resolved outcomes yet — pending predictions evaluate at EOD</i>"
    return msg


def format_outcomes_telegram(metrics: Optional[dict] = None) -> str:
    snap = get_unified_snapshot()
    daily = snap['metrics_daily']
    historical = metrics or snap['metrics_all_time']
    pending_cls = _get_pending_classification_safe()

    daily_resolved = int(daily.get('evaluated', daily.get('total_evaluated', 0)) or 0)
    hist_evaluated = historical.get('evaluated', historical.get('total_evaluated', 0))
    wins = historical.get('wins', 0)
    losses = historical.get('losses', 0)
    actionable = wins + losses + (historical.get('neutral') or 0)

    msg = "<b>📊 Outcomes</b>\n\n"
    msg += "<b>LIVE SESSION</b>\n"
    msg += f"Resolved: {daily_resolved}\n"
    msg += f"Pending Active: {pending_cls.get('pending_active', 0)}\n"
    msg += f"Expired: {pending_cls.get('expired', 0)}\n"
    msg += f"Neutralized: {pending_cls.get('neutralized_today', 0)}\n\n"
    msg += "<b>Historical Calibration</b>\n"

    if not (wins or losses or hist_evaluated):
        msg += f"Evaluated: {hist_evaluated}\n"
        msg += "<i>Outcomes evaluate at post-market EOD and 8 AM cycle.</i>"
        return msg

    if actionable < 5:
        msg += (
            f"Evaluated: {hist_evaluated} · Wins: {wins} · Losses: {losses}\n"
            "<i>Early positive sample detected.</i>"
        )
        return msg

    msg += f"Win rate: {historical.get('win_rate', 0):.1f}%\n"
    msg += f"✅ Wins: {wins} | ❌ Losses: {losses} | 📊 Evaluated: {hist_evaluated}"
    return msg


def format_calibration_telegram(cal: Optional[dict] = None) -> str:
    c = cal or get_calibration_metrics()
    phase = c.get('calibration_phase') or 'LEARNING'
    msg = f"<b>🎯 Calibration</b> · <b>{phase}</b>\n\n"
    msg += f"Predictions: {c.get('prediction_total', 0)} · Evaluated: {c.get('evaluated', c.get('total_evaluated', 0))}\n"
    msg += f"Pending: {c.get('pending', 0)} · Resolved sample: {c.get('resolved_sample', 0)}\n"
    if c.get('show_win_rate') or (c.get('resolved_sample') or 0) >= 20:
        msg += f"Win rate: {c.get('win_rate', 0):.1f}% · Wins: {c.get('wins', 0)} · Losses: {c.get('losses', 0)}\n"
    msg += f"<i>{c.get('message', '')}</i>"
    return msg


def embed_metrics_in_lifecycle_state(state: dict) -> dict:
    """Attach canonical metrics to lifecycle_state.json snapshot."""
    snap = get_unified_snapshot()
    state['unified_metrics'] = {
        'predictions': snap['predictions'],
        'evaluated': snap['metrics_all_time']['evaluated'],
        'pending': snap['metrics_all_time']['pending'],
        'wins': snap['metrics_all_time']['wins'],
        'losses': snap['metrics_all_time']['losses'],
        'win_rate': snap['metrics_all_time']['win_rate'],
        'generated_at': snap['generated_at'],
    }
    return state
