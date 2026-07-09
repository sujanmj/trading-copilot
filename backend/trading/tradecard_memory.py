"""
Tradecard decision memory — Phase 4B.13.

Persistent JSONL snapshots of /tradecards and /tradecard decisions for future evidence lookup.
Paper/research only — no LLM calls.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.13'
DEFAULT_MEMORY_FILE = DATA_DIR / 'tradecard_memory.jsonl'


def memory_file_path() -> Path:
    override = os.environ.get('TRADECARD_MEMORY_FILE', '').strip()
    return Path(override) if override else DEFAULT_MEMORY_FILE


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _normalize_symbol(value: object) -> str:
    return str(value or '').strip().upper()


def _normalize_cap_bucket(row: dict[str, Any] | None) -> str:
    from backend.trading.all_cap_gainers import format_cap_bucket_metadata, resolve_cap_bucket_for_symbol

    sym = _normalize_symbol((row or {}).get('ticker'))
    meta = format_cap_bucket_metadata(row, symbol=sym)
    if meta.startswith('cap_bucket='):
        bucket = meta.split('=', 1)[1].strip()
        if bucket:
            return bucket
    if sym:
        return resolve_cap_bucket_for_symbol(sym, row) or 'unknown'
    return 'unknown'


def resolve_board_status(board: dict[str, Any] | None) -> str:
    data = board or {}
    if data.get('session_stale') or data.get('data_status') == 'stale':
        return 'stale_blocked'
    if data.get('reference_only') or data.get('data_status') == 'previous_session_reference':
        return 'previous_session_reference'
    if data.get('data_status') == 'after_hours_same_day':
        return 'after_hours_watch'
    return 'live_current'


def resolve_outcome_status(
    *,
    board_status: str,
    selected_best: bool = False,
    no_current_entry: bool = False,
    status: str = '',
) -> str:
    if board_status == 'stale_blocked':
        return 'stale'
    if board_status == 'previous_session_reference' or no_current_entry:
        return 'reference_only'
    status_upper = str(status or '').strip().upper()
    if status_upper in ('NO_ACTIVE_ENTRY', 'NO_TRADE', 'ENTRY_MISSED', 'WAIT_FOR_VOLUME', 'WAIT_FOR_PULLBACK'):
        return 'no_fill'
    return 'pending'


def _run_id(board: dict[str, Any] | None) -> str:
    data = board or {}
    session = str(data.get('session_date') or data.get('source_session_date') or '')
    generated = str(data.get('generated_at') or '')
    return f'{session}_{generated}'[:120] if session or generated else ''


def _risk_filters_from_row(row: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    state = str(row.get('state') or '').upper()
    if state == 'CHASE_RISK':
        risks.append('extended/chase')
    if row.get('pullback_only'):
        risks.append('pullback-only plan')
    if state == 'NEW_LISTING_MOMENTUM':
        risks.append('new listing — volume confirm required')
    if state == 'DEMERGER_MOMENTUM':
        risks.append('demerger entity — confirm breadth/volume')
    if row.get('gainer_promoted') and state == 'TOP_GAINER_CONFIRM':
        risks.append('top gainer — confirm VWAP/volume')
    return risks


def _matrix_lists(matrix: dict[str, Any] | None) -> tuple[list[str], list[str], list[str], list[str]]:
    data = matrix or {}
    direct = [str(x) for x in (data.get('direct_confirms') or []) if str(x).strip()]
    indirect = [str(x) for x in (data.get('indirect_confirms') or []) if str(x).strip()]
    risk = [str(x) for x in (data.get('risk_filters') or []) if str(x).strip()]
    missing = [str(x) for x in (data.get('missing_modules') or data.get('missing_data') or []) if str(x).strip()]
    return direct, indirect, risk, missing


def build_memory_record(
    *,
    command_source: str,
    board: dict[str, Any] | None,
    symbol: str,
    row: dict[str, Any] | None = None,
    rank: int = 0,
    selected_best: bool = False,
    evidence_matrix: dict[str, Any] | None = None,
    card: dict[str, Any] | None = None,
    raw_summary_text: str = '',
    no_current_entry: bool = False,
) -> dict[str, Any]:
    """Build one tradecard memory record."""
    ist_now = _now_ist()
    data = board or {}
    board_status = resolve_board_status(data)
    sym = _normalize_symbol(symbol)
    base_row = dict(row or {})
    status = str((card or {}).get('status') or base_row.get('state') or '')
    outcome = resolve_outcome_status(
        board_status=board_status,
        selected_best=selected_best,
        no_current_entry=no_current_entry,
        status=status,
    )
    direct, indirect, risk_matrix, missing = _matrix_lists(evidence_matrix)
    row_risks = _risk_filters_from_row(base_row)
    risk_filters = list(dict.fromkeys(row_risks + risk_matrix))
    reasons = list(base_row.get('why') or [])
    if not reasons and card:
        reason = str(card.get('reason') or '').strip()
        if reason:
            reasons = [reason]

    from backend.trading.chart_patterns import pattern_fields_for_memory

    pattern_fields = pattern_fields_for_memory(base_row)

    record = {
        'memory_id': uuid.uuid4().hex,
        'created_at': ist_now.replace(microsecond=0).isoformat(),
        'current_ist': ist_now.strftime('%Y-%m-%d %H:%M IST'),
        'session_date': str(data.get('session_date') or data.get('source_session_date') or ''),
        'command_source': str(command_source or '/tradecard'),
        'market_lifecycle': str(data.get('market_lifecycle') or ''),
        'board_status': board_status,
        'symbol': sym,
        'cap_bucket': _normalize_cap_bucket(base_row or card),
        'rank': int(rank or 0),
        'score': int(base_row.get('score') or (card or {}).get('score') or 0),
        'state': str(base_row.get('state') or status or ''),
        'selected_best': bool(selected_best),
        'reasons': reasons[:8],
        'direct_confirms': direct[:12],
        'indirect_confirms': indirect[:12],
        'risk_filters': risk_filters[:12],
        'missing_data': missing[:12],
        'evidence_matrix': evidence_matrix if evidence_matrix else None,
        'source_freshness': dict(data.get('source_freshness') or {}),
        'board_id': _run_id(data),
        'run_id': _run_id(data),
        'raw_summary_text': str(raw_summary_text or '')[:240],
        'outcome_status': outcome,
        'outcome_reason': '',
    }
    record.update(pattern_fields)
    return record


def append_tradecard_memory(record: dict[str, Any]) -> dict[str, Any]:
    """Append one memory record to JSONL store."""
    path = memory_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault('memory_id', uuid.uuid4().hex)
    payload.setdefault('created_at', _now_ist().replace(microsecond=0).isoformat())
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + '\n')
    return payload


def load_tradecard_memory(symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Load memory records, newest first."""
    path = memory_file_path()
    if not path.exists():
        return []
    sym = _normalize_symbol(symbol) if symbol else ''
    rows: list[dict[str, Any]] = []
    try:
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if sym and _normalize_symbol(row.get('symbol')) != sym:
                    continue
                rows.append(row)
    except OSError:
        return []
    rows.sort(
        key=lambda r: (
            str(r.get('created_at') or ''),
            -int(r.get('rank') or 0),
            str(r.get('memory_id') or ''),
        ),
        reverse=True,
    )
    return rows[: max(1, int(limit or 50))]


