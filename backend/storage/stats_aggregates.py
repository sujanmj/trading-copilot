"""
Single source of truth for prediction/outcome/calibration counters.

All Telegram, GUI, OPS, API, and JSON exports MUST derive from these functions.
SQLite predictions + outcomes tables are authoritative; JSON files are snapshots only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from backend.storage.db_manager import get_connection, get_db_stats, init_db

RESOLVED_VERDICTS = ('WIN', 'LOSS', 'PARTIAL', 'NEUTRAL', 'EXPIRED', 'INVALIDATED')
ACTIONABLE_VERDICTS = ('WIN', 'LOSS', 'PARTIAL', 'NEUTRAL')
PENDING_VERDICTS = ('PENDING', 'UNRESOLVED')


def _date_filter(metric_type: str, prefix: str = 'p') -> str:
    if metric_type == 'daily':
        return f"AND {prefix}.prediction_date = date('now')"
    if metric_type == 'weekly':
        return f"AND {prefix}.prediction_date >= date('now', '-7 days')"
    return ''


def _empty_block(metric_type: str) -> Dict[str, Any]:
    return {
        'metric_date': datetime.now().date().isoformat(),
        'metric_type': metric_type,
        'total_predictions': 0,
        'total_evaluated': 0,
        'wins': 0,
        'losses': 0,
        'neutral': 0,
        'partials': 0,
        'expired': 0,
        'invalidated': 0,
        'pending': 0,
        'unresolved': 0,
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


def aggregate_outcomes(metric_type: str = 'all_time') -> Dict[str, Any]:
    """Canonical outcome counters from SQLite (predictions + linked outcomes)."""
    init_db()
    conn = get_connection()
    date_filter = _date_filter(metric_type)
    try:
        row = conn.execute(
            f"""
            SELECT
                COUNT(p.id) as total_predictions,
                SUM(CASE WHEN o.verdict IN ('WIN','LOSS','PARTIAL','NEUTRAL','EXPIRED','INVALIDATED') THEN 1 ELSE 0 END) as total_evaluated,
                SUM(CASE WHEN o.verdict='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN o.verdict='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN o.verdict IN ('NEUTRAL','PARTIAL') THEN 1 ELSE 0 END) as neutral,
                SUM(CASE WHEN o.verdict='PARTIAL' THEN 1 ELSE 0 END) as partials,
                SUM(CASE WHEN o.verdict='EXPIRED' THEN 1 ELSE 0 END) as expired,
                SUM(CASE WHEN o.verdict='INVALIDATED' THEN 1 ELSE 0 END) as invalidated,
                SUM(CASE WHEN o.verdict='UNRESOLVED' THEN 1 ELSE 0 END) as unresolved,
                SUM(CASE WHEN o.verdict='PENDING' THEN 1 ELSE 0 END) as pending_verdict,
                SUM(CASE WHEN o.id IS NULL THEN 1 ELSE 0 END) as predictions_without_outcome,
                AVG(CASE WHEN o.verdict='WIN' THEN o.max_gain_pct END) as avg_gain,
                AVG(CASE WHEN o.verdict='LOSS' THEN o.max_loss_pct END) as avg_loss,
                SUM(CASE WHEN p.category='opportunity' AND o.verdict='WIN' THEN 1 ELSE 0 END) as opp_wins,
                SUM(CASE WHEN p.category='opportunity' AND o.verdict IS NOT NULL AND o.verdict != 'PENDING' THEN 1 ELSE 0 END) as opp_total,
                SUM(CASE WHEN p.category='risk' AND o.verdict='LOSS' THEN 1 ELSE 0 END) as risk_correct,
                SUM(CASE WHEN p.category='risk' AND o.verdict IS NOT NULL AND o.verdict != 'PENDING' THEN 1 ELSE 0 END) as risk_total,
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict='WIN' THEN 1 ELSE 0 END) as high_wins,
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict IS NOT NULL AND o.verdict NOT IN ('PENDING','UNRESOLVED') THEN 1 ELSE 0 END) as high_total,
                SUM(CASE WHEN p.confidence='MEDIUM' AND o.verdict='WIN' THEN 1 ELSE 0 END) as med_wins,
                SUM(CASE WHEN p.confidence='MEDIUM' AND o.verdict IS NOT NULL AND o.verdict NOT IN ('PENDING','UNRESOLVED') THEN 1 ELSE 0 END) as med_total,
                SUM(CASE WHEN p.confidence='LOW' AND o.verdict='WIN' THEN 1 ELSE 0 END) as low_wins,
                SUM(CASE WHEN p.confidence='LOW' AND o.verdict IS NOT NULL AND o.verdict NOT IN ('PENDING','UNRESOLVED') THEN 1 ELSE 0 END) as low_total
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE 1=1 {date_filter}
            """
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return _empty_block(metric_type)

    d = dict(row)
    wins = d.get('wins') or 0
    losses = d.get('losses') or 0
    neutral = d.get('neutral') or 0
    partials = d.get('partials') or 0
    evaluated = d.get('total_evaluated') or 0
    pending = (d.get('pending_verdict') or 0) + (d.get('unresolved') or 0) + (d.get('predictions_without_outcome') or 0)

    actionable = wins + losses + neutral
    avg_gain = d.get('avg_gain') or 0
    avg_loss = abs(d.get('avg_loss') or 0)
    profit_factor = avg_gain / avg_loss if avg_loss > 0 else 0

    return {
        'metric_date': datetime.now().date().isoformat(),
        'metric_type': metric_type,
        'total_predictions': d.get('total_predictions') or 0,
        'total_evaluated': evaluated,
        'wins': wins,
        'losses': losses,
        'neutral': neutral,
        'partials': partials,
        'expired': d.get('expired') or 0,
        'invalidated': d.get('invalidated') or 0,
        'pending': pending,
        'unresolved': d.get('unresolved') or 0,
        'predictions_without_outcome': d.get('predictions_without_outcome') or 0,
        'win_rate': round((wins / actionable * 100) if actionable > 0 else 0, 2),
        'avg_gain_pct': round(avg_gain, 2),
        'avg_loss_pct': round(avg_loss, 2),
        'profit_factor': round(profit_factor, 2),
        'opportunity_win_rate': round((d.get('opp_wins') or 0) / (d.get('opp_total') or 1) * 100, 2) if d.get('opp_total') else 0,
        'risk_avoidance_rate': round((d.get('risk_correct') or 0) / (d.get('risk_total') or 1) * 100, 2) if d.get('risk_total') else 0,
        'high_conf_win_rate': round((d.get('high_wins') or 0) / (d.get('high_total') or 1) * 100, 2) if d.get('high_total') else 0,
        'medium_conf_win_rate': round((d.get('med_wins') or 0) / (d.get('med_total') or 1) * 100, 2) if d.get('med_total') else 0,
        'low_conf_win_rate': round((d.get('low_wins') or 0) / (d.get('low_total') or 1) * 100, 2) if d.get('low_total') else 0,
    }


def aggregate_calibration() -> Dict[str, Any]:
    """Calibration snapshot fields derived from the same outcome aggregate."""
    core = aggregate_outcomes('all_time')
    evaluated_actionable = (core.get('wins') or 0) + (core.get('losses') or 0) + (core.get('partials') or 0)
    return {
        'generated_at': datetime.now().isoformat(),
        'date': datetime.now().date().isoformat(),
        'win_rate': core.get('win_rate', 0),
        'loss_rate': round((core.get('losses') or 0) / evaluated_actionable * 100, 2) if evaluated_actionable else 0,
        'partial_rate': round((core.get('partials') or 0) / evaluated_actionable * 100, 2) if evaluated_actionable else 0,
        'avg_gain_pct': core.get('avg_gain_pct', 0),
        'avg_loss_pct': core.get('avg_loss_pct', 0),
        'profit_factor': core.get('profit_factor', 0),
        'total_evaluated': evaluated_actionable,
        'total_resolved': core.get('total_evaluated', 0),
        'wins': core.get('wins', 0),
        'losses': core.get('losses', 0),
        'pending': core.get('pending', 0),
        'expired': core.get('expired', 0),
        'invalidated': core.get('invalidated', 0),
        'unresolved': core.get('unresolved', 0),
        'message': (
            'Awaiting evaluated prediction sample size.'
            if evaluated_actionable < 30
            else 'Calibration metrics synchronized from SQLite.'
        ),
        'source': 'sqlite_aggregate',
    }


def aggregate_stats() -> Dict[str, Any]:
    """Full stats payload for exports, Telegram, GUI, and API."""
    init_db()
    return {
        'db_stats': get_db_stats(),
        'metrics_all_time': aggregate_outcomes('all_time'),
        'metrics_weekly': aggregate_outcomes('weekly'),
        'metrics_daily': aggregate_outcomes('daily'),
        'calibration_core': aggregate_calibration(),
    }


def get_live_stats_payload(refresh_export: bool = False) -> Dict[str, Any]:
    """
    Live read from SQLite — never uses stale JSON for counters.
    When refresh_export=True, runs full export_stats() snapshot (includes top winners/losers).
    """
    if refresh_export:
        from backend.storage.stats_exporter import export_stats
        return export_stats()
    return aggregate_stats()


def format_stats_telegram(metrics: Optional[dict] = None, db_stats: Optional[dict] = None) -> str:
    metrics = metrics or aggregate_outcomes('all_time')
    db_stats = db_stats or get_db_stats()
    evaluated = metrics.get('total_evaluated', 0)
    pending = metrics.get('pending', 0)
    wins = metrics.get('wins', 0)
    losses = metrics.get('losses', 0)

    msg = "<b>📊 Trading Copilot Stats</b>\n\n"
    msg += f"<b>Predictions:</b> {db_stats.get('total_predictions', metrics.get('total_predictions', 0))}\n"
    msg += f"<b>Evaluated:</b> {evaluated}\n"
    msg += f"<b>Pending:</b> {pending}\n"
    if wins or losses or evaluated:
        msg += f"<b>Win Rate:</b> {metrics.get('win_rate', 0):.1f}% (actionable)\n"
        msg += f"  ✅ Wins: {wins}\n"
        msg += f"  ❌ Losses: {losses}\n"
        msg += f"<b>Avg Gain:</b> +{metrics.get('avg_gain_pct', 0):.2f}%\n"
        msg += f"<b>Avg Loss:</b> -{metrics.get('avg_loss_pct', 0):.2f}%\n"
        msg += f"<b>Profit Factor:</b> {metrics.get('profit_factor', 0):.2f}\n"
    else:
        msg += "\n<i>⏳ No resolved outcomes yet — pending predictions evaluate at EOD</i>"
    return msg


def format_outcomes_telegram(metrics: Optional[dict] = None) -> str:
    metrics = metrics or aggregate_outcomes('all_time')
    evaluated = metrics.get('total_evaluated', 0)
    pending = metrics.get('pending', 0)
    wins = metrics.get('wins', 0)
    losses = metrics.get('losses', 0)
    if not (wins or losses or evaluated):
        return (
            "<b>📊 Outcomes</b>\n\n"
            f"Evaluated: {evaluated} | Pending: {pending}\n"
            "<i>Outcomes evaluate at post-market EOD and 8 AM cycle.</i>"
        )
    return (
        f"<b>📊 Outcomes</b>\n\n"
        f"Evaluated: {evaluated} | Win rate: {metrics.get('win_rate', 0):.1f}%\n"
        f"✅ Wins: {wins} | ❌ Losses: {losses} | ⏳ Pending: {pending}"
    )
