"""
EOD outcome scoring for Telegram daily review (Stage 46G).

Fixes W0/L0/N0 when resolved count > 0 by scoring predictions and telegram alerts.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.db_manager import get_connection, init_db

IST = ZoneInfo('Asia/Kolkata')

TERMINAL_VERDICTS = frozenset({'WIN', 'LOSS', 'NEUTRAL', 'PARTIAL', 'EXPIRED', 'PENDING'})
ALERT_TYPE_MAP = {
    'PRE_MARKET': 'premarket',
    'INTRADAY_OPPORTUNITY': 'open_setup',
    'INTRADAY_EVENT': 'intraday',
    'EMERGENCY_MACRO_ALERT': 'emergency_macro',
    'MARKET_CLOSE_SUMMARY': 'close',
    'MIDDAY_UPDATE': 'intraday',
}


def _today() -> str:
    return datetime.now(IST).strftime('%Y-%m-%d')


def _log(msg: str) -> None:
    print(f'[EOD_OUTCOME] {msg}', flush=True)


def _bucket_verdict(verdict: Optional[str]) -> str:
    v = (verdict or 'PENDING').upper()
    if v in TERMINAL_VERDICTS:
        return v
    if v in ('INVALIDATED', 'UNRESOLVED', 'ACTIVE'):
        return 'EXPIRED'
    return 'PENDING'


def _query_prediction_outcomes(review_date: str) -> dict:
    init_db()
    conn = get_connection()
    counts = {'WIN': 0, 'LOSS': 0, 'NEUTRAL': 0, 'PARTIAL': 0, 'EXPIRED': 0, 'PENDING': 0}
    rows_out: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT p.ticker, p.signal_type, p.prediction_date, o.verdict,
                   o.change_1d_pct, o.max_gain_pct, o.max_loss_pct, o.last_checked
            FROM outcomes o
            INNER JOIN predictions p ON o.source_type='prediction' AND o.source_id=p.id
            WHERE o.last_checked LIKE ?
              AND o.verdict IS NOT NULL
            ORDER BY o.last_checked DESC
            LIMIT 500
            """,
            (f'{review_date}%',),
        ).fetchall()
        for row in rows:
            d = dict(row)
            bucket = _bucket_verdict(d.get('verdict'))
            counts[bucket] = counts.get(bucket, 0) + 1
            pct = d.get('change_1d_pct')
            if pct is None:
                pct = d.get('max_gain_pct') if bucket == 'WIN' else d.get('max_loss_pct')
            rows_out.append({
                'ticker': d.get('ticker'),
                'verdict': bucket,
                'pct': pct,
                'alert_type': 'prediction',
                'signal_type': d.get('signal_type'),
            })
    except Exception as exc:
        _log(f'prediction query error: {exc}')
    finally:
        conn.close()
    return {'counts': counts, 'rows': rows_out}


def _query_telegram_alert_outcomes(review_date: str) -> dict:
    init_db()
    conn = get_connection()
    by_type: dict[str, dict[str, int]] = {}
    rows_out: list[dict] = []
    price_missing = False
    try:
        rows = conn.execute(
            """
            SELECT e.source AS category, e.ticker, e.direction, h.hit_miss, h.change_pct,
                   e.entry_price, h.evaluated_at
            FROM signal_events e
            LEFT JOIN signal_horizons h ON h.event_id = e.id
            WHERE e.event_date = ?
              AND e.signal_type = 'telegram'
            ORDER BY e.event_ts DESC
            LIMIT 300
            """,
            (review_date,),
        ).fetchall()
        for row in rows:
            d = dict(row)
            category = str(d.get('category') or '')
            alert_type = ALERT_TYPE_MAP.get(category, 'intraday')
            hit = (d.get('hit_miss') or 'PENDING').upper()
            if hit == 'PENDING' and d.get('entry_price') is None:
                price_missing = True
            bucket = hit if hit in counts_keys() else 'PENDING'
            type_counts = by_type.setdefault(alert_type, {'WIN': 0, 'LOSS': 0, 'NEUTRAL': 0, 'PARTIAL': 0, 'PENDING': 0})
            type_counts[bucket] = type_counts.get(bucket, 0) + 1
            rows_out.append({
                'ticker': d.get('ticker') or category[:12],
                'verdict': bucket,
                'pct': d.get('change_pct'),
                'alert_type': alert_type,
            })
    except Exception as exc:
        _log(f'telegram query error: {exc}')
        price_missing = True
    finally:
        conn.close()
    return {'by_type': by_type, 'rows': rows_out, 'price_missing': price_missing}


def counts_keys() -> set[str]:
    return {'WIN', 'LOSS', 'NEUTRAL', 'PARTIAL', 'EXPIRED', 'PENDING'}


def _top_movers(rows: list[dict], verdict: str, limit: int = 3) -> list[dict]:
    filtered = [r for r in rows if r.get('verdict') == verdict and r.get('pct') is not None]
    if verdict == 'WIN':
        filtered.sort(key=lambda r: float(r.get('pct') or 0), reverse=True)
    elif verdict == 'LOSS':
        filtered.sort(key=lambda r: float(r.get('pct') or 0))
    else:
        filtered.sort(key=lambda r: abs(float(r.get('pct') or 0)), reverse=True)
    return filtered[:limit]