def latest_tradecard_memory(limit: int = 10) -> list[dict[str, Any]]:
    return load_tradecard_memory(symbol=None, limit=limit)


def memory_stats() -> dict[str, Any]:
    rows = load_tradecard_memory(limit=10000)
    pending = sum(1 for r in rows if r.get('outcome_status') == 'pending')
    reference_only = sum(1 for r in rows if r.get('outcome_status') == 'reference_only')
    stale = sum(1 for r in rows if r.get('outcome_status') == 'stale')
    stats = {
        'total': len(rows),
        'pending': pending,
        'reference_only': reference_only,
        'stale_skipped': stale,
    }
    try:
        from backend.trading.candidate_outcome_learning import learning_stats

        stats.update(learning_stats())
    except Exception:
        stats.update({
            'candidate_snapshots': 0,
            'candidate_outcomes': 0,
            'candidate_learning_records': 0,
            'ai_explanations_used_today': 0,
        })
    try:
        from backend.trading.longterm_snapshot_memory import longterm_memory_stats

        stats.update(longterm_memory_stats())
    except Exception:
        stats.update({
            'screener_snapshots': 0,
            'longterm_recommendation_snapshots': 0,
            'longterm_symbols_tracked': 0,
        })
    try:
        from backend.trading.weekly_conviction_engine import weekly_memory_stats

        stats.update(weekly_memory_stats())
    except Exception:
        stats.update({
            'weekly_signal_events': 0,
            'weekly_pick_runs': 0,
            'weekly_pick_records': 0,
            'weekly_candidate_evaluations': 0,
            'weekly_symbols_tracked': 0,
        })
    try:
        from backend.trading.investor_intelligence import investor_memory_stats

        stats.update(investor_memory_stats())
    except Exception:
        stats.update({
            'investor_records': 0,
            'investor_symbols_tracked': 0,
            'investor_good_quality_records': 0,
            'investor_missing_records': 0,
        })
    return stats


