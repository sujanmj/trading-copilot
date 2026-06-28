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

import pytz

from backend.storage.db_manager import get_connection, get_db_stats, init_db

IST = pytz.timezone('Asia/Kolkata')

EVALUATED_VERDICTS = ('WIN', 'LOSS', 'EXPIRED', 'NEUTRAL', 'CANCELLED')
PENDING_VERDICTS = ('ACTIVE', 'PENDING')


def _ist_today_iso() -> str:
    return datetime.now(IST).date().isoformat()


def _date_filter(metric_type: str, prefix: str = 'p') -> str:
    if metric_type == 'daily':
        today = _ist_today_iso()
        return f"AND {prefix}.prediction_date = '{today}'"
    if metric_type == 'weekly':
        today = _ist_today_iso()
        return (
            f"AND {prefix}.prediction_date >= date('{today}', '-7 days') "
            f"AND {prefix}.prediction_date <= '{today}'"
        )
    return ''


def _empty(metric_type: str = 'all_time') -> Dict[str, Any]:
    return {
        'metric_date': _ist_today_iso(),
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
        'win_rate': None,
        'resolved': 0,
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

    from backend.metrics.canonical_metrics import build_canonical_metrics

    raw_metrics = {
        'metric_date': _ist_today_iso(),
        'metric_type': metric_type,
        'source': 'sqlite_unified_metrics',
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
    }
    return build_canonical_metrics(raw_metrics)


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
        'date': _ist_today_iso(),
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
    all_time = get_outcome_metrics('all_time')
    daily = get_outcome_metrics('daily')
    calibration = get_calibration_metrics()
    pending_cls = _get_pending_classification_safe()
    from backend.metrics.canonical_metrics import build_metric_sections

    sections = build_metric_sections(
        all_time=all_time,
        daily=daily,
        pending_classification=pending_cls,
        calibration=calibration,
    )
    all_time = {**all_time, 'sections': sections}
    daily = {**daily, 'sections': sections}
    lifecycle_validation = _validate_sqlite_lifecycle()
    return {
        'generated_at': datetime.now().isoformat(),
        'source': 'sqlite_unified_metrics',
        'db_stats': get_db_stats(),
        'predictions': get_prediction_metrics('all_time'),
        'metrics_all_time': all_time,
        'metrics_weekly': get_outcome_metrics('weekly'),
        'metrics_daily': daily,
        'calibration': calibration,
        'metric_sections': sections,
        'pending_classification': pending_cls,
        'partition_validation': __import__(
            'backend.lifecycle.eod_reconciliation_engine', fromlist=['validate_metrics_partition']
        ).validate_metrics_partition(),
        'lifecycle_validation': lifecycle_validation,
    }


def _validate_sqlite_lifecycle() -> Dict[str, Any]:
    """Reconcile raw prediction rows — export/API must not use frontend-derived counts."""
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT p.id, o.verdict, o.verdict AS state
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            """
        ).fetchall()
        records = [dict(r) for r in rows]
    finally:
        conn.close()
    from backend.lifecycle.prediction_reconciliation import validate_prediction_lifecycle
    return validate_prediction_lifecycle(records)


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
    from backend.lifecycle.win_rate_engine import format_win_rate_line
    return format_win_rate_line(m)


def _active_book_count_label() -> str:
    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_active_predictions_payload

        payload = get_active_predictions_payload()
        count = payload.get('count')
        if count is None:
            preds = payload.get('predictions') or []
            count = len(preds) if isinstance(preds, list) else 0
        source = payload.get('source') or 'active_predictions'
        return f"{int(count)} ({source})"
    except Exception:
        return "unavailable"


def format_stats_telegram(metrics: Optional[dict] = None, *, session: str = 'today') -> str:
    snap = get_unified_snapshot()
    sections = snap.get('metric_sections') or {}
    if metrics is not None and not sections:
        from backend.metrics.canonical_metrics import build_metric_sections
        sections = build_metric_sections(
            all_time=metrics if session == 'historical' else snap['metrics_all_time'],
            daily=snap['metrics_daily'],
            pending_classification=snap.get('pending_classification'),
            calibration=snap.get('calibration'),
        )
    live = sections.get('live_session') or {}
    hist = sections.get('historical_calibration') or {}
    archived = sections.get('archived') or {}

    msg = '<b>📊 Trading Copilot Stats</b>\n\n'
    msg += '<b>LIVE SESSION</b>\n'
    msg += f"Active book: {_active_book_count_label()}\n"
    msg += f"Live-session pending: {live.get('active_predictions', live.get('pending', 0))}\n"
    msg += f"Resolved today: {live.get('resolved_today', 0)}"
    if live.get('wins_today') or live.get('losses_today'):
        msg += f" · {live.get('wins_today', 0)}W/{live.get('losses_today', 0)}L"
    msg += '\n\n'

    msg += '<b>HISTORICAL CALIBRATION</b>\n'
    msg += f"Evaluated sample: {hist.get('evaluated_sample', 0)}\n"
    msg += f"Wins: {hist.get('wins', 0)} · Losses: {hist.get('losses', 0)}\n"
    wr_disp = hist.get('win_rate_display') or 'Awaiting statistical confidence'
    msg += f"Win rate: {wr_disp}\n"
    if hist.get('calibration_confidence'):
        msg += f"<i>{hist.get('calibration_confidence')}</i>\n"

    msg += '\n<b>ARCHIVED</b>\n'
    msg += f"Expired: {archived.get('expired', 0)} · Neutralized: {archived.get('neutralized', 0)}"
    return msg


def format_outcomes_telegram(metrics: Optional[dict] = None) -> str:
    snap = get_unified_snapshot()
    sections = snap.get('metric_sections') or {}
    if metrics is not None and not sections:
        from backend.metrics.canonical_metrics import build_metric_sections
        sections = build_metric_sections(
            all_time=metrics or snap['metrics_all_time'],
            daily=snap['metrics_daily'],
            pending_classification=snap.get('pending_classification'),
            calibration=snap.get('calibration'),
        )
    live = sections.get('live_session') or {}
    hist = sections.get('historical_calibration') or {}
    archived = sections.get('archived') or {}

    msg = '<b>📊 Outcomes</b>\n\n'
    msg += '<b>LIVE SESSION</b>\n'
    msg += f"Active book: {_active_book_count_label()}\n"
    msg += f"Live-session pending: {live.get('active_predictions', live.get('pending', 0))}\n"
    msg += f"Resolved today: {live.get('resolved_today', 0)}\n\n"

    msg += '<b>HISTORICAL CALIBRATION</b>\n'
    evaluated = hist.get('evaluated_sample', 0)
    wins = hist.get('wins', 0)
    losses = hist.get('losses', 0)
    if not (wins or losses or evaluated):
        msg += f"Evaluated sample: {evaluated}\n"
        msg += '<i>Outcomes evaluate at post-market EOD and 8 AM cycle.</i>\n\n'
    else:
        from backend.lifecycle.win_rate_engine import win_rate_denominator
        actionable = win_rate_denominator(wins, losses)
        if actionable < 5:
            msg += (
                f"Evaluated sample: {evaluated} · Wins: {wins} · Losses: {losses}\n"
                '<i>Early positive sample detected.</i>\n\n'
            )
        else:
            from backend.metrics.format_helpers import safe_pct
            msg += f"Evaluated sample: {evaluated}\n"
            msg += f"Win rate: {safe_pct(hist.get('win_rate'))}\n"
            msg += f"✅ Wins: {wins} | ❌ Losses: {losses}\n\n"

    msg += '<b>ARCHIVED</b>\n'
    msg += f"Expired: {archived.get('expired', 0)} · Neutralized: {archived.get('neutralized', 0)}"
    return msg


def format_calibration_telegram(cal: Optional[dict] = None) -> str:
    from backend.metrics.format_helpers import safe_pct
    snap = get_unified_snapshot()
    sections = snap.get('metric_sections') or {}
    hist = sections.get('historical_calibration') or {}
    archived = sections.get('archived') or {}
    c = cal or get_calibration_metrics()
    phase = c.get('calibration_phase') or hist.get('calibration_phase') or 'LEARNING'
    msg = f"<b>🎯 Calibration</b> · <b>{phase}</b>\n\n"
    msg += '<b>HISTORICAL CALIBRATION</b>\n'
    msg += f"Evaluated sample: {hist.get('evaluated_sample', c.get('evaluated', 0))}\n"
    msg += f"Wins: {hist.get('wins', c.get('wins', 0))} · Losses: {hist.get('losses', c.get('losses', 0))}\n"
    if c.get('show_win_rate') or (c.get('resolved_sample') or 0) >= 20 or hist.get('statistically_confident'):
        wr = safe_pct(hist.get('win_rate') if hist.get('win_rate') is not None else c.get('win_rate'))
        msg += f"Win rate: {wr}\n"
    msg += f"<i>{c.get('message') or hist.get('calibration_confidence') or ''}</i>\n"
    msg += f"\n<b>ARCHIVED</b>\nExpired: {archived.get('expired', 0)} · Neutralized: {archived.get('neutralized', 0)}"
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