def compute_eod_outcome_summary(review_date: Optional[str] = None) -> dict:
    """Compute EOD W/L/N/P resolution summary for daily review."""
    date = review_date or _today()
    pred = _query_prediction_outcomes(date)
    tg = _query_telegram_alert_outcomes(date)

    pred_counts = pred.get('counts') or {}
    all_rows = (pred.get('rows') or []) + (tg.get('rows') or [])

    wins = pred_counts.get('WIN', 0)
    losses = pred_counts.get('LOSS', 0)
    neutrals = pred_counts.get('NEUTRAL', 0)
    partials = pred_counts.get('PARTIAL', 0)
    expired = pred_counts.get('EXPIRED', 0)
    pending = pred_counts.get('PENDING', 0)

    for type_counts in (tg.get('by_type') or {}).values():
        wins += type_counts.get('WIN', 0)
        losses += type_counts.get('LOSS', 0)
        neutrals += type_counts.get('NEUTRAL', 0)
        partials += type_counts.get('PARTIAL', 0)
        pending += type_counts.get('PENDING', 0)

    resolved = wins + losses + neutrals + partials + expired
    data_available = resolved > 0 or not tg.get('price_missing')

    by_type = dict(tg.get('by_type') or {})
    for key in ('premarket', 'open_setup', 'intraday', 'emergency_macro', 'today/tomorrow decision'):
        by_type.setdefault(key, {'WIN': 0, 'LOSS': 0, 'NEUTRAL': 0, 'PARTIAL': 0, 'PENDING': 0})

    premarket = by_type.get('premarket') or {}
    emergency = by_type.get('emergency_macro') or {}

    best = _top_movers(all_rows, 'WIN', 3)
    worst = _top_movers(all_rows, 'LOSS', 3)

    return {
        'date': date,
        'resolved': resolved,
        'wins': wins,
        'losses': losses,
        'neutrals': neutrals,
        'partials': partials,
        'expired': expired,
        'pending': pending,
        'data_available': data_available,
        'best': best,
        'worst': worst,
        'by_alert_type': by_type,
        'premarket_confirmed': premarket.get('WIN', 0),
        'premarket_rejected': premarket.get('LOSS', 0) + premarket.get('NEUTRAL', 0),
        'emergency_useful': emergency.get('WIN', 0) + emergency.get('PARTIAL', 0),
        'emergency_duplicate_skipped': 0,
    }


def format_outcome_line(row: dict) -> str:
    ticker = row.get('ticker') or '?'
    pct = row.get('pct')
    verdict = row.get('verdict') or 'PENDING'
    if pct is None:
        return f'• {ticker} — {verdict}'
    try:
        return f'• {ticker} {float(pct):+.1f}% after alert — {verdict}'
    except (TypeError, ValueError):
        return f'• {ticker} — {verdict}'


def format_eod_telegram_message(summary: dict, *, pending_meta: Optional[dict] = None) -> str:
    """Format DAILY REVIEW Telegram message per Stage 46G spec."""
    pending = pending_meta or {}
    if not summary.get('data_available') and summary.get('resolved', 0) == 0:
        outcome_line = 'Outcome pending — price data unavailable.'
    else:
        outcome_line = (
            f"Resolved: {summary.get('resolved', 0)} · "
            f"W{summary.get('wins', 0)}/L{summary.get('losses', 0)}/"
            f"N{summary.get('neutrals', 0)}/P{summary.get('partials', 0)}"
        )

    best_lines = [format_outcome_line(r) for r in (summary.get('best') or [])]
    worst_lines = [format_outcome_line(r) for r in (summary.get('worst') or [])]

    by_type = summary.get('by_alert_type') or {}
    open_setup = by_type.get('open_setup') or {}
    intraday = by_type.get('intraday') or {}
    emergency = by_type.get('emergency_macro') or {}

    def _wln(d: dict) -> str:
        return f"W{d.get('WIN', 0)}/L{d.get('LOSS', 0)}/N{d.get('NEUTRAL', 0)}"

    msg = (
        f"<b>📘 DAILY REVIEW</b>\n\n"
        f"<b>EOD Resolution</b>\n"
        f"{outcome_line}\n"
        f"Pending Active: {pending.get('pending_active', 0)} · "
        f"Expired: {pending.get('expired', summary.get('expired', 0))}\n\n"
        f"<b>Best:</b>\n{chr(10).join(best_lines) if best_lines else '—'}\n\n"
        f"<b>Worst:</b>\n{chr(10).join(worst_lines) if worst_lines else '—'}\n\n"
        f"<b>Premarket:</b>\n"
        f"Confirmed: {summary.get('premarket_confirmed', 0)} · "
        f"Rejected: {summary.get('premarket_rejected', 0)}\n\n"
        f"<b>Open setups:</b>\n{_wln(open_setup)}\n\n"
        f"<b>Intraday:</b>\n{_wln(intraday)}\n\n"
        f"<b>Emergency macro:</b>\n"
        f"Useful: {summary.get('emergency_useful', 0)} · "
        f"Duplicate skipped: {summary.get('emergency_duplicate_skipped', 0)}\n\n"
        f"<b>Tomorrow:</b>\nFresh post-market intelligence generated"
    )
    return msg


def persist_eod_summary(summary: dict) -> None:
    path = get_data_path(f'eod_outcome_summary_{summary.get("date") or _today()}.json')
    path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
