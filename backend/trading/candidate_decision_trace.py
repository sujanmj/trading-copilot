"""
Candidate Decision Trace — AstraEdge 52P.

Deterministic, inspectable explanation of how a candidate reached its current
decision. Read-only with respect to outcomes. Reuses canonical 52O gates:
scanner freshness, macro shock, quality-tradecard filter, outcome learning.
Paper/research only — no AI/LLM and no broker execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
TRACE_VERSION = '52P'
TRACE_STAGES = (
    'candidate_source',
    'market_mode',
    'scanner_guard',
    'macro_guard',
    'data_quality',
    'evidence_scoring',
    'risk_adjustment',
    'ranking',
    'decision_gate',
    'quality_tradecard_gate',
    'outcome_learning_gate',
    'final_decision',
)

STATUS_PASS = 'pass'
STATUS_WARN = 'warn'
STATUS_FAIL = 'fail'
STATUS_BLOCKED = 'blocked'
STATUS_SKIPPED = 'skipped'
STATUS_INFO = 'informational'


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _normalize_symbol(value: object) -> str:
    return str(value or '').strip().upper()


def _stage(
    name: str,
    status: str,
    *,
    reason_codes: list[str] | None = None,
    reason: str = '',
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        'stage': name,
        'status': status,
        'reason_codes': list(reason_codes or []),
        'reason': str(reason or ''),
        'facts': dict(facts or {}),
    }


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scanner_stage(board: dict[str, Any]) -> dict[str, Any]:
    from backend.trading.market_freshness_guard import (
        FRESHNESS_CURRENT,
        FRESHNESS_MISSING,
        FRESHNESS_PREVIOUS_SESSION,
        FRESHNESS_STALE,
    )

    status = str(board.get('scanner_freshness_status') or '').upper()
    lifecycle = str(board.get('market_lifecycle') or '')
    live_ready = bool(board.get('live_scanner_ready'))
    scanner_stale = bool(board.get('scanner_stale'))
    facts = {
        'scanner_freshness_status': status or None,
        'live_scanner_ready': live_ready,
        'scanner_stale': scanner_stale,
        'market_lifecycle': lifecycle or None,
    }
    if status == FRESHNESS_CURRENT and live_ready:
        return _stage(
            'scanner_guard',
            STATUS_PASS,
            reason_codes=['LIVE_SCANNER_CURRENT'],
            reason='scanner current',
            facts=facts,
        )
    if lifecycle == 'MARKET_ACTIVE' and (scanner_stale or status in (FRESHNESS_STALE, FRESHNESS_MISSING, '')):
        code = 'SCANNER_MISSING' if status in (FRESHNESS_MISSING, '') else 'SCANNER_STALE'
        return _stage(
            'scanner_guard',
            STATUS_BLOCKED,
            reason_codes=['LIVE_SCANNER_REQUIRED', code],
            reason='live scanner required during active market session',
            facts=facts,
        )
    if status == FRESHNESS_PREVIOUS_SESSION:
        return _stage(
            'scanner_guard',
            STATUS_WARN,
            reason_codes=['NEXT_SESSION_ONLY'],
            reason='previous-session scanner — not live confirmation',
            facts=facts,
        )
    if status == FRESHNESS_STALE:
        return _stage(
            'scanner_guard',
            STATUS_WARN,
            reason_codes=['SCANNER_STALE'],
            reason='scanner stale',
            facts=facts,
        )
    if status == FRESHNESS_MISSING:
        return _stage(
            'scanner_guard',
            STATUS_FAIL,
            reason_codes=['SCANNER_MISSING'],
            reason='scanner missing',
            facts=facts,
        )
    if board.get('reference_only') or lifecycle in ('WEEKEND', 'HOLIDAY', 'AFTER_HOURS', 'PREMARKET'):
        return _stage(
            'scanner_guard',
            STATUS_INFO,
            reason_codes=['NEXT_SESSION_ONLY'],
            reason='non-live session — scanner used as reference only',
            facts=facts,
        )
    return _stage(
        'scanner_guard',
        STATUS_INFO,
        reason_codes=['LIVE_SCANNER_CURRENT'] if live_ready else ['SCANNER_STALE'],
        reason=f'scanner status {status or "unknown"}',
        facts=facts,
    )


def _macro_stage(board: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    macro = board.get('macro_shock') if isinstance(board.get('macro_shock'), dict) else {}
    severity = str(
        board.get('macro_severity')
        or macro.get('severity')
        or (macro.get('latest_shock') or {}).get('severity')
        or ''
    ).upper()
    regime = str(board.get('macro_regime') or macro.get('regime') or '')
    active = bool(macro.get('active') or board.get('emergency_macro') or severity in ('HIGH', 'CRITICAL', 'WATCH'))
    penalty = _safe_float(board.get('macro_penalty') or row.get('macro_penalty'))
    facts = {
        'macro_active': active,
        'macro_severity': severity or None,
        'macro_regime': regime or None,
        'macro_penalty': penalty,
        'gap_down_risk': bool(board.get('gap_down_risk') or macro.get('gap_down_risk')),
        'candidate_score': _safe_int(row.get('score')),
    }
    if severity in ('HIGH', 'CRITICAL') or board.get('emergency_macro') or board.get('macro_crash'):
        return _stage(
            'macro_guard',
            STATUS_BLOCKED if severity == 'CRITICAL' or board.get('macro_crash') else STATUS_WARN,
            reason_codes=['MACRO_RISK_DOWNGRADE'],
            reason=f'macro {severity or "risk"} — score cannot bypass guard',
            facts=facts,
        )
    if severity == 'WATCH' or penalty > 0:
        return _stage(
            'macro_guard',
            STATUS_WARN,
            reason_codes=['MACRO_RISK_DOWNGRADE'],
            reason='risk-off tone / macro penalty applied',
            facts=facts,
        )
    if macro and not active and not severity:
        return _stage(
            'macro_guard',
            STATUS_PASS,
            reason_codes=['MACRO_GUARD_PASS'],
            reason='macro guard clear',
            facts=facts,
        )
    if not macro and board.get('macro_penalty') in (None, 0, 0.0) and not board.get('emergency_macro'):
        # Missing summary treated as clear when board already applied guard without flags.
        return _stage(
            'macro_guard',
            STATUS_PASS,
            reason_codes=['MACRO_GUARD_PASS'],
            reason='macro guard clear',
            facts=facts,
        )
    if not macro:
        return _stage(
            'macro_guard',
            STATUS_WARN,
            reason_codes=['MACRO_DATA_MISSING'],
            reason='macro evidence missing — follow existing safe path',
            facts=facts,
        )
    return _stage(
        'macro_guard',
        STATUS_PASS,
        reason_codes=['MACRO_GUARD_PASS'],
        reason='macro guard clear',
        facts=facts,
    )


def _source_stage(row: dict[str, Any]) -> dict[str, Any]:
    codes: list[str] = []
    parts: list[str] = []
    if isinstance(row.get('scanner_row'), dict) and row.get('scanner_row'):
        codes.append('LIVE_SCANNER_CURRENT')
        parts.append('scanner candidate')
    if row.get('gainer_promoted') or row.get('promoted_from_gainers'):
        codes.append('TOP_GAINER_CONFIRM')
        parts.append('gainer-promoted')
    if row.get('previous_mover') or row.get('previous_session_mover'):
        codes.append('PREVIOUS_MOVER')
        parts.append('previous mover')
    if row.get('has_catalyst'):
        codes.append('CATALYST_CONFIRM')
        parts.append('catalyst-linked')
    if not codes:
        codes.append('RESEARCH_ONLY')
        parts.append('research/reference candidate')
    return _stage(
        'candidate_source',
        STATUS_PASS if 'LIVE_SCANNER_CURRENT' in codes or 'TOP_GAINER_CONFIRM' in codes else STATUS_INFO,
        reason_codes=codes,
        reason=', '.join(parts),
        facts={
            'has_scanner_row': bool(row.get('scanner_row')),
            'gainer_promoted': bool(row.get('gainer_promoted') or row.get('promoted_from_gainers')),
            'previous_mover': bool(row.get('previous_mover') or row.get('previous_session_mover')),
            'has_catalyst': bool(row.get('has_catalyst')),
        },
    )


def _market_mode_stage(board: dict[str, Any]) -> dict[str, Any]:
    lifecycle = str(board.get('market_lifecycle') or board.get('phase') or 'UNKNOWN')
    reference_only = bool(board.get('reference_only'))
    codes = []
    status = STATUS_INFO
    reason = f'market mode {lifecycle}'
    if reference_only:
        codes.append('RESEARCH_ONLY')
        reason = f'{lifecycle} — reference/research only'
    if lifecycle in ('WEEKEND', 'HOLIDAY', 'AFTER_HOURS'):
        codes.append('NEXT_SESSION_ONLY')
    if lifecycle == 'MARKET_ACTIVE' and not reference_only:
        status = STATUS_PASS
        codes = codes or ['LIVE_SCANNER_REQUIRED']
        reason = 'active market session'
    return _stage(
        'market_mode',
        status,
        reason_codes=codes or ['RESEARCH_ONLY'],
        reason=reason,
        facts={
            'market_lifecycle': lifecycle,
            'reference_only': reference_only,
            'session_stale': bool(board.get('session_stale')),
            'phase': board.get('phase'),
            'session_date': board.get('session_date') or board.get('source_session_date'),
        },
    )


def _data_quality_stage(board: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    if not row.get('scanner_row') and not row.get('price') and not row.get('ltp'):
        missing.append('price')
    if row.get('volume_ratio') in (None, 0, 0.0) and not (row.get('scanner_row') or {}).get('volume_ratio'):
        missing.append('volume')
    if board.get('session_stale') or board.get('data_status') == 'stale':
        return _stage(
            'data_quality',
            STATUS_WARN,
            reason_codes=['DATA_QUALITY_INCOMPLETE'],
            reason='stale or incomplete session data',
            facts={'missing': missing, 'data_status': board.get('data_status')},
        )
    if missing:
        return _stage(
            'data_quality',
            STATUS_WARN,
            reason_codes=['DATA_QUALITY_INCOMPLETE'],
            reason='incomplete candidate inputs: ' + ', '.join(missing),
            facts={'missing': missing},
        )
    return _stage(
        'data_quality',
        STATUS_PASS,
        reason_codes=['DATA_QUALITY_OK'],
        reason='candidate inputs present',
        facts={'missing': []},
    )


def _evidence_stage(row: dict[str, Any], board: dict[str, Any]) -> dict[str, Any]:
    codes: list[str] = []
    parts: list[str] = []
    vol = _safe_float(row.get('volume_ratio'))
    breadth = row.get('sector_breadth') if isinstance(row.get('sector_breadth'), dict) else {}
    boost = _safe_int(breadth.get('boost'))
    if row.get('has_catalyst'):
        codes.append('CATALYST_CONFIRM')
        parts.append('catalyst')
    if vol >= 1.2:
        codes.append('VOLUME_CONFIRM')
        parts.append('volume')
    if boost > 0:
        codes.append('BREADTH_CONFIRM')
        parts.append('breadth')
    if row.get('above_open'):
        codes.append('PRICE_STRENGTH')
        parts.append('above open')
    if row.get('above_vwap'):
        codes.append('PRICE_STRENGTH')
        parts.append('above vwap')
    penalty = _safe_float(board.get('macro_penalty'))
    score = _safe_int(row.get('score'))
    facts = {
        'score': score,
        'macro_penalty': penalty,
        'volume_ratio': vol,
        'change_percent': _safe_float(row.get('change_percent')),
        'has_catalyst': bool(row.get('has_catalyst')),
        'breadth_boost': boost,
        'why': list(row.get('why') or [])[:6],
        # Observed final score and known board penalty — not a re-score.
        'score_after_penalties': score,
        'score_before_penalties': score + int(round(penalty)) if penalty else score,
    }
    if not codes:
        return _stage(
            'evidence_scoring',
            STATUS_WARN,
            reason_codes=['DATA_QUALITY_INCOMPLETE'],
            reason='limited deterministic evidence',
            facts=facts,
        )
    return _stage(
        'evidence_scoring',
        STATUS_PASS,
        reason_codes=list(dict.fromkeys(codes)),
        reason=', '.join(parts) + ' confirmation',
        facts=facts,
    )


def _risk_stage(row: dict[str, Any]) -> dict[str, Any]:
    state = str(row.get('state') or '').upper()
    codes: list[str] = []
    parts: list[str] = []
    status = STATUS_PASS
    if row.get('extended') or state == 'CHASE_RISK':
        codes.append('EXTENDED_MOVE')
        parts.append('extended move')
        status = STATUS_WARN
    if state == 'CHASE_RISK' or row.get('pullback_only'):
        codes.append('CHASE_RISK')
        parts.append('pullback-only / chase risk')
        status = STATUS_WARN
    if row.get('momentum_only') or state == 'MOMENTUM_ONLY_WATCH':
        codes.append('MOMENTUM_ONLY')
        parts.append('momentum-only')
        status = STATUS_WARN
    if state in ('REJECTED', 'BLOCKED_STALE_DATA', 'NO_TRADE'):
        codes.append(state)
        parts.append(state.lower().replace('_', ' '))
        status = STATUS_BLOCKED
    if not codes:
        return _stage(
            'risk_adjustment',
            STATUS_PASS,
            reason_codes=['RISK_CLEAR'],
            reason='no chase/extended risk flags',
            facts={'state': state, 'extended': bool(row.get('extended')), 'pullback_only': bool(row.get('pullback_only'))},
        )
    return _stage(
        'risk_adjustment',
        status,
        reason_codes=codes,
        reason='; '.join(parts),
        facts={
            'state': state,
            'extended': bool(row.get('extended')),
            'pullback_only': bool(row.get('pullback_only')),
            'momentum_only': bool(row.get('momentum_only')),
        },
    )


def _ranking_stage(
    row: dict[str, Any],
    board: dict[str, Any],
    *,
    rank: int | None,
) -> dict[str, Any]:
    ranked = [
        r for r in (board.get('ranked_candidates') or [])
        if isinstance(r, dict) and _normalize_symbol(r.get('ticker'))
    ]
    sym = _normalize_symbol(row.get('ticker'))
    if rank is None:
        rank = next(
            (idx for idx, r in enumerate(ranked, start=1) if _normalize_symbol(r.get('ticker')) == sym),
            0,
        )
    total = len(ranked) or 1
    above = ranked[rank - 2] if rank and rank > 1 else None
    below = ranked[rank] if rank and rank < len(ranked) else None
    comparison = {
        'above': (
            {
                'ticker': _normalize_symbol(above.get('ticker')),
                'score': _safe_int(above.get('score')),
                'state': str(above.get('state') or ''),
            }
            if above else None
        ),
        'below': (
            {
                'ticker': _normalize_symbol(below.get('ticker')),
                'score': _safe_int(below.get('score')),
                'state': str(below.get('state') or ''),
            }
            if below else None
        ),
    }
    reason = f'ranked {rank} of {total}' if rank else 'unranked'
    if above:
        reason += (
            f' — below {_normalize_symbol(above.get("ticker"))} '
            f'(score {_safe_int(above.get("score"))})'
        )
    elif rank == 1 and total:
        reason += ' — top ranked candidate'
    return _stage(
        'ranking',
        STATUS_PASS if rank else STATUS_INFO,
        reason_codes=['RANK_ASSIGNED'] if rank else ['UNRANKED'],
        reason=reason,
        facts={'rank': rank, 'total': total, 'comparison': comparison, 'score': _safe_int(row.get('score'))},
    )


def _quality_and_learning_stages(
    row: dict[str, Any],
    board: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool, bool]:
    from backend.trading.candidate_outcome_learning import (
        MIN_QUALITY_SCORE,
        filter_quality_candidates,
        is_outcome_learning_eligible,
        outcome_learning_skip_reason,
    )

    quality_kept = filter_quality_candidates([row], board=board, for_outcome_learning=False)
    quality_pass = bool(quality_kept) and _safe_int(row.get('score')) >= MIN_QUALITY_SCORE
    skip = outcome_learning_skip_reason(row, board=board)
    learning_eligible = is_outcome_learning_eligible(row, board=board)
    # Canonical rule: outcome learning requires quality gate.
    if not quality_pass:
        learning_eligible = False
        skip = skip or 'below_threshold'

    q_codes = ['QUALITY_TRADECARD_PASS'] if quality_pass else ['QUALITY_TRADECARD_FAIL']
    q_stage = _stage(
        'quality_tradecard_gate',
        STATUS_PASS if quality_pass else STATUS_FAIL,
        reason_codes=q_codes,
        reason=(
            f'quality tradecard pass (score>={MIN_QUALITY_SCORE})'
            if quality_pass
            else f'quality tradecard fail (score<{MIN_QUALITY_SCORE} or ineligible state)'
        ),
        facts={
            'score': _safe_int(row.get('score')),
            'min_quality_score': MIN_QUALITY_SCORE,
            'state': str(row.get('state') or ''),
            'quality_pass': quality_pass,
        },
    )
    if learning_eligible:
        l_stage = _stage(
            'outcome_learning_gate',
            STATUS_PASS,
            reason_codes=['OUTCOME_LEARNING_ELIGIBLE'],
            reason='eligible for outcome learning',
            facts={'eligible': True, 'skip_reason': None},
        )
    else:
        l_stage = _stage(
            'outcome_learning_gate',
            STATUS_BLOCKED,
            reason_codes=['OUTCOME_LEARNING_BLOCKED'],
            reason=f'not eligible ({skip or "quality gate failed"})',
            facts={'eligible': False, 'skip_reason': skip, 'outcome': 'not_eligible'},
        )
    return q_stage, l_stage, quality_pass, learning_eligible


def build_candidate_decision_trace(
    row: dict[str, Any] | None,
    *,
    board: dict[str, Any] | None = None,
    rank: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic decision trace from an existing candidate row + board."""
    ist = _now_ist(now)
    data = dict(board or {})
    candidate = dict(row or {})
    sym = _normalize_symbol(candidate.get('ticker') or candidate.get('symbol'))
    if not sym:
        return {
            'trace_version': TRACE_VERSION,
            'ok': False,
            'symbol': '',
            'generated_at': ist.replace(microsecond=0).isoformat(),
            'unavailable': True,
            'final_decision': 'UNAVAILABLE',
            'final_reason': 'missing candidate symbol',
            'reason_codes': ['CANDIDATE_MISSING'],
            'stages': [
                _stage(
                    'final_decision',
                    STATUS_FAIL,
                    reason_codes=['CANDIDATE_MISSING'],
                    reason='missing candidate symbol',
                )
            ],
        }

    source = _source_stage(candidate)
    market = _market_mode_stage(data)
    scanner = _scanner_stage(data)
    macro = _macro_stage(data, candidate)
    data_q = _data_quality_stage(data, candidate)
    evidence = _evidence_stage(candidate, data)
    risk = _risk_stage(candidate)
    ranking = _ranking_stage(candidate, data, rank=rank)
    decision_state = str(candidate.get('state') or 'UNKNOWN').upper()
    decision_gate = _stage(
        'decision_gate',
        STATUS_PASS if decision_state not in ('REJECTED', 'BLOCKED_STALE_DATA', 'NO_TRADE') else STATUS_BLOCKED,
        reason_codes=[decision_state or 'UNKNOWN_STATE'],
        reason=f'current state {decision_state}',
        facts={'state': decision_state, 'why': list(candidate.get('why') or [])[:4]},
    )
    quality, learning, quality_pass, learning_eligible = _quality_and_learning_stages(candidate, data)

    blocked = []
    downgraded = []
    missing = []
    for stage in (scanner, macro, data_q, risk, quality, learning):
        if stage['status'] in (STATUS_BLOCKED, STATUS_FAIL):
            blocked.extend(stage.get('reason_codes') or [])
        if stage['status'] == STATUS_WARN:
            downgraded.extend(stage.get('reason_codes') or [])
        miss = (stage.get('facts') or {}).get('missing') or []
        if isinstance(miss, list):
            missing.extend(str(m) for m in miss)

    why = list(candidate.get('why') or [])
    final_reason = why[0] if why else f'state={decision_state}'
    if scanner['status'] == STATUS_BLOCKED:
        final_reason = scanner['reason']
    elif macro['status'] == STATUS_BLOCKED:
        final_reason = macro['reason']
    elif not quality_pass and decision_state in ('TRADECARD_CANDIDATE', 'PULLBACK_ONLY_PLAN', 'CHASE_RISK'):
        final_reason = f'{decision_state}: not a quality tradecard'

    final = _stage(
        'final_decision',
        STATUS_PASS if decision_state not in ('REJECTED', 'BLOCKED_STALE_DATA') else STATUS_BLOCKED,
        reason_codes=[decision_state] + (['OUTCOME_LEARNING_ELIGIBLE'] if learning_eligible else ['OUTCOME_LEARNING_BLOCKED']),
        reason=final_reason,
        facts={
            'final_decision': decision_state,
            'quality_tradecard': quality_pass,
            'outcome_learning_eligible': learning_eligible,
        },
    )
    stages = [
        source, market, scanner, macro, data_q, evidence, risk,
        ranking, decision_gate, quality, learning, final,
    ]
    all_codes: list[str] = []
    for stage in stages:
        for code in stage.get('reason_codes') or []:
            if code not in all_codes:
                all_codes.append(code)

    score_facts = (evidence.get('facts') or {})
    return {
        'trace_version': TRACE_VERSION,
        'ok': True,
        'unavailable': False,
        'symbol': sym,
        'generated_at': ist.replace(microsecond=0).isoformat(),
        'board_session_date': data.get('session_date') or data.get('source_session_date'),
        'market_lifecycle': data.get('market_lifecycle') or data.get('phase'),
        'candidate_source': source.get('reason'),
        'initial_candidate_state': decision_state,
        'scanner_status': data.get('scanner_freshness_status'),
        'scanner_guard': scanner,
        'macro_guard': macro,
        'data_quality': data_q,
        'score': _safe_int(candidate.get('score')),
        'score_before_penalties': score_facts.get('score_before_penalties'),
        'score_after_penalties': score_facts.get('score_after_penalties'),
        'score_components': {
            'has_catalyst': bool(candidate.get('has_catalyst')),
            'volume_ratio': _safe_float(candidate.get('volume_ratio')),
            'change_percent': _safe_float(candidate.get('change_percent')),
            'breadth_boost': _safe_int((candidate.get('sector_breadth') or {}).get('boost')),
            'macro_penalty': _safe_float(data.get('macro_penalty')),
            'above_open': bool(candidate.get('above_open')),
            'above_vwap': bool(candidate.get('above_vwap')),
            'extended': bool(candidate.get('extended')),
            'momentum_only': bool(candidate.get('momentum_only')),
        },
        'risk_filters': list(candidate.get('risk_filters') or candidate.get('why') or [])[:8],
        'rank': (ranking.get('facts') or {}).get('rank'),
        'comparison': (ranking.get('facts') or {}).get('comparison'),
        'quality_tradecard': quality_pass,
        'outcome_learning_eligible': learning_eligible,
        'final_decision': decision_state,
        'final_reason': final_reason,
        'blocked_reasons': blocked,
        'downgrade_reasons': downgraded,
        'missing_data_reasons': missing,
        'reason_codes': all_codes,
        'stages': stages,
        # Explicit: traces never invent outcomes.
        'outcome': 'not_eligible' if not learning_eligible else 'pending_or_unknown',
    }


