"""
Opening workflow session-date stale guard — Phase 4B.9.

Prevents previous-day scanner/radar/tradecards from presenting as current-session picks.
Paper/research only — read-only date checks, no LLM calls.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.9'

_SESSION_DATE_KEYS = ('session_date', 'trading_date', 'market_date')
_TIMESTAMP_KEYS = (
    'generated_at',
    'scan_time_local',
    'last_updated',
    'refreshed_at',
    'updated_at',
    'timestamp',
    'cache_refreshed_at',
)


def _now_ist(now: datetime | None = None) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=IST)
        return now.astimezone(IST)
    return datetime.now(IST)


def current_ist_session_date(now: datetime | None = None) -> str:
    """Current IST calendar date (YYYY-MM-DD)."""
    return _now_ist(now).date().isoformat()


def _parse_iso_datetime(value: object) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        if ' ' in raw and 'T' not in raw:
            raw = raw.replace(' ', 'T', 1)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (TypeError, ValueError):
        return None


def extract_payload_session_date(payload: dict[str, Any] | None) -> str:
    """Best-effort session date from a cache payload."""
    if not isinstance(payload, dict) or not payload:
        return ''
    for key in _SESSION_DATE_KEYS:
        val = str(payload.get(key) or '').strip()
        if len(val) >= 10:
            return val[:10]
    best: date | None = None
    for key in _TIMESTAMP_KEYS:
        dt = _parse_iso_datetime(payload.get(key))
        if dt is None:
            continue
        day = dt.date()
        best = day if best is None or day > best else best
    return best.isoformat() if best else ''


def resolve_market_state(now: datetime | None = None) -> str:
    try:
        from backend.telegram.india_mode_lock import resolve_telegram_market_phase

        return str(resolve_telegram_market_phase() or 'RESEARCH_MODE')
    except Exception:
        ist = _now_ist(now)
        mins = ist.hour * 60 + ist.minute
        if mins < 9 * 60:
            return 'INDIA_PREMARKET_MODE'
        if mins < 15 * 60 + 30:
            return 'INDIA_MARKET_HOURS'
        if mins < 16 * 60 + 30:
            return 'INDIA_POSTMARKET_MODE'
        return 'INDIA_AFTER_HOURS'


def _minutes_since_midnight(now: datetime) -> int:
    local = _now_ist(now)
    return local.hour * 60 + local.minute


def _source_freshness(
    *,
    scanner_payload: dict[str, Any] | None,
    catalyst_payload: dict[str, Any] | None,
    premarket_payload: dict[str, Any] | None,
) -> dict[str, str]:
    return {
        'scanner': extract_payload_session_date(scanner_payload) or 'unknown',
        'catalyst': extract_payload_session_date(catalyst_payload) or 'unknown',
        'premarket': extract_payload_session_date(premarket_payload) or 'unknown',
    }


def evaluate_session_stale(
    *,
    source_session_date: str,
    current_ist_date: str,
    now: datetime | None = None,
) -> bool:
    """True when source data is from a prior IST calendar date."""
    source = str(source_session_date or '').strip()[:10]
    current = str(current_ist_date or '').strip()[:10]
    if not source or not current:
        return False
    try:
        return date.fromisoformat(source) < date.fromisoformat(current)
    except ValueError:
        return source < current


def stale_guard_message(
    *,
    source_session_date: str,
    current_ist_date: str,
    generated_at: str = '',
) -> str:
    src = source_session_date or 'unknown date'
    cur = current_ist_date or current_ist_session_date()
    base = (
        f'Stale cache: last tradecards are from {src}. '
        f'Current IST date is {cur}. '
        'Use /refresh full or wait for 09:00/09:20 workflow.'
    )
    if generated_at:
        return f'{base}\nLast generated: {generated_at}'
    return base


def apply_session_guard_to_board(
    board: dict[str, Any],
    *,
    scanner_payload: dict[str, Any] | None = None,
    catalyst_payload: dict[str, Any] | None = None,
    premarket_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach session metadata and clear current candidates when stale."""
    ist_now = _now_ist(now)
    current_date = current_ist_session_date(ist_now)
    source_freshness = _source_freshness(
        scanner_payload=scanner_payload,
        catalyst_payload=catalyst_payload,
        premarket_payload=premarket_payload,
    )
    source_session_date = source_freshness.get('scanner') or ''
    if source_session_date == 'unknown':
        source_session_date = extract_payload_session_date(catalyst_payload) or current_date

    generated_at = str(board.get('generated_at') or ist_now.replace(microsecond=0).isoformat())
    generated_label = _parse_iso_datetime(generated_at)
    generated_display = (
        generated_label.strftime('%Y-%m-%d %H:%M IST')
        if generated_label
        else generated_at
    )

    market_state = resolve_market_state(ist_now)
    stale = evaluate_session_stale(
        source_session_date=source_session_date,
        current_ist_date=current_date,
        now=ist_now,
    )
    lifecycle = 'stale_previous_session' if stale else 'current_session'
    if stale:
        print(
            f'[OPENING_SESSION_STALE] source_date={source_session_date} '
            f'current_date={current_date} market_state={market_state}',
            flush=True,
        )

    out = dict(board)
    out['session_date'] = current_date
    out['source_session_date'] = source_session_date
    out['current_ist_date'] = current_date
    out['market_state'] = market_state
    out['lifecycle'] = lifecycle
    out['source_freshness'] = source_freshness
    out['session_stale'] = stale
    out['generated_at_display'] = generated_display

    if stale:
        ranked = list(out.get('ranked_candidates') or [])
        gscan = dict(out.get('gainer_scan') or {})
        out['reference_candidates'] = ranked
        out['reference_gainer_scan'] = dict(gscan)
        out['ranked_candidates'] = []
        out['gainer_scan'] = {'promoted': [], 'total': 0}
        out['stale_message'] = stale_guard_message(
            source_session_date=source_session_date,
            current_ist_date=current_date,
            generated_at=generated_display,
        )
        out['reference_only'] = True
    else:
        out['reference_candidates'] = []
        out['reference_only'] = False
        out['stale_message'] = ''

    return out


