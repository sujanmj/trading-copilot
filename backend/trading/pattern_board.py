"""
Pattern board — Phase 4B.17A.

Scan /tradecards top candidates for chart pattern readiness (paper/research only).
"""

from __future__ import annotations

from typing import Any

STAGE = '4B.17A'
BULLISH_PATTERNS = frozenset({
    'ascending_triangle',
    'symmetrical_triangle',
    'breakout_retest',
    'breakout_confirmed',
})


def _normalize_symbol(value: object) -> str:
    import re
    return re.sub(r'[^A-Z0-9&-]', '', str(value or '').strip().upper())


def _cap_bucket_label(row: dict[str, Any]) -> str:
    try:
        from backend.trading.all_cap_gainers import format_cap_bucket_inline
        return format_cap_bucket_inline(row) or '—'
    except Exception:
        bucket = str(row.get('gainer_bucket') or row.get('cap_bucket') or '').strip()
        return bucket.replace('_', ' ').title() if bucket else '—'


def _pattern_score(best: dict[str, Any] | None) -> int:
    if not best:
        return 0
    score = int(best.get('confidence') or 0)
    status = str(best.get('status') or '')
    pattern = str(best.get('pattern') or '')
    if status == 'breakout_confirmed':
        score += 30
    elif status == 'retest_confirmed':
        score += 25
    elif status == 'near_breakout':
        score += 18
    elif status == 'forming':
        score += 8
    if pattern in BULLISH_PATTERNS:
        score += 6
    return score


def _is_bullish_active_pattern(best: dict[str, Any] | None) -> bool:
    if not best:
        return False
    pattern = str(best.get('pattern') or '')
    status = str(best.get('status') or '')
    if pattern in ('descending_triangle', 'failed_breakout'):
        return False
    return status in ('breakout_confirmed', 'near_breakout', 'retest_confirmed', 'forming')


