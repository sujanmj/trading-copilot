"""Recover candidate outcomes and post-mortems for missed India sessions."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
LOOKBACK_DAYS = 14


def _data_path(name: str) -> Path:
    from backend.storage.data_paths import get_data_path

    return get_data_path(name)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_json(path: Path, value: dict) -> None:
    from backend.storage.json_io import atomic_write_json

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, value)


def _session_dates(today: date, lookback_days: int) -> list[str]:
    from backend.analytics.market_calendar_router import is_india_market_day

    days: list[str] = []
    cursor = today - timedelta(days=1)
    earliest = today - timedelta(days=max(1, int(lookback_days)))
    while cursor >= earliest:
        if is_india_market_day(cursor):
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _snapshot_dates() -> set[str]:
    from backend.trading.candidate_outcome_learning import _load_jsonl, _snapshots_path

    return {
        str(row.get('session_date') or '')[:10]
        for row in _load_jsonl(_snapshots_path())
        if isinstance(row, dict) and row.get('session_date')
    }


def _format_recovered_review(day: str, outcomes: list[dict[str, Any]], summary: dict) -> str:
    counts = Counter(str(row.get('outcome') or 'PENDING').upper() for row in outcomes)
    lines = [
        f"<b>📘 Recovered EOD review · {day}</b>",
        f"Morning candidates reviewed: {len(outcomes)}",
        f"Resolved: W{counts['WIN']} / L{counts['LOSS']} / N{counts['NEUTRAL']} · Pending: {counts['PENDING']}",
    ]
    if counts['PENDING']:
        reasons = Counter(
            str(row.get('pending_reason') or 'evidence_pending')
            for row in outcomes if str(row.get('outcome') or '').upper() == 'PENDING'
        )
        lines.append('Pending evidence: ' + ', '.join(f'{k} {v}' for k, v in reasons.most_common(4)))
    lines.append('EOD alert review: '
                 f"{summary.get('resolved', 0)} resolved · {summary.get('alerts_pending_score', 0)} pending")
    try:
        from backend.analytics.prediction_postmortem import format_eod_postmortem_digest

        digest = format_eod_postmortem_digest(day)
        if digest:
            lines.extend(['', digest])
    except Exception:
        pass
    return '\n'.join(lines)


def recover_missed_sessions(
    *,
    today: date | None = None,
    lookback_days: int = LOOKBACK_DAYS,
    send_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Resolve saved candidate snapshots from recent exchange sessions.

    Pending outcomes are intentionally retried on future calls; terminal
    outcomes are idempotent. Each recovered session gets one Telegram notice.
    """
    today = today or datetime.now(IST).date()
    candidates = _snapshot_dates()
    state_path = _data_path('missed_session_recovery.json')
    state = _read_json(state_path)
    notified = state.get('notified') if isinstance(state.get('notified'), dict) else {}
    result: dict[str, Any] = {'sessions': [], 'skipped': [], 'errors': []}

    for day in _session_dates(today, lookback_days):
        if day not in candidates:
            continue
        try:
            from backend.trading.candidate_outcome_learning import resolve_candidate_outcomes
            from backend.analytics.eod_outcome_scoring import compute_eod_outcome_summary, persist_eod_summary

            resolved = resolve_candidate_outcomes(session_date=day, run_ai=True)
            # The resolver currently returns aggregate counts; read its durable
            # date-filtered records for the review and idempotency decision.
            from backend.trading.candidate_outcome_learning import _load_jsonl, _outcomes_path

            rows = [row for row in _load_jsonl(_outcomes_path())
                    if str(row.get('session_date') or '')[:10] == day]
            summary = compute_eod_outcome_summary(review_date=day)
            persist_eod_summary(summary)
            item = {
                'date': day,
                'candidates': len(rows),
                'resolved': sum(str(r.get('outcome') or '').upper() in {'WIN', 'LOSS', 'NEUTRAL'} for r in rows),
                'pending': sum(str(r.get('outcome') or '').upper() == 'PENDING' for r in rows),
                'postmortem': resolved.get('prediction_postmortem') or {},
            }
            result['sessions'].append(item)

            if day not in notified and rows and send_fn:
                sent = send_fn(_format_recovered_review(day, rows, summary))
                if sent is not False:
                    notified[day] = datetime.now(IST).isoformat()
                    state['notified'] = notified
                    _write_json(state_path, state)
        except Exception as exc:
            result['errors'].append({'date': day, 'error': f'{type(exc).__name__}: {exc}'[:240]})

    state['last_run_at'] = datetime.now(IST).isoformat()
    state['last_run_date'] = today.isoformat()
    _write_json(state_path, state)
    return result


def run_scheduled_missed_session_recovery() -> dict[str, Any]:
    """Scheduler adapter; notify through the already-configured Telegram bot."""
    from backend.orchestration.telegram_listener import send_message

    result = recover_missed_sessions(send_fn=send_message)
    print(
        f"[MISSED_SESSION_RECOVERY] sessions={len(result['sessions'])} "
        f"errors={len(result['errors'])}",
        flush=True,
    )
    return result
