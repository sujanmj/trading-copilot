"""
Opening workflow session freshness — Phase 4B.10.

Guards previous-day / closed-market boards from presenting as current-session picks.
Paper/research only — read-only date checks, no LLM calls.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.10'

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

_DATA_STATUS_LABELS = {
    'current': 'current',
    'previous_session_reference': 'previous-session',
    'stale': 'stale',
    'after_hours_same_day': 'after-hours (same session)',
}


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
    ist_now = _now_ist(now)
    try:
        if now is not None:
            from datetime import timezone

            from backend.analytics.market_calendar_router import get_india_telegram_mode
            from backend.telegram.india_mode_lock import (
                _normalize_mode_token,
                _phase_from_token,
                is_weekend_holiday_research_telegram_mode,
            )

            india = get_india_telegram_mode(ist_now.astimezone(timezone.utc))
            if is_weekend_holiday_research_telegram_mode(india, ist_now.astimezone(timezone.utc)):
                return 'RESEARCH_MODE'
            label = _phase_from_token(_normalize_mode_token(india.get('market_mode')))
            if label:
                return label
            code = _phase_from_token(_normalize_mode_token(india.get('mode_code')))
            if code:
                return code

        from backend.telegram.india_mode_lock import resolve_telegram_market_phase

        return str(resolve_telegram_market_phase() or 'RESEARCH_MODE')
    except Exception:
        mins = ist_now.hour * 60 + ist_now.minute
        if mins < 9 * 60:
            return 'INDIA_PREMARKET_MODE'
        if mins < 15 * 60 + 30:
            return 'INDIA_MARKET_HOURS'
        if mins < 16 * 60 + 30:
            return 'INDIA_POSTMARKET_MODE'
        return 'INDIA_AFTER_HOURS'


def resolve_market_lifecycle(now: datetime | None = None) -> str:
    """Canonical lifecycle label aligned with /status (WEEKEND, MARKET_ACTIVE, …)."""
    try:
        from backend.lifecycle.canonical_lifecycle import resolve_base_lifecycle

        return str(resolve_base_lifecycle(_now_ist(now)) or 'AFTER_HOURS')
    except Exception:
        ist = _now_ist(now)
        if ist.weekday() >= 5:
            return 'WEEKEND'
        return resolve_market_state(now)


def is_india_market_day(value: date | datetime | str) -> bool:
    try:
        from backend.analytics.market_calendar_router import is_india_market_day as _is_day

        return bool(_is_day(value))
    except Exception:
        if isinstance(value, datetime):
            day = value.date()
        elif isinstance(value, date):
            day = value
        else:
            day = date.fromisoformat(str(value)[:10])
        return day.weekday() < 5


def last_india_trading_day_on_or_before(day: date) -> date:
    cursor = day
    for _ in range(21):
        if is_india_market_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return day


def expected_board_session_date(now: datetime | None = None) -> str:
    """Session date a board must match to count as current for this clock."""
    ist = _now_ist(now)
    today = ist.date()
    lifecycle = resolve_market_lifecycle(ist)

    if lifecycle == 'MARKET_ACTIVE' and is_india_market_day(today):
        return today.isoformat()
    if lifecycle in ('POST_MARKET', 'AFTER_HOURS') and is_india_market_day(today):
        return today.isoformat()
    if lifecycle == 'PRE_MARKET' and is_india_market_day(today):
        return last_india_trading_day_on_or_before(today - timedelta(days=1)).isoformat()
    return last_india_trading_day_on_or_before(today).isoformat()


def is_closed_market_reference_mode(now: datetime | None = None) -> bool:
    """True when no live session is active — weekend, holiday, or research/closed."""
    ist = _now_ist(now)
    lifecycle = resolve_market_lifecycle(ist)
    today = ist.date()

    if lifecycle in ('WEEKEND', 'HOLIDAY'):
        return True
    market_state = resolve_market_state(ist)
    if market_state == 'RESEARCH_MODE':
        return True
    if lifecycle in ('AFTER_HOURS', 'POST_MARKET', 'MARKET_ACTIVE'):
        return False
    if market_state == 'INDIA_MARKET_HOURS':
        return False
    if lifecycle == 'PRE_MARKET' and is_india_market_day(today):
        return False
    if market_state in ('INDIA_PREMARKET_MODE', 'INDIA_PREOPEN_MODE') and is_india_market_day(today):
        return False
    return lifecycle not in ('MARKET_ACTIVE', 'POST_MARKET', 'AFTER_HOURS', 'PRE_MARKET')


def evaluate_session_stale(
    *,
    source_session_date: str,
    current_ist_date: str,
    now: datetime | None = None,
) -> bool:
    """True when source data is too old for the current context (multi-day stale)."""
    return evaluate_data_status(source_session_date, now=now) == 'stale'


def evaluate_data_status(
    source_session_date: str,
    *,
    now: datetime | None = None,
) -> str:
    """
    Classify board/gainer data for display.

    Returns: current | previous_session_reference | stale | after_hours_same_day
    """
    ist = _now_ist(now)
    expected = expected_board_session_date(ist)
    lifecycle = resolve_market_lifecycle(ist)
    closed_ref = is_closed_market_reference_mode(ist)
    source = str(source_session_date or '').strip()[:10]

    if not source or source == 'unknown':
        return 'previous_session_reference' if closed_ref else 'current'

    try:
        src_day = date.fromisoformat(source)
        exp_day = date.fromisoformat(expected)
    except ValueError:
        if closed_ref:
            return 'previous_session_reference'
        return 'stale' if source < expected else 'current'

    if src_day == exp_day:
        if lifecycle == 'MARKET_ACTIVE':
            return 'current'
        if lifecycle in ('POST_MARKET', 'AFTER_HOURS'):
            return 'after_hours_same_day'
        if closed_ref:
            return 'previous_session_reference'
        return 'current'

    if src_day < exp_day:
        if closed_ref and src_day == last_india_trading_day_on_or_before(exp_day):
            return 'previous_session_reference'
        return 'stale'

    return 'current'


def compute_board_age_display(generated_at: str, now: datetime | None = None) -> str:
    gen = _parse_iso_datetime(generated_at)
    if gen is None:
        return 'unknown'
    delta = _now_ist(now) - gen
    total_mins = max(0, int(delta.total_seconds() // 60))
    hours, mins = divmod(total_mins, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f'{days}d {hours}h'
    if hours:
        return f'{hours}h {mins}m'
    return f'{mins}m'


def format_session_metadata_block(payload: dict[str, Any]) -> list[str]:
    """Shared IST / lifecycle / board session metadata for Telegram outputs."""
    ist_now = _now_ist()
    current_display = str(payload.get('current_ist_display') or ist_now.strftime('%Y-%m-%d %H:%M IST'))
    lifecycle = str(payload.get('market_lifecycle') or resolve_market_lifecycle(ist_now))
    board_date = str(payload.get('board_session_date') or payload.get('source_session_date') or '—')
    age = str(payload.get('board_age_display') or '—')
    status = str(payload.get('data_status') or 'unknown')
    status_label = _DATA_STATUS_LABELS.get(status, status.replace('_', ' '))
    return [
        f'Market state: {lifecycle}',
        f'Current IST: {current_display}',
        f'Board session date: {board_date}',
        f'Board age: {age}',
        f'Data status: {status_label}',
    ]


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


def _resolve_source_session_date(
    *,
    source_freshness: dict[str, str],
    catalyst_payload: dict[str, Any] | None,
    board: dict[str, Any] | None,
    ist_now: datetime,
) -> str:
    def _norm(value: str) -> str:
        token = str(value or '').strip()[:10]
        return token if token else 'unknown'

    source_session_date = _norm(source_freshness.get('scanner') or '')
    if source_session_date == 'unknown':
        source_session_date = _norm(extract_payload_session_date(catalyst_payload))
    if source_session_date == 'unknown' and board:
        source_session_date = _norm(extract_payload_session_date(board))
    if source_session_date == 'unknown' and is_closed_market_reference_mode(ist_now):
        source_session_date = expected_board_session_date(ist_now)
    elif source_session_date == 'unknown':
        source_session_date = current_ist_session_date(ist_now)
    return source_session_date


def _lifecycle_from_data_status(data_status: str) -> str:
    return {
        'stale': 'stale_previous_session',
        'previous_session_reference': 'previous_session_reference',
        'after_hours_same_day': 'after_hours_session',
        'current': 'current_session',
    }.get(data_status, 'current_session')


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


def reference_guard_message(
    *,
    source_session_date: str,
    market_lifecycle: str,
    generated_at: str = '',
) -> str:
    src = source_session_date or 'unknown date'
    base = (
        f'Board is from prior trading session ({src}). '
        f'Market is {market_lifecycle.replace("_", " ").lower()} — not current live candidates.'
    )
    if generated_at:
        return f'{base}\nLast board generated: {generated_at}'
    return base


def _attach_session_metadata(
    out: dict[str, Any],
    *,
    ist_now: datetime,
    source_session_date: str,
    source_freshness: dict[str, str],
    data_status: str,
    generated_display: str,
    generated_at: str,
) -> None:
    current_date = current_ist_session_date(ist_now)
    market_state = resolve_market_state(ist_now)
    market_lifecycle = resolve_market_lifecycle(ist_now)
    out['session_date'] = current_date
    out['source_session_date'] = source_session_date
    out['board_session_date'] = source_session_date
    out['current_ist_date'] = current_date
    out['current_ist_display'] = ist_now.strftime('%Y-%m-%d %H:%M IST')
    out['market_state'] = market_state
    out['market_lifecycle'] = market_lifecycle
    out['lifecycle'] = _lifecycle_from_data_status(data_status)
    out['data_status'] = data_status
    out['source_freshness'] = source_freshness
    out['session_stale'] = data_status == 'stale'
    out['reference_only'] = data_status in ('stale', 'previous_session_reference')
    out['generated_at_display'] = generated_display
    out['board_age_display'] = compute_board_age_display(generated_at, ist_now)


def _demote_to_reference(out: dict[str, Any]) -> None:
    ranked = list(out.get('ranked_candidates') or [])
    gscan = dict(out.get('gainer_scan') or {})
    out['reference_candidates'] = ranked
    out['reference_gainer_scan'] = dict(gscan)
    out['ranked_candidates'] = []
    out['gainer_scan'] = {'promoted': [], 'total': 0}


def _demote_gainer_scan_to_reference(out: dict[str, Any]) -> None:
    out['reference_buckets'] = dict(out.get('buckets') or {})
    out['buckets'] = {key: [] for key in (out.get('buckets') or {})}
    out['promoted_symbols'] = []
    out['by_symbol'] = {}


def apply_session_guard_to_board(
    board: dict[str, Any],
    *,
    scanner_payload: dict[str, Any] | None = None,
    catalyst_payload: dict[str, Any] | None = None,
    premarket_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach session metadata and clear current candidates when not live-current."""
    ist_now = _now_ist(now)
    source_freshness = _source_freshness(
        scanner_payload=scanner_payload,
        catalyst_payload=catalyst_payload,
        premarket_payload=premarket_payload,
    )
    source_session_date = _resolve_source_session_date(
        source_freshness=source_freshness,
        catalyst_payload=catalyst_payload,
        board=board,
        ist_now=ist_now,
    )

    generated_at = str(board.get('generated_at') or ist_now.replace(microsecond=0).isoformat())
    generated_label = _parse_iso_datetime(generated_at)
    generated_display = (
        generated_label.strftime('%Y-%m-%d %H:%M IST')
        if generated_label
        else generated_at
    )

    data_status = evaluate_data_status(source_session_date, now=ist_now)
    market_lifecycle = resolve_market_lifecycle(ist_now)
    current_date = current_ist_session_date(ist_now)

    if data_status == 'stale':
        print(
            f'[OPENING_SESSION_STALE] source_date={source_session_date} '
            f'current_date={current_date} market_lifecycle={market_lifecycle}',
            flush=True,
        )
    elif data_status == 'previous_session_reference':
        print(
            f'[OPENING_SESSION_REFERENCE] source_date={source_session_date} '
            f'market_lifecycle={market_lifecycle}',
            flush=True,
        )

    out = dict(board)
    _attach_session_metadata(
        out,
        ist_now=ist_now,
        source_session_date=source_session_date,
        source_freshness=source_freshness,
        data_status=data_status,
        generated_display=generated_display,
        generated_at=generated_at,
    )

    if data_status in ('stale', 'previous_session_reference'):
        _demote_to_reference(out)
        if data_status == 'stale':
            out['stale_message'] = stale_guard_message(
                source_session_date=source_session_date,
                current_ist_date=current_date,
                generated_at=generated_display,
            )
        else:
            out['stale_message'] = reference_guard_message(
                source_session_date=source_session_date,
                market_lifecycle=market_lifecycle,
                generated_at=generated_display,
            )
    else:
        out['reference_candidates'] = []
        out['reference_gainer_scan'] = {}
        out['stale_message'] = ''

    return out


