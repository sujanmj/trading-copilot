"""
Opening workflow accounting — Phase 4B.18B.

Persists scheduled early/final opening steps to tradecard memory, journal, and
daily-review summary. Paper/research only — no LLM calls.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18B'
SUMMARY_DIR = DATA_DIR / 'opening_workflow'


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _summary_path(session_date: str) -> Path:
    return SUMMARY_DIR / f'{session_date}.json'


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _catalyst_tier(row: dict[str, Any]) -> int:
    if bool(row.get('has_catalyst')):
        return 3
    cat_state = str(row.get('catalyst_state') or '').upper()
    if cat_state in ('CATALYST_CONFIRMED', 'CONFIRMED_CATALYST'):
        return 3
    if row.get('themes'):
        return 2
    if cat_state in ('PRICE_VOLUME_ONLY', 'UNKNOWN_CATALYST', 'THEME_ONLY'):
        return 0
    if cat_state in ('THEME_CONTEXT',):
        return 2
    return 1


def _action_safety_tier(row: dict[str, Any]) -> int:
    state = str(row.get('state') or '').upper()
    if state == 'CHASE_RISK':
        return 0
    if state == 'MOMENTUM_ONLY_WATCH':
        return 1
    if state in (
        'TRADECARD_CANDIDATE',
        'VOLUME_IGNITION',
        'PRICE_IGNITION',
        'SECTOR_BREADTH_CONFIRM',
        'TOP_GAINER_CONFIRM',
    ):
        return 2
    return 1


def early_tradecard_sort_key(row: dict[str, Any], *, prior_rank: int = 999) -> tuple[Any, ...]:
    """Sort early tradecard candidates: score desc, catalyst tier, safety, radar rank."""
    state = str(row.get('state') or '').upper()
    chase_penalty = 1 if state == 'CHASE_RISK' else 0
    rank_bonus = -int(prior_rank) if prior_rank < 999 else 0
    return (
        int(row.get('score') or 0),
        -chase_penalty,
        _catalyst_tier(row),
        _action_safety_tier(row),
        rank_bonus,
    )


def sort_early_tradecard_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ranked early tradecard candidates with explainable tie-breaks."""
    ranked = [dict(r) for r in candidates if str(r.get('state') or '').upper() != 'REJECTED']
    for idx, row in enumerate(ranked, start=1):
        row.setdefault('_prior_radar_rank', idx)
    ranked.sort(
        key=lambda r: early_tradecard_sort_key(
            r,
            prior_rank=int(r.get('_prior_radar_rank') or r.get('tradecards_rank') or 999),
        ),
        reverse=True,
    )
    for row in ranked:
        row.pop('_prior_radar_rank', None)
    return ranked


def _load_summary(session_date: str) -> dict[str, Any]:
    path = _summary_path(session_date)
    if not path.is_file():
        return {'session_date': session_date}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'session_date': session_date}
    return payload if isinstance(payload, dict) else {'session_date': session_date}


def _save_summary(session_date: str, summary: dict[str, Any]) -> dict[str, Any]:
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(summary)
    payload['session_date'] = session_date
    payload['updated_at'] = _now_ist().replace(microsecond=0).isoformat()
    _summary_path(session_date).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return payload


def _confirmation_bucket(confirm_state: str) -> str:
    token = str(confirm_state or '').upper().replace(' ', '_')
    if token == 'CONFIRMED':
        return 'confirmed'
    if token in ('NO_CLEAN_ENTRY', 'REJECTED'):
        return 'rejected'
    if token in ('WAIT_FOR_PULLBACK',):
        return 'wait_pullback'
    if token in ('PULLBACK_ONLY_PLAN',):
        return 'pullback_only'
    if token in ('CHASE_RISK',):
        return 'chase_risk'
    return 'wait_pullback'


def record_scheduled_early_tradecards(
    board: dict[str, Any],
    *,
    best_sym: str = '',
    candidates: list[dict[str, Any]] | None = None,
    timestamp: str = '',
) -> dict[str, Any]:
    """Persist 09:25 early tradecards to memory and opening workflow summary."""
    if board.get('reference_only') or board.get('session_stale'):
        return {}
    session_date = str(board.get('session_date') or timestamp[:10] or _now_ist().date().isoformat())
    ranked = sort_early_tradecard_candidates(list(candidates or []))
    best = _normalize_ticker(best_sym)
    if not best and ranked:
        best = _normalize_ticker(ranked[0].get('ticker'))
    try:
        from backend.trading.tradecard_memory import record_tradecards_memory

        record_tradecards_memory(board, command_source='scheduled_early_tradecards')
    except Exception:
        pass
    summary = _load_summary(session_date)
    summary['early_tradecards_generated'] = int(summary.get('early_tradecards_generated') or 0) + 1
    summary['best_provisional_pick'] = best
    summary['early_candidates'] = [
        {
            'ticker': _normalize_ticker(row.get('ticker')),
            'score': int(row.get('score') or 0),
            'rank': idx,
            'state': str(row.get('state') or ''),
        }
        for idx, row in enumerate(ranked[:10], start=1)
        if _normalize_ticker(row.get('ticker'))
    ]
    if timestamp:
        summary['early_tradecards_at'] = timestamp
    print(
        f'[OPENING_WORKFLOW_ACCOUNTING] stage=0925 best={best or "-"} '
        f'candidates={len(ranked)} generated={summary["early_tradecards_generated"]}',
        flush=True,
    )
    return _save_summary(session_date, summary)


def _opening_row_price(row: dict[str, Any] | None) -> float | None:
    scanner = (row or {}).get('scanner_row') if isinstance((row or {}).get('scanner_row'), dict) else {}
    for source in (scanner, row or {}):
        for key in ('price', 'last_price', 'current_price', 'ltp'):
            try:
                val = float(source.get(key) or 0)
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                return val
    return None