def apply_session_guard_to_gainer_scan(
    scan: dict[str, Any],
    *,
    scanner_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply the same stale guard to /gainers scan output."""
    ist_now = _now_ist(now)
    current_date = current_ist_session_date(ist_now)
    source_session_date = extract_payload_session_date(scanner_payload) or 'unknown'
    market_state = resolve_market_state(ist_now)
    stale = evaluate_session_stale(
        source_session_date=source_session_date,
        current_ist_date=current_date,
        now=ist_now,
    )
    out = dict(scan)
    out['session_date'] = current_date
    out['source_session_date'] = source_session_date
    out['current_ist_date'] = current_date
    out['market_state'] = market_state
    out['lifecycle'] = 'stale_previous_session' if stale else 'current_session'
    out['source_freshness'] = {'scanner': source_session_date}
    out['session_stale'] = stale
    if stale:
        print(
            f'[GAINERS_SESSION_STALE] source_date={source_session_date} current_date={current_date}',
            flush=True,
        )
        out['reference_buckets'] = dict(out.get('buckets') or {})
        out['buckets'] = {key: [] for key in (out.get('buckets') or {})}
        out['promoted_symbols'] = []
        out['by_symbol'] = {}
        out['stale_message'] = stale_guard_message(
            source_session_date=source_session_date,
            current_ist_date=current_date,
        )
        out['reference_only'] = True
    else:
        out['reference_only'] = False
        out['stale_message'] = ''
    return out


def format_stale_tradecards_telegram(board: dict[str, Any]) -> str:
    src = str(board.get('source_session_date') or 'unknown')
    cur = str(board.get('current_ist_date') or current_ist_session_date())
    generated = str(board.get('generated_at_display') or board.get('generated_at') or '—')
    lines = [
        '<b>TRADECARDS — STALE / PREVIOUS SESSION</b>',
        '<i>paper only — research, not execution</i>',
        '',
        f'Last generated: {generated}',
        f'Current IST date: {cur}',
        'No current-session tradecards available.',
        'Plan: wait for 09:20 live reaction or run /refresh full.',
        '',
        str(board.get('stale_message') or stale_guard_message(
            source_session_date=src,
            current_ist_date=cur,
            generated_at=generated,
        )),
    ]
    refs = board.get('reference_candidates') or []
    if refs:
        lines.extend(['', '<b>Previous-session reference only:</b>'])
        for row in refs[:5]:
            sym = str(row.get('ticker') or '?')
            why = ' + '.join(row.get('why') or [])[:120] or 'prior session board'
            lines.append(f'• <b>{sym}</b> — {why}')
    return '\n'.join(lines)


def format_stale_radar_telegram(board: dict[str, Any], *, scheduled_slot: str | None = None) -> str:
    ist_now = _now_ist()
    mins = _minutes_since_midnight(ist_now)
    src = str(board.get('source_session_date') or 'unknown')
    cur = str(board.get('current_ist_date') or current_ist_session_date())
    generated = str(board.get('generated_at_display') or board.get('generated_at') or '—')

    if mins < 9 * 60 and not scheduled_slot:
        title = '<b>Opening Rally Radar — no current-date board</b>'
        plan = 'No current-date radar yet. Scheduled Radar Armed runs at 09:00 IST.'
    else:
        title = '<b>Opening Rally Radar — STALE / PREVIOUS SESSION</b>'
        plan = 'Plan: wait for 09:20 live reaction or run /refresh full.'

    lines = [
        title,
        '<i>Paper/research only</i>',
        '',
        f'Last generated: {generated}',
        f'Current IST date: {cur}',
        plan,
        '',
        str(board.get('stale_message') or stale_guard_message(
            source_session_date=src,
            current_ist_date=cur,
            generated_at=generated,
        )),
    ]
    refs = board.get('reference_candidates') or []
    if refs:
        lines.extend(['', '<b>Previous-session reference only:</b>'])
        for row in refs[:5]:
            sym = str(row.get('ticker') or '?')
            lines.append(f'• <b>{sym}</b>')
    return '\n'.join(lines)


def format_stale_gainers_telegram(scan: dict[str, Any]) -> str:
    src = str(scan.get('source_session_date') or 'unknown')
    cur = str(scan.get('current_ist_date') or current_ist_session_date())
    lines = [
        '<b>ALL-CAP GAINERS — STALE / PREVIOUS SESSION</b>',
        '<i>Paper/research only</i>',
        '',
        f'Current IST date: {cur}',
        'No current-session gainers available from scanner source.',
        str(scan.get('stale_message') or stale_guard_message(
            source_session_date=src,
            current_ist_date=cur,
        )),
        '',
        'Plan: run /refresh full or wait for 09:00/09:20 opening workflow.',
    ]
    refs = scan.get('reference_buckets') or {}
    flat: list[tuple[str, dict]] = []
    for bucket_rows in refs.values():
        if isinstance(bucket_rows, list):
            flat.extend((str(r.get('ticker') or '?'), r) for r in bucket_rows if isinstance(r, dict))
    if flat:
        lines.extend(['', '<b>Previous-session reference only:</b>'])
        for sym, row in flat[:5]:
            chg = row.get('change_percent')
            lines.append(f'• <b>{sym}</b> — +{float(chg or 0):.1f}%')
    return '\n'.join(lines)


def format_stale_tradecard_notice(board: dict[str, Any]) -> str:
    src = str(board.get('source_session_date') or 'unknown')
    cur = str(board.get('current_ist_date') or current_ist_session_date())
    lines = [
        '<b>📋 TRADE CARD — NO CURRENT-SESSION BOARD</b>',
        f'No current-session tradecard available. Last board is stale from {src}.',
        f'Current IST date: {cur}',
        'Plan: wait for 09:20 live reaction or run /refresh full.',
        '',
        str(board.get('stale_message') or stale_guard_message(
            source_session_date=src,
            current_ist_date=cur,
        )),
    ]
    refs = board.get('reference_candidates') or []
    if refs:
        best = refs[0]
        sym = str(best.get('ticker') or '?')
        lines.extend([
            '',
            '<b>Previous-session reference only:</b>',
            f'• {sym} — not an active watch',
        ])
    lines.append('')
    lines.append('Paper only.')
    return '\n'.join(lines)