def apply_session_guard_to_gainer_scan(
    scan: dict[str, Any],
    *,
    scanner_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply session guard to /gainers scan output."""
    ist_now = _now_ist(now)
    current_date = current_ist_session_date(ist_now)
    source_freshness = {'scanner': extract_payload_session_date(scanner_payload) or 'unknown'}
    source_session_date = _resolve_source_session_date(
        source_freshness=source_freshness,
        catalyst_payload=None,
        board=scan,
        ist_now=ist_now,
    )
    data_status = evaluate_data_status(source_session_date, now=ist_now)
    market_lifecycle = resolve_market_lifecycle(ist_now)

    generated_at = str(scan.get('generated_at') or ist_now.replace(microsecond=0).isoformat())
    generated_label = _parse_iso_datetime(generated_at)
    generated_display = (
        generated_label.strftime('%Y-%m-%d %H:%M IST')
        if generated_label
        else generated_at
    )

    out = dict(scan)
    _attach_session_metadata(
        out,
        ist_now=ist_now,
        source_session_date=source_session_date,
        source_freshness=source_freshness,
        data_status=data_status,
        generated_display=generated_display,
        generated_at=generated_at,
    )

    if data_status in ('stale', 'previous_session_reference'):
        if data_status == 'stale':
            print(
                f'[GAINERS_SESSION_STALE] source_date={source_session_date} current_date={current_date}',
                flush=True,
            )
            out['stale_message'] = stale_guard_message(
                source_session_date=source_session_date,
                current_ist_date=current_date,
            )
        else:
            print(
                f'[GAINERS_SESSION_REFERENCE] source_date={source_session_date} '
                f'market_lifecycle={market_lifecycle}',
                flush=True,
            )
            out['stale_message'] = reference_guard_message(
                source_session_date=source_session_date,
                market_lifecycle=market_lifecycle,
            )
        _demote_gainer_scan_to_reference(out)
    else:
        out['reference_buckets'] = {}
        out['stale_message'] = ''

    return out


def _append_reference_candidates(lines: list[str], refs: list[dict[str, Any]], *, limit: int = 5) -> None:
    if not refs:
        return
    lines.extend(['', '<b>Previous-session reference:</b>'])
    for idx, row in enumerate(refs[:limit], start=1):
        sym = str(row.get('ticker') or '?')
        why = ' + '.join(row.get('why') or [])[:120] or 'prior session board'
        lines.append(f'{idx}. <b>{sym}</b> — {why} <i>(not current)</i>')


def format_reference_tradecards_telegram(board: dict[str, Any]) -> str:
    generated = str(board.get('generated_at_display') or board.get('generated_at') or '—')
    lines = [
        '<b>TRADECARDS — PREVIOUS-SESSION REFERENCE</b>',
        '<i>paper only — research, not execution</i>',
        '',
        *format_session_metadata_block(board),
        '',
        f'Last board generated: {generated}',
        'No current-session tradecards available.',
        'Next live workflow: 09:00 Radar Armed, 09:20 Opening Rally Radar.',
    ]
    _append_reference_candidates(lines, list(board.get('reference_candidates') or []))
    return '\n'.join(lines)


def format_stale_tradecards_telegram(board: dict[str, Any]) -> str:
    generated = str(board.get('generated_at_display') or board.get('generated_at') or '—')
    lines = [
        '<b>TRADECARDS — STALE / PREVIOUS SESSION</b>',
        '<i>paper only — research, not execution</i>',
        '',
        *format_session_metadata_block(board),
        '',
        f'Last generated: {generated}',
        'No current-session tradecards available.',
        'Plan: wait for 09:20 live reaction or run /refresh full.',
        '',
        str(board.get('stale_message') or stale_guard_message(
            source_session_date=str(board.get('source_session_date') or 'unknown'),
            current_ist_date=str(board.get('current_ist_date') or current_ist_session_date()),
            generated_at=generated,
        )),
    ]
    _append_reference_candidates(lines, list(board.get('reference_candidates') or []))
    return '\n'.join(lines)


def format_reference_radar_telegram(board: dict[str, Any], *, scheduled_slot: str | None = None) -> str:
    ist_now = _now_ist()
    mins = _minutes_since_midnight(ist_now)
    generated = str(board.get('generated_at_display') or board.get('generated_at') or '—')

    if mins < 9 * 60 and not scheduled_slot and is_closed_market_reference_mode(ist_now):
        title = '<b>OPENING RALLY RADAR — PREVIOUS-SESSION REFERENCE</b>'
        plan = 'No current-date radar yet. Scheduled Radar Armed runs at 09:00 IST on next trading day.'
    else:
        title = '<b>OPENING RALLY RADAR — PREVIOUS-SESSION REFERENCE</b>'
        plan = 'Not current pre-armed board — prior session reference only.'

    lines = [
        title,
        '<i>Paper/research only</i>',
        '',
        *format_session_metadata_block(board),
        '',
        f'Last board generated: {generated}',
        plan,
        '',
        str(board.get('stale_message') or ''),
    ]
    refs = board.get('reference_candidates') or []
    if refs:
        lines.extend(['', '<b>Previous-session reference:</b>'])
        for row in refs[:5]:
            sym = str(row.get('ticker') or '?')
            lines.append(f'• <b>{sym}</b> <i>(not current)</i>')
    return '\n'.join(lines)


def format_stale_radar_telegram(board: dict[str, Any], *, scheduled_slot: str | None = None) -> str:
    ist_now = _now_ist()
    mins = _minutes_since_midnight(ist_now)
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
        *format_session_metadata_block(board),
        '',
        f'Last generated: {generated}',
        plan,
        '',
        str(board.get('stale_message') or stale_guard_message(
            source_session_date=str(board.get('source_session_date') or 'unknown'),
            current_ist_date=str(board.get('current_ist_date') or current_ist_session_date()),
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


def format_reference_gainers_telegram(scan: dict[str, Any]) -> str:
    src = str(scan.get('source_session_date') or 'unknown')
    lines = [
        '<b>ALL-CAP GAINERS — PREVIOUS-SESSION REFERENCE</b>',
        '<i>Paper/research only</i>',
        '',
        *format_session_metadata_block(scan),
        '',
        f'Last data session: {src}',
        'Not current live gainers.',
        'Next live workflow: 09:00 Radar Armed, 09:20 Opening Rally Radar.',
    ]
    refs = scan.get('reference_buckets') or {}
    flat: list[tuple[str, dict]] = []
    for bucket_rows in refs.values():
        if isinstance(bucket_rows, list):
            flat.extend((str(r.get('ticker') or '?'), r) for r in bucket_rows if isinstance(r, dict))
    if flat:
        lines.extend(['', '<b>Previous-session reference:</b>'])
        for sym, row in flat[:5]:
            chg = row.get('change_percent')
            lines.append(f'• <b>{sym}</b> — +{float(chg or 0):.1f}% <i>(not current)</i>')
    return '\n'.join(lines)


def format_stale_gainers_telegram(scan: dict[str, Any]) -> str:
    lines = [
        '<b>ALL-CAP GAINERS — STALE / PREVIOUS SESSION</b>',
        '<i>Paper/research only</i>',
        '',
        *format_session_metadata_block(scan),
        '',
        'No current-session gainers available from scanner source.',
        str(scan.get('stale_message') or stale_guard_message(
            source_session_date=str(scan.get('source_session_date') or 'unknown'),
            current_ist_date=str(scan.get('current_ist_date') or current_ist_session_date()),
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


def format_reference_tradecard_notice(board: dict[str, Any], *, ticker: str = '') -> str:
    sym = str(ticker or '').strip().upper()
    src = str(board.get('source_session_date') or 'unknown')
    lifecycle = str(board.get('market_lifecycle') or resolve_market_lifecycle())
    lines = [
        '<b>TRADE CARD — PREVIOUS-SESSION REFERENCE</b>',
    ]
    if sym:
        lines.append(f'<b>{sym}</b> · NO CURRENT ENTRY')
    else:
        lines.append('NO CURRENT ENTRY')
    lines.extend([
        f'Reason: market is closed/weekend ({lifecycle.replace("_", " ").lower()}); '
        f'board is previous-session reference ({src}).',
        'Plan: wait for next trading day 09:20 live confirmation.',
        '',
        *format_session_metadata_block(board),
    ])
    refs = board.get('reference_candidates') or []
    if sym and not any(str(r.get('ticker') or '').upper() == sym for r in refs):
        lines.extend(['', f'Prior board did not rank <b>{sym}</b> in top candidates.'])
    elif refs:
        ref_sym = sym or str(refs[0].get('ticker') or '?')
        lines.extend([
            '',
            '<b>Previous-session reference:</b>',
            f'• {ref_sym} — not an active watch <i>(not current)</i>',
        ])
    lines.append('')
    lines.append('Paper only.')
    return '\n'.join(lines)


def format_stale_tradecard_notice(board: dict[str, Any]) -> str:
    src = str(board.get('source_session_date') or 'unknown')
    lines = [
        '<b>📋 TRADE CARD — NO CURRENT-SESSION BOARD</b>',
        f'No current-session tradecard available. Last board is stale from {src}.',
        '',
        *format_session_metadata_block(board),
        '',
        'Plan: wait for 09:20 live reaction or run /refresh full.',
        '',
        str(board.get('stale_message') or stale_guard_message(
            source_session_date=src,
            current_ist_date=str(board.get('current_ist_date') or current_ist_session_date()),
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


def format_after_hours_tradecards_header(board: dict[str, Any]) -> list[str]:
    """Extra header lines for same-day after-hours tradecards board."""
    return [
        '<i>After-hours — same-session next-day watch, not live entry</i>',
        '',
        *format_session_metadata_block(board),
        '',
    ]