def _opening_confirmed_card(row: dict[str, Any], *, now: datetime) -> dict[str, Any] | None:
    sym = _normalize_ticker(row.get('ticker'))
    price = _opening_row_price(row)
    if not sym or price is None:
        return None
    zone_low = round(price * 0.995, 2)
    zone_high = round(price * 1.005, 2)
    stop = round(price * 0.985, 2)
    return {
        'ok': True,
        'ticker': sym,
        'status': 'VALID_ENTRY',
        'session_date': now.astimezone(IST).date().isoformat(),
        'generated_at': now.replace(microsecond=0).isoformat(),
        'current_price': round(price, 2),
        'entry_zone': f'{zone_low}-{zone_high}',
        'stop_loss': stop,
        'target_1': round(price * 1.02, 2),
        'target_2': round(price * 1.04, 2),
        'risk_reward': 1.5,
        'confidence': 'MEDIUM' if int(row.get('score') or 0) >= 70 else 'LOW',
        'capital_plan': 'Paper only — scheduled opening confirmation; manual entry discipline.',
        'reason': ' + '.join(row.get('why') or []) or 'opening board confirmed at 09:31',
        'invalid_if': f'Price trades below {stop} or VWAP/volume fail.',
        'paper_only': True,
        'source_label': 'scheduled_final_opening_confirmation',
    }


def record_scheduled_final_confirmation(
    board: dict[str, Any],
    *,
    best_sym: str = '',
    best_row: dict[str, Any] | None = None,
    confirm_state: str = '',
    timestamp: str = '',
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist 09:31 final confirmation to memory, journal, and workflow summary."""
    if board.get('reference_only') or board.get('session_stale'):
        return {}
    ist_now = now or _now_ist()
    session_date = str(board.get('session_date') or timestamp[:10] or ist_now.date().isoformat())
    sym = _normalize_ticker(best_sym)
    row = dict(best_row or {})
    state = str(confirm_state or '').upper().replace(' ', '_')
    try:
        from backend.trading.tradecard_memory import record_tradecard_memory

        record_tradecard_memory(
            board=board,
            sync={'selected': sym, 'tradecards_best': sym, 'board_row': row},
            symbol=sym,
            row=row,
            command_source='scheduled_final_opening_confirmation',
            no_current_entry=state != 'CONFIRMED',
        )
    except Exception:
        pass
    journal_record = None
    if state == 'CONFIRMED' and row:
        card = _opening_confirmed_card(row, now=ist_now)
        if card:
            try:
                from backend.trading.tradecard_journal import persist_tradecard_generation

                journal_record = persist_tradecard_generation(
                    card,
                    source_label='scheduled_final_opening_confirmation',
                )
            except Exception:
                journal_record = None
    elif state == 'PULLBACK_ONLY_PLAN' and row:
        try:
            from backend.trading.opening_rally_radar import _persist_opening_best_tradecard

            journal_record = _persist_opening_best_tradecard(
                row=row,
                now=ist_now,
                state=state,
            )
        except Exception:
            journal_record = None
    summary = _load_summary(session_date)
    summary['final_confirmation_generated'] = int(summary.get('final_confirmation_generated') or 0) + 1
    summary['final_best_pick'] = sym
    summary['final_confirmation_state'] = state
    bucket = _confirmation_bucket(state)
    for key in ('confirmed', 'rejected', 'wait_pullback', 'pullback_only', 'chase_risk'):
        summary.setdefault(key, 0)
    summary[bucket] = int(summary.get(bucket) or 0) + 1
    if timestamp:
        summary['final_confirmation_at'] = timestamp
    print(
        f'[OPENING_WORKFLOW_ACCOUNTING] stage=0931 best={sym or "-"} state={state.lower()} '
        f'journal={"yes" if journal_record else "no"}',
        flush=True,
    )
    return _save_summary(session_date, summary)


def summarize_opening_workflow_accounting(review_date: str) -> dict[str, Any]:
    """Merge persisted opening workflow summary with alert-event capture."""
    summary = _load_summary(review_date)
    try:
        from backend.orchestration.alert_event_log import summarize_opening_workflow_for_date

        captured = summarize_opening_workflow_for_date(review_date)
    except Exception:
        captured = {}
    merged = {
        'session_date': review_date,
        'radar_armed': int(captured.get('radar_armed') or 0),
        'opening_radar': int(captured.get('opening_radar') or 0),
        'early_tradecards_generated': int(summary.get('early_tradecards_generated') or 0),
        'final_confirmation_generated': int(summary.get('final_confirmation_generated') or 0),
        'early_tradecard_best': str(
            summary.get('best_provisional_pick') or captured.get('early_tradecard_best') or ''
        ),
        'final_confirmation_best': str(
            summary.get('final_best_pick') or captured.get('final_confirmation_best') or ''
        ),
        'final_confirmation_state': str(summary.get('final_confirmation_state') or ''),
        'confirmed': int(summary.get('confirmed') or 0),
        'rejected': int(summary.get('rejected') or 0),
        'wait_pullback': int(summary.get('wait_pullback') or 0),
        'pullback_only': int(summary.get('pullback_only') or 0),
        'chase_risk': int(summary.get('chase_risk') or 0),
        'early_candidates': list(summary.get('early_candidates') or []),
        'learning_candidates': list(captured.get('learning_candidates') or []),
        'intraday_alert_count': 0,
    }
    try:
        from backend.orchestration.alert_event_log import count_individual_intraday_alerts

        merged['intraday_alert_count'] = count_individual_intraday_alerts(review_date)
    except Exception:
        pass
    return merged