def summarize_symbol_memory(symbol: str) -> dict[str, Any]:
    sym = _normalize_symbol(symbol)
    rows = load_tradecard_memory(symbol=sym, limit=200)
    if not rows:
        return {'symbol': sym, 'count': 0}
    ranks = [int(r.get('rank') or 0) for r in rows if int(r.get('rank') or 0) > 0]
    best_rank = min(ranks) if ranks else 0
    latest = rows[0]
    patterns: list[str] = []
    for row in rows[:5]:
        for reason in row.get('reasons') or []:
            token = str(reason).strip().lower()
            if token and token not in patterns:
                patterns.append(token)
    chart_pattern = str(latest.get('chart_pattern') or '')
    pattern_status = str(latest.get('pattern_status') or '')
    return {
        'symbol': sym,
        'count': len(rows),
        'best_rank': best_rank,
        'last_score': int(latest.get('score') or 0),
        'cap_bucket': str(latest.get('cap_bucket') or 'unknown'),
        'last_reasons': list(latest.get('reasons') or [])[:5],
        'last_risk': list(latest.get('risk_filters') or [])[:3],
        'last_outcome': str(latest.get('outcome_status') or 'pending'),
        'common_patterns': patterns[:4],
        'chart_pattern': chart_pattern,
        'pattern_status': pattern_status,
        'breakout_level': latest.get('breakout_level'),
        'pattern_confidence': int(latest.get('pattern_confidence') or 0),
    }


def _should_store_board(board_status: str) -> bool:
    return board_status != 'stale_blocked'


def record_tradecards_memory(
    board: dict[str, Any],
    *,
    command_source: str = '/tradecards',
) -> list[dict[str, Any]]:
    """Store top ranked candidates from /tradecards."""
    board_status = resolve_board_status(board)
    if not _should_store_board(board_status):
        return []
    stored: list[dict[str, Any]] = []
    if board_status == 'previous_session_reference':
        candidates = list(board.get('reference_candidates') or [])[:10]
        best_sym = _normalize_symbol(
            board.get('reference_best_pick') or board.get('tradecards_best_pick') or ''
        )
        batch_created = _now_ist().replace(microsecond=0)
        for idx, row in enumerate(candidates, start=1):
            sym = _normalize_symbol(row.get('ticker'))
            if not sym:
                continue
            record = build_memory_record(
                command_source=command_source,
                board=board,
                symbol=sym,
                row=row,
                rank=idx,
                selected_best=(sym == best_sym and idx == 1) or (idx == 1 and not best_sym),
                no_current_entry=True,
                raw_summary_text=' + '.join(row.get('why') or [])[:200],
            )
            record['created_at'] = batch_created.isoformat()
            record['current_ist'] = batch_created.strftime('%Y-%m-%d %H:%M IST')
            stored.append(append_tradecard_memory(record))
        return stored

    candidates = [
        r for r in (board.get('ranked_candidates') or [])
        if str(r.get('state') or '').upper() != 'REJECTED'
    ][:10]
    batch_created = _now_ist().replace(microsecond=0)
    for idx, row in enumerate(candidates, start=1):
        sym = _normalize_symbol(row.get('ticker'))
        if not sym:
            continue
        record = build_memory_record(
            command_source=command_source,
            board=board,
            symbol=sym,
            row=row,
            rank=idx,
            selected_best=(idx == 1),
            raw_summary_text=' + '.join(row.get('why') or [])[:200],
        )
        record['created_at'] = batch_created.isoformat()
        record['current_ist'] = batch_created.strftime('%Y-%m-%d %H:%M IST')
        stored.append(append_tradecard_memory(record))
    return stored


def record_tradecard_memory(
    *,
    board: dict[str, Any] | None,
    sync: dict[str, Any] | None,
    symbol: str,
    row: dict[str, Any] | None = None,
    card: dict[str, Any] | None = None,
    evidence_matrix: dict[str, Any] | None = None,
    command_source: str = '/tradecard',
    no_current_entry: bool = False,
) -> dict[str, Any] | None:
    """Store single /tradecard snapshot."""
    data = board or (sync or {}).get('board') or {}
    board_status = resolve_board_status(data)
    if board_status == 'stale_blocked':
        return None
    sym = _normalize_symbol(symbol)
    if not sym:
        return None
    if no_current_entry and board_status == 'live_current':
        pass
    ref_best = _normalize_symbol(
        (sync or {}).get('reference_best') or (sync or {}).get('tradecards_best') or ''
    )
    if no_current_entry and board_status == 'previous_session_reference':
        if ref_best and sym != ref_best:
            return None
    selected_best = bool((sync or {}).get('selected')) or sym == ref_best or bool(
        (sync or {}).get('tradecards_best') == sym
    )
    rank = 1 if selected_best else int((row or {}).get('tradecards_rank') or 0)
    record = build_memory_record(
        command_source=command_source,
        board=data,
        symbol=sym,
        row=row or (sync or {}).get('board_row') or {},
        rank=rank or 1,
        selected_best=selected_best or rank == 1,
        evidence_matrix=evidence_matrix,
        card=card,
        no_current_entry=no_current_entry or board_status == 'previous_session_reference',
        raw_summary_text=str((card or {}).get('reason') or '')[:200],
    )
    return append_tradecard_memory(record)