def get_tradecard_pattern_universe(*, limit: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Return tradecards/radar/gainers candidate rows without scanning full market."""
    from backend.trading.opening_rally_radar import build_opening_rally_board

    board = build_opening_rally_board()
    candidates = [
        dict(r) for r in (board.get('ranked_candidates') or [])
        if str(r.get('state') or '').upper() != 'REJECTED'
    ][:limit]
    source = 'tradecards'
    if candidates:
        return candidates, board, source

    from backend.trading.all_cap_gainers import scan_all_cap_gainers

    scan = scan_all_cap_gainers()
    flat: list[dict[str, Any]] = []
    for rows in (scan.get('buckets') or {}).values():
        for row in list(rows or [])[:5]:
            flat.append(dict(row))
    if flat:
        return flat[:limit], {'gainer_scan': scan, **board}, 'gainers'

    fallback = [dict(r) for r in (board.get('ranked_candidates') or [])][:limit]
    return fallback, board, 'radar'


def _analyze_candidate(row: dict[str, Any], *, rank: int) -> dict[str, Any]:
    from backend.trading.chart_patterns import detect_chart_patterns, load_candles_for_symbol
    from backend.trading.intraday_candle_memory import MIN_DERIVED_CANDLES, get_candle_readiness

    sym = _normalize_symbol(row.get('ticker'))
    readiness = get_candle_readiness(sym) if sym else {}
    snapshot_count = int(readiness.get('snapshot_count') or 0)
    derived_count = int(readiness.get('derived_count') or 0)
    pattern_ready = bool(readiness.get('pattern_ready'))
    reason = str(readiness.get('reason') or '')
    if derived_count < MIN_DERIVED_CANDLES:
        reason = reason or f'need at least {MIN_DERIVED_CANDLES} derived candles'

    best_pattern: dict[str, Any] | None = None
    pattern_status = ''
    breakout_level = None
    support_level = None
    resistance_level = None
    risk_flags: list[str] = []
    reasons: list[str] = []
    pattern_score = 0

    if pattern_ready and sym:
        scanner = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else row
        candles = load_candles_for_symbol(sym)
        current_price = scanner.get('price') or scanner.get('close') or scanner.get('ltp')
        vwap = scanner.get('vwap')
        try:
            current_f = float(current_price) if current_price not in (None, '') else None
        except (TypeError, ValueError):
            current_f = None
        try:
            vwap_f = float(vwap) if vwap not in (None, '') else None
        except (TypeError, ValueError):
            vwap_f = None
        result = detect_chart_patterns(sym, candles, current_price=current_f, vwap=vwap_f)
        best_pattern = result.get('best_pattern')
        if best_pattern:
            pattern_status = str(best_pattern.get('status') or '')
            breakout_level = best_pattern.get('breakout_level')
            support_level = best_pattern.get('support_level')
            resistance_level = best_pattern.get('resistance_level')
            risk_flags = list(best_pattern.get('risk_flags') or [])
            reasons = list(best_pattern.get('reasons') or [])
            pattern_score = _pattern_score(best_pattern)

    return {
        'symbol': sym,
        'cap_bucket': _cap_bucket_label(row),
        'tradecard_rank': rank,
        'tradecard_score': int(row.get('score') or 0),
        'snapshots_count': snapshot_count,
        'derived_candles_count': derived_count,
        'pattern_ready': pattern_ready,
        'reason': reason,
        'best_pattern': best_pattern,
        'pattern_score': pattern_score,
        'pattern_status': pattern_status,
        'breakout_level': breakout_level,
        'support_level': support_level,
        'resistance_level': resistance_level,
        'risk_flags': risk_flags,
        'reasons': reasons,
        'candidate_row': row,
    }


def refresh_board_snapshots(candidates: list[dict[str, Any]], *, source: str = 'patterns_board') -> int:
    from backend.trading.intraday_candle_memory import (
        capture_candidate_snapshots,
        record_candidate_symbols,
        refresh_candidate_snapshots,
    )

    syms = [_normalize_symbol(r.get('ticker')) for r in candidates]
    syms = [s for s in syms if s]
    record_candidate_symbols(syms, source=source)
    count = capture_candidate_snapshots(candidates, source=source)
    count += refresh_candidate_snapshots(syms, source='heartbeat')
    return count


def build_pattern_board(*, limit: int = 10, refresh_snapshots: bool = True) -> dict[str, Any]:
    candidates, board, source = get_tradecard_pattern_universe(limit=limit)
    if refresh_snapshots and candidates:
        refresh_board_snapshots(candidates, source='patterns_board')

    entries = [
        _analyze_candidate(row, rank=idx)
        for idx, row in enumerate(candidates[:limit], start=1)
    ]
    return {
        'source': source,
        'board': board,
        'entries': entries,
        'scanned_count': len(entries),
    }


def select_best_pattern_candidate(pattern_board: dict[str, Any]) -> dict[str, Any]:
    entries = list(pattern_board.get('entries') or [])
    ready = [
        e for e in entries
        if e.get('pattern_ready') and e.get('best_pattern') and _is_bullish_active_pattern(e.get('best_pattern'))
    ]
    if ready:
        ready.sort(
            key=lambda e: (
                -int(e.get('pattern_score') or 0),
                int(e.get('tradecard_rank') or 99),
            ),
        )
        return {'pick': ready[0], 'valid': True, 'scanned_count': len(entries)}

    closest = sorted(
        entries,
        key=lambda e: (
            -int(e.get('derived_candles_count') or 0),
            int(e.get('tradecard_rank') or 99),
        ),
    )
    return {'pick': None, 'valid': False, 'scanned_count': len(entries), 'closest': closest[:5]}


def format_patterns_board(pattern_board: dict[str, Any]) -> str:
    from backend.trading.intraday_candle_memory import MIN_DERIVED_CANDLES
    from backend.trading.opening_session_freshness import format_session_metadata_block

    board = pattern_board.get('board') or {}
    lines = [
        '<b>PATTERNS — TRADECARD TOP 10</b>',
        '<i>paper/research only</i>',
        '',
    ]
    meta = format_session_metadata_block(board)
    if meta:
        lines.extend(meta)
        lines.append('')

    entries = pattern_board.get('entries') or []
    if not entries:
        lines.append('No tradecard candidates available for pattern scan.')
        lines.append('Run /radar or /tradecards during market.')
        return '\n'.join(lines)

    for entry in entries:
        sym = entry.get('symbol') or '?'
        cap = entry.get('cap_bucket') or '—'
        rank = int(entry.get('tradecard_rank') or 0)
        score = int(entry.get('tradecard_score') or 0)
        snaps = int(entry.get('snapshots_count') or 0)
        candles = int(entry.get('derived_candles_count') or 0)
        ready = bool(entry.get('pattern_ready'))
        status_label = 'READY' if ready else 'NOT READY'
        lines.append(f'{rank}. <b>{sym}</b> — {cap} — {status_label}')
        lines.append(f'   Tradecard rank: {rank} | Score: {score}')
        lines.append(f'   Candles: {candles} | Snapshots: {snaps}')

        best = entry.get('best_pattern')
        if ready and best:
            label = str(best.get('label') or 'Pattern')
            pstatus = str(best.get('pattern_status') or best.get('status') or 'forming').replace('_', ' ')
            lines.append(f'   Pattern: {label} {pstatus}')
            if entry.get('breakout_level') is not None:
                lines.append(f'   Breakout: {entry.get("breakout_level")}')
            risks = entry.get('risk_flags') or []
            if risks:
                lines.append(f'   Risk: {risks[0]}')
        else:
            reason = entry.get('reason') or f'need at least {MIN_DERIVED_CANDLES} derived candles'
            if candles < MIN_DERIVED_CANDLES:
                lines.append(f'   Candles: {candles}/{MIN_DERIVED_CANDLES}')
            lines.append(f'   Reason: {reason}')
        lines.append('')

    return '\n'.join(lines).rstrip()


def format_single_pattern_pick(pattern_pick: dict[str, Any]) -> str:
    from backend.trading.intraday_candle_memory import MIN_DERIVED_CANDLES

    scanned = int(pattern_pick.get('scanned_count') or 0)
    if pattern_pick.get('valid') and pattern_pick.get('pick'):
        entry = pattern_pick['pick']
        sym = entry.get('symbol') or '?'
        cap = entry.get('cap_bucket') or '—'
        best = entry.get('best_pattern') or {}
        label = str(best.get('label') or 'Pattern')
        pstatus = str(entry.get('pattern_status') or 'forming').replace('_', ' ')
        candles = int(entry.get('derived_candles_count') or 0)
        lines = [
            '<b>PATTERN — BEST FROM TRADECARD TOP 10</b>',
            f'<b>{sym}</b> — {cap}',
            f'Pattern: {label}',
            f'Candles: {candles}',
        ]
        if entry.get('breakout_level') is not None:
            lines.append(f'Breakout: {entry.get("breakout_level")}')
        lines.append(f'Status: {pstatus}')
        risks = entry.get('risk_flags') or []
        if risks:
            lines.append(f'Risk: {risks[0]}')
        lines.append('<i>Paper only.</i>')
        return '\n'.join(lines)

    lines = [
        '<b>PATTERN — NO VALID ACTIVE PATTERN</b>',
        f'Scanned: {scanned} tradecard candidates',
        'Closest:',
    ]
    for idx, entry in enumerate(pattern_pick.get('closest') or [], start=1):
        sym = entry.get('symbol') or '?'
        candles = int(entry.get('derived_candles_count') or 0)
        need = max(0, MIN_DERIVED_CANDLES - candles)
        lines.append(f'{idx}. {sym} — candles {candles}/{MIN_DERIVED_CANDLES}' + (f' — need {need} more' if need else ''))
    return '\n'.join(lines)