def apply_decision_traces_to_board(board: dict[str, Any] | None) -> dict[str, Any]:
    """Attach decision_trace additively to each ranked candidate (idempotent)."""
    out = dict(board or {})
    ranked = list(out.get('ranked_candidates') or [])
    updated: list[dict[str, Any]] = []
    for idx, row in enumerate(ranked, start=1):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item['decision_trace'] = build_candidate_decision_trace(item, board=out, rank=idx)
        updated.append(item)
    out['ranked_candidates'] = updated
    out['decision_trace_version'] = TRACE_VERSION
    return out


def format_candidate_decision_trace_telegram(trace: dict[str, Any] | None) -> list[str]:
    """Compact Telegram lines for Candidate Decision Trace section."""
    if not isinstance(trace, dict) or trace.get('unavailable') or not trace.get('ok'):
        return [
            '',
            '<b>Candidate Decision Trace</b>',
            'Trace unavailable for this candidate.',
        ]
    stage_map = {
        str(s.get('stage')): s
        for s in (trace.get('stages') or [])
        if isinstance(s, dict)
    }
    display = [
        ('candidate_source', 'Source'),
        ('scanner_guard', 'Scanner guard'),
        ('macro_guard', 'Macro guard'),
        ('evidence_scoring', 'Evidence scoring'),
        ('risk_adjustment', 'Risk adjustment'),
        ('ranking', 'Ranking'),
        ('quality_tradecard_gate', 'Quality gate'),
        ('outcome_learning_gate', 'Outcome learning'),
    ]
    lines = ['', '<b>Candidate Decision Trace</b>']
    for i, (key, label) in enumerate(display, start=1):
        stage = stage_map.get(key) or {}
        status = str(stage.get('status') or 'informational').upper()
        if key == 'outcome_learning_gate':
            status = 'ELIGIBLE' if trace.get('outcome_learning_eligible') else 'NOT ELIGIBLE'
        elif key == 'quality_tradecard_gate':
            status = 'PASS' if trace.get('quality_tradecard') else 'FAIL'
        else:
            status = {
                'pass': 'PASS',
                'warn': 'WARN',
                'fail': 'FAIL',
                'blocked': 'BLOCKED',
                'skipped': 'SKIPPED',
                'informational': 'INFO',
            }.get(str(stage.get('status') or '').lower(), status)
        reason = str(stage.get('reason') or '').strip() or '—'
        lines.append(f'{i}. {label} — {status}: {reason}')
    final = str(trace.get('final_decision') or 'UNKNOWN').replace('_', '-')
    lines.append(f'Final: {final}')
    return lines


def extract_decision_trace(
    row: dict[str, Any] | None = None,
    *,
    board: dict[str, Any] | None = None,
    symbol: str | None = None,
) -> dict[str, Any] | None:
    """Read an existing trace or build one from row/board without raising."""
    try:
        if isinstance(row, dict) and isinstance(row.get('decision_trace'), dict):
            return row['decision_trace']
        sym = _normalize_symbol(symbol or (row or {}).get('ticker'))
        if board and sym:
            for cand in board.get('ranked_candidates') or []:
                if not isinstance(cand, dict):
                    continue
                if _normalize_symbol(cand.get('ticker')) != sym:
                    continue
                if isinstance(cand.get('decision_trace'), dict):
                    return cand['decision_trace']
                return build_candidate_decision_trace(cand, board=board)
        if isinstance(row, dict) and row:
            return build_candidate_decision_trace(row, board=board)
    except Exception:
        return None
    return None
