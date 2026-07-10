"""
Market freshness guard — Phase 4B.18I / AstraEdge 52G.

Tracks per-source freshness for opening workflow. Board wrapper age alone
must not mark data as current when scanner/gainers inputs are stale.
Paper/research only — no LLM calls.
"""

from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18I'

FRESHNESS_CURRENT = 'CURRENT'
FRESHNESS_PREOPEN_ONLY = 'PREOPEN_ONLY'
FRESHNESS_PREVIOUS_SESSION = 'PREVIOUS_SESSION'
FRESHNESS_STALE = 'STALE'
FRESHNESS_MISSING = 'MISSING'

TRADECARDS_WAITING_SCANNER = 'WAITING LIVE SCANNER'
TRADECARDS_AFTER_HOURS = 'NEXT-SESSION WATCH / reference only'
TRADECARDS_READY_NO_QUALITY = 'CURRENT · no quality candidate above 60'
TRADECARDS_READY = 'CURRENT'

LIVE_SCANNER_MAX_AGE_MINUTES = 10
LIVE_SCANNER_MIN_IST = time(9, 15)
OPENING_RADAR_IST = time(9, 20)
EARLY_TRADECARDS_IST = time(9, 25)
FINAL_CONFIRM_IST = time(9, 31)

SCANNER_FILE = DATA_DIR / 'scanner_data.json'
CATALYST_FILE = DATA_DIR / 'stock_catalyst_radar_latest.json'
NEWS_FILE = DATA_DIR / 'news_feed.json'
PREMARKET_FILE = DATA_DIR / 'premarket_conviction_report.json'


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            payload = json.loads(path.read_text(encoding='utf-8'))
            return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _parse_ts(value: object) -> datetime | None:
    from backend.trading.opening_session_freshness import _parse_iso_datetime

    return _parse_iso_datetime(value)


def _session_date(now: datetime | None = None) -> str:
    from backend.trading.opening_session_freshness import current_ist_session_date

    return current_ist_session_date(now)


def _age_minutes(ts: datetime | None, now: datetime | None = None) -> int | None:
    if ts is None:
        return None
    delta = _now_ist(now) - ts.astimezone(IST)
    return max(0, int(delta.total_seconds() // 60))


def _format_ist(ts: datetime | None) -> str:
    if ts is None:
        return '—'
    return ts.astimezone(IST).strftime('%H:%M IST')


def _source_record(
    *,
    source_date: str = '',
    last_updated: datetime | None = None,
    market_session_date: str = '',
    age_minutes: int | None = None,
    freshness_status: str = FRESHNESS_MISSING,
    detail: str = '',
) -> dict[str, Any]:
    return {
        'source_date': source_date or '—',
        'last_updated_ist': _format_ist(last_updated),
        'market_session_date': market_session_date or _session_date(),
        'age_minutes': age_minutes,
        'freshness_status': freshness_status,
        'detail': detail,
    }


def _evaluate_tradecards_freshness_status(
    scanner_record: dict[str, Any],
    *,
    board: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tradecards readiness for /refresh status — derived from scanner + lifecycle."""
    from backend.trading.opening_session_freshness import resolve_market_lifecycle

    ist = _now_ist(now)
    lifecycle = str(resolve_market_lifecycle(ist) or '')
    scanner_status = str(scanner_record.get('freshness_status') or FRESHNESS_MISSING)
    data = board or {}

    if lifecycle in ('AFTER_HOURS', 'POST_MARKET', 'WEEKEND'):
        return _source_record(
            freshness_status=TRADECARDS_AFTER_HOURS,
            market_session_date=_session_date(ist),
            detail='after-hours reference watch only',
        )

    if scanner_status in (FRESHNESS_STALE, FRESHNESS_MISSING):
        return _source_record(
            freshness_status=TRADECARDS_WAITING_SCANNER,
            market_session_date=_session_date(ist),
            detail=f'scanner {scanner_status.lower()}',
        )

    live_ready = scanner_status == FRESHNESS_CURRENT or bool(data.get('live_scanner_ready'))
    if not live_ready or data.get('scanner_stale') or data.get('quality_tradecard_blocked'):
        return _source_record(
            freshness_status=TRADECARDS_WAITING_SCANNER,
            market_session_date=_session_date(ist),
            detail='scanner not ready for quality tradecards',
        )

    if data.get('ranked_candidates'):
        try:
            from backend.trading.candidate_outcome_learning import filter_quality_candidates

            candidates = [
                r for r in (data.get('ranked_candidates') or [])
                if str(r.get('state') or '').upper() != 'REJECTED'
            ]
            if filter_quality_candidates(candidates):
                return _source_record(
                    freshness_status=TRADECARDS_READY,
                    last_updated=_parse_ts(data.get('generated_at')),
                    market_session_date=_session_date(ist),
                    detail='quality candidates available',
                )
        except Exception:
            pass

    return _source_record(
        freshness_status=TRADECARDS_READY_NO_QUALITY,
        market_session_date=_session_date(ist),
        detail='scanner current; no score >= 60 candidate',
    )


def _evaluate_scanner_freshness(
    scanner_payload: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    from backend.trading.opening_session_freshness import (
        extract_payload_session_date,
        resolve_market_lifecycle,
    )

    ist = _now_ist(now)
    today = _session_date(ist)
    lifecycle = str(resolve_market_lifecycle(ist) or '')
    payload = dict(scanner_payload or {})
    if not payload:
        payload = _load_json(SCANNER_FILE)

    if not payload:
        return _source_record(
            freshness_status=FRESHNESS_MISSING,
            detail='scanner file missing',
            market_session_date=today,
        )

    source_date = str(extract_payload_session_date(payload) or '')[:10]
    ts = (
        _parse_ts(payload.get('last_updated'))
        or _parse_ts(payload.get('scan_time_local'))
        or _parse_ts(payload.get('refreshed_at'))
        or _parse_ts(payload.get('updated_at'))
    )
    age = _age_minutes(ts, ist)

    if lifecycle in ('PRE_MARKET', 'INDIA_PREMARKET_MODE', 'INDIA_PREOPEN_MODE'):
        if source_date and source_date < today:
            return _source_record(
                source_date=source_date,
                last_updated=ts,
                age_minutes=age,
                freshness_status=FRESHNESS_PREOPEN_ONLY,
                detail='previous session — premarket context only',
                market_session_date=today,
            )
        return _source_record(
            source_date=source_date or today,
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_PREOPEN_ONLY,
            detail='premarket — waiting for market open',
            market_session_date=today,
        )

    if not source_date or source_date == 'unknown':
        return _source_record(
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_MISSING,
            detail='scanner session date unknown',
            market_session_date=today,
        )

    if source_date < today:
        return _source_record(
            source_date=source_date,
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_PREVIOUS_SESSION,
            detail='previous trading session',
            market_session_date=today,
        )

    if lifecycle != 'MARKET_ACTIVE':
        if source_date == today:
            return _source_record(
                source_date=source_date,
                last_updated=ts,
                age_minutes=age,
                freshness_status=FRESHNESS_PREOPEN_ONLY,
                market_session_date=today,
            )
        return _source_record(
            source_date=source_date,
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_STALE,
            market_session_date=today,
        )

    # MARKET_ACTIVE — require post-09:15 stamp when clock is past 09:15.
    if ist.time() >= LIVE_SCANNER_MIN_IST:
        if ts is None:
            return _source_record(
                source_date=source_date,
                freshness_status=FRESHNESS_MISSING,
                detail='no scanner timestamp',
                market_session_date=today,
            )
        if ts.astimezone(IST).date().isoformat() != today:
            return _source_record(
                source_date=source_date,
                last_updated=ts,
                age_minutes=age,
                freshness_status=FRESHNESS_STALE,
                detail='scanner timestamp not today',
                market_session_date=today,
            )
        if ts.astimezone(IST).time() < LIVE_SCANNER_MIN_IST:
            return _source_record(
                source_date=source_date,
                last_updated=ts,
                age_minutes=age,
                freshness_status=FRESHNESS_STALE,
                detail='scanner before 09:15 IST',
                market_session_date=today,
            )
        if age is not None and age > LIVE_SCANNER_MAX_AGE_MINUTES:
            return _source_record(
                source_date=source_date,
                last_updated=ts,
                age_minutes=age,
                freshness_status=FRESHNESS_STALE,
                detail=f'scanner age {age}m > {LIVE_SCANNER_MAX_AGE_MINUTES}m',
                market_session_date=today,
            )
        return _source_record(
            source_date=source_date,
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_CURRENT,
            market_session_date=today,
        )

    return _source_record(
        source_date=source_date,
        last_updated=ts,
        age_minutes=age,
        freshness_status=FRESHNESS_CURRENT if source_date == today else FRESHNESS_PREOPEN_ONLY,
        market_session_date=today,
    )


def _evaluate_json_source_freshness(
    payload: dict[str, Any] | None,
    *,
    path: Path,
    now: datetime | None = None,
    stale_after_minutes: int = 120,
) -> dict[str, Any]:
    from backend.trading.opening_session_freshness import extract_payload_session_date

    ist = _now_ist(now)
    today = _session_date(ist)
    data = dict(payload or {})
    if not data:
        data = _load_json(path)
    if not data:
        return _source_record(freshness_status=FRESHNESS_MISSING, market_session_date=today)

    source_date = str(extract_payload_session_date(data) or '')[:10]
    ts = (
        _parse_ts(data.get('generated_at'))
        or _parse_ts(data.get('last_updated'))
        or _parse_ts(data.get('refreshed_at'))
        or _parse_ts(data.get('updated_at'))
    )
    if ts is None and path.is_file():
        try:
            ts = datetime.fromtimestamp(path.stat().st_mtime, tz=IST)
        except OSError:
            ts = None
    age = _age_minutes(ts, ist)

    if not source_date or source_date == 'unknown':
        source_date = ts.astimezone(IST).date().isoformat() if ts else ''

    if not source_date:
        return _source_record(
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_MISSING,
            market_session_date=today,
        )
    if source_date < today:
        return _source_record(
            source_date=source_date,
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_PREVIOUS_SESSION,
            market_session_date=today,
        )
    if age is not None and age > stale_after_minutes:
        return _source_record(
            source_date=source_date,
            last_updated=ts,
            age_minutes=age,
            freshness_status=FRESHNESS_STALE,
            market_session_date=today,
        )
    return _source_record(
        source_date=source_date,
        last_updated=ts,
        age_minutes=age,
        freshness_status=FRESHNESS_CURRENT,
        market_session_date=today,
    )


def evaluate_macro_freshness(*, now: datetime | None = None) -> dict[str, Any]:
    ist = _now_ist(now)
    today = _session_date(ist)
    try:
        from backend.trading.macro_shock_sentinel import get_active_macro_shock

        active = get_active_macro_shock(now=ist)
    except Exception:
        active = None
    if not active:
        return _source_record(
            source_date=today,
            freshness_status=FRESHNESS_CURRENT,
            detail='no active macro shock',
            market_session_date=today,
        )
    ts = _parse_ts(active.get('updated_at') or active.get('detected_at'))
    session = str(active.get('session_date') or '')[:10]
    status = FRESHNESS_CURRENT if session == today else FRESHNESS_STALE
    return _source_record(
        source_date=session or today,
        last_updated=ts,
        age_minutes=_age_minutes(ts, ist),
        freshness_status=status,
        market_session_date=today,
    )


def evaluate_all_source_freshness(
    *,
    scanner_payload: dict[str, Any] | None = None,
    catalyst_payload: dict[str, Any] | None = None,
    news_payload: dict[str, Any] | None = None,
    board: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    scanner = _evaluate_scanner_freshness(scanner_payload, now=now)
    gainers = _evaluate_json_source_freshness(
        board.get('gainer_scan') if isinstance(board, dict) else None,
        path=SCANNER_FILE,
        now=now,
        stale_after_minutes=LIVE_SCANNER_MAX_AGE_MINUTES + 5,
    )
    if gainers.get('freshness_status') == FRESHNESS_MISSING:
        gainers = dict(scanner)
        gainers['detail'] = 'gainers derived from scanner'

    table = {
        'scanner': scanner,
        'gainers': gainers,
        'news': _evaluate_json_source_freshness(news_payload, path=NEWS_FILE, now=now, stale_after_minutes=180),
        'catalyst': _evaluate_json_source_freshness(
            catalyst_payload, path=CATALYST_FILE, now=now, stale_after_minutes=240,
        ),
        'macro': evaluate_macro_freshness(now=now),
        'radar_board': _source_record(
            source_date=str((board or {}).get('source_session_date') or '')[:10] or _session_date(now),
            last_updated=_parse_ts((board or {}).get('generated_at')),
            age_minutes=_age_minutes(_parse_ts((board or {}).get('generated_at')), now),
            freshness_status=(
                FRESHNESS_STALE
                if (board or {}).get('scanner_stale')
                else FRESHNESS_CURRENT
                if (board or {}).get('live_scanner_ready')
                else FRESHNESS_MISSING
            ),
            market_session_date=_session_date(now),
        ),
        'tradecards': _evaluate_tradecards_freshness_status(scanner, board=board, now=now),
    }
    return table


def is_live_scanner_ready(
    *,
    scanner_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> bool:
    rec = _evaluate_scanner_freshness(scanner_payload, now=now)
    return rec.get('freshness_status') == FRESHNESS_CURRENT


def is_scanner_ready_for_final_confirm(
    *,
    scanner_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    ist = _now_ist(now)
    rec = _evaluate_scanner_freshness(scanner_payload, now=now)
    status = str(rec.get('freshness_status') or '')
    if ist.time() < FINAL_CONFIRM_IST:
        return True, ''
    if status == FRESHNESS_CURRENT:
        return True, ''
    detail = str(rec.get('detail') or 'live scanner stale/missing')
    return False, detail


def composite_data_status(
    *,
    wrapper_status: str,
    freshness_table: dict[str, dict[str, Any]],
    now: datetime | None = None,
) -> str:
    """Board data_status — not current unless critical inputs are current."""
    from backend.trading.opening_session_freshness import resolve_market_lifecycle

    ist = _now_ist(now)
    lifecycle = str(resolve_market_lifecycle(ist) or '')
    scanner_status = str((freshness_table.get('scanner') or {}).get('freshness_status') or '')
    gainers_status = str((freshness_table.get('gainers') or {}).get('freshness_status') or '')

    if wrapper_status in ('stale', 'previous_session_reference'):
        return wrapper_status

    if lifecycle == 'MARKET_ACTIVE' and ist.time() >= OPENING_RADAR_IST:
        if scanner_status not in (FRESHNESS_CURRENT,):
            return 'stale'
        if gainers_status in (FRESHNESS_PREVIOUS_SESSION, FRESHNESS_STALE, FRESHNESS_MISSING):
            return 'stale'

    return wrapper_status or 'current'


def filter_stale_live_candidates(
    ranked: list[dict[str, Any]],
    *,
    live_scanner_ready: bool,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Drop previous-session-only movers when live scanner is not ready."""
    from backend.trading.opening_session_freshness import resolve_market_lifecycle

    ist = _now_ist(now)
    if live_scanner_ready or str(resolve_market_lifecycle(ist) or '') != 'MARKET_ACTIVE':
        return list(ranked or [])
    if ist.time() < OPENING_RADAR_IST:
        return list(ranked or [])

    kept: list[dict[str, Any]] = []
    for row in ranked or []:
        if not isinstance(row, dict):
            continue
        prev = bool(row.get('previous_mover') or row.get('previous_session_mover'))
        has_live = bool(row.get('scanner_row')) and not bool(row.get('scanner_stale'))
        if prev and not has_live:
            continue
        if str(row.get('state') or '').upper() == 'PREVIOUS_SESSION_MOVER':
            continue
        kept.append(row)
    return kept


def apply_market_freshness_to_board(
    board: dict[str, Any],
    *,
    scanner_payload: dict[str, Any] | None = None,
    catalyst_payload: dict[str, Any] | None = None,
    news_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach per-source freshness and enforce live scanner gates on board."""
    from backend.trading.opening_session_freshness import (
        _demote_to_reference,
        resolve_market_lifecycle,
        stale_guard_message,
    )

    ist = _now_ist(now)
    out = dict(board or {})
    scanner_data = scanner_payload if scanner_payload is not None else _load_json(SCANNER_FILE)
    table = evaluate_all_source_freshness(
        scanner_payload=scanner_data,
        catalyst_payload=catalyst_payload,
        news_payload=news_payload,
        board=out,
        now=ist,
    )
    live_ready = is_live_scanner_ready(scanner_payload=scanner_data, now=ist)
    wrapper_status = str(out.get('data_status') or 'current')
    composite = composite_data_status(
        wrapper_status=wrapper_status,
        freshness_table=table,
        now=ist,
    )

    out['market_freshness'] = table
    out['live_scanner_ready'] = live_ready
    out['scanner_stale'] = not live_ready and str(resolve_market_lifecycle(ist) or '') == 'MARKET_ACTIVE'
    out['scanner_freshness_status'] = str((table.get('scanner') or {}).get('freshness_status') or '')
    out['gainers_freshness_status'] = str((table.get('gainers') or {}).get('freshness_status') or '')

    if composite != wrapper_status:
        out['wrapper_data_status'] = wrapper_status
        out['data_status'] = composite
        out['session_stale'] = composite == 'stale'
        if composite == 'stale' and not out.get('reference_only'):
            print(
                f'[MARKET_FRESHNESS_GUARD] wrapper={wrapper_status} composite={composite} '
                f'scanner={out.get("scanner_freshness_status")}',
                flush=True,
            )

    if out.get('scanner_stale') and ist.time() >= OPENING_RADAR_IST:
        ranked = filter_stale_live_candidates(
            list(out.get('ranked_candidates') or []),
            live_scanner_ready=live_ready,
            now=ist,
        )
        out['ranked_candidates'] = ranked
        if composite == 'stale' and ranked and not out.get('reference_only'):
            out['stale_message'] = (
                'SCANNER STALE / WAIT — live scanner not ready. '
                'Previous-session movers excluded from active radar.'
            )
        elif composite == 'stale' and not ranked and not out.get('reference_only'):
            out['reference_only'] = True
            out['no_current_entry'] = True
            _demote_to_reference(out)
            out['stale_message'] = stale_guard_message(
                source_session_date=str(out.get('source_session_date') or ''),
                current_ist_date=_session_date(ist),
                generated_at=str(out.get('generated_at_display') or ''),
            )

    # Refresh tradecards/radar rows in table after board mutation.
    out['market_freshness'] = evaluate_all_source_freshness(
        scanner_payload=scanner_data,
        catalyst_payload=catalyst_payload,
        news_payload=news_payload,
        board=out,
        now=ist,
    )
    return out


def format_freshness_status_telegram(*, now: datetime | None = None) -> str:
    table = evaluate_all_source_freshness(now=now)
    lines = ['<b>/refresh status</b>', '', '<b>SOURCE FRESHNESS</b>']
    labels = {
        'scanner': 'scanner',
        'gainers': 'gainers',
        'news': 'news',
        'macro': 'macro',
        'radar_board': 'radar board',
        'tradecards': 'tradecards',
    }
    for key, label in labels.items():
        rec = table.get(key) or {}
        status = str(rec.get('freshness_status') or FRESHNESS_MISSING)
        updated = str(rec.get('last_updated_ist') or '—')
        age = rec.get('age_minutes')
        age_part = f' · age {age}m' if age is not None else ''
        if key == 'tradecards' or status in (
            TRADECARDS_WAITING_SCANNER,
            TRADECARDS_AFTER_HOURS,
            TRADECARDS_READY_NO_QUALITY,
        ) or '·' in status:
            lines.append(f'{label}: {status}')
        else:
            lines.append(f'{label}: {status} · updated {updated}{age_part}')
    try:
        from backend.collectors.news_provider_registry import evaluate_news_provider_freshness

        news_table = evaluate_news_provider_freshness()
        agg = news_table.get('news_all') or {}
        lines.extend([
            '',
            '<b>NEWS PROVIDERS</b>',
            f"news_all: {agg.get('freshness_status', FRESHNESS_MISSING)} · items {agg.get('items_found', 0)}",
        ])
        for pid in ('mint_rss', 'business_standard', 'nse_rss', 'bse_rss', 'rbi', 'sebi', 'pib'):
            rec = news_table.get(pid) or {}
            status = str(rec.get('freshness_status') or FRESHNESS_MISSING)
            items = rec.get('items_found', 0)
            err = rec.get('error_count', 0)
            err_part = f' · errors {err}' if err else ''
            lines.append(f'{pid}: {status} · items {items}{err_part}')
    except Exception:
        pass
    lines.append('<i>Paper/research only</i>')
    return '\n'.join(lines)


def format_data_freshness_block(board: dict[str, Any] | None) -> list[str]:
    data = board or {}
    table = data.get('market_freshness') if isinstance(data.get('market_freshness'), dict) else {}
    if not table:
        table = evaluate_all_source_freshness(board=data)
    scanner = str((table.get('scanner') or {}).get('freshness_status') or FRESHNESS_MISSING)
    gainers = str((table.get('gainers') or {}).get('freshness_status') or FRESHNESS_MISSING)
    news = str((table.get('news') or {}).get('freshness_status') or FRESHNESS_MISSING)
    return [
        'Data freshness:',
        f'scanner: {scanner}',
        f'gainers: {gainers}',
        f'news: {news}',
    ]


def format_scanner_stale_radar_telegram(
    board: dict[str, Any] | None = None,
    *,
    scheduled_slot: str = '0920',
) -> str:
    from backend.trading.opening_session_freshness import format_session_metadata_block

    data = dict(board or {})
    time_ist = str(data.get('time_ist') or '09:20')
    lines = [
        f'<b>Opening Rally Radar — {time_ist} IST</b>',
        '<i>SCANNER STALE / WAIT · paper/research only</i>',
        '',
        *format_session_metadata_block(data),
        *format_data_freshness_block(data),
        '',
        'Live scanner not ready for current-session ranking.',
        'Run /refresh scanner or wait for intraday batch after 09:15.',
        'Previous-session movers are context only — not active radar candidates.',
    ]
    return '\n'.join(lines)


def format_no_active_tradecard_telegram(board: dict[str, Any] | None = None) -> str:
    from backend.trading.opening_session_freshness import format_session_metadata_block

    data = dict(board or {})
    lines = [
        '<b>Early Tradecards — 09:25 IST</b>',
        '<i>paper/research only</i>',
        '',
        *format_session_metadata_block(data),
        *format_data_freshness_block(data),
        '',
        'NO ACTIVE TRADECARD — live scanner not ready',
        'Allowed: WAIT LIVE CONFIRM · WATCH ONLY · NO TRADE',
    ]
    return '\n'.join(lines)


def refresh_scanner_scopes() -> list[str]:
    return ['scanner', 'prices']


def refresh_market_scopes() -> list[str]:
    return ['scanner', 'prices', 'runtime']


def prepare_session_rollover_for_opening(*, now: datetime | None = None) -> dict[str, Any]:
    """
    Session rollover cleanup for 07:45/08:15 prep.

    Do not treat previous-day scanner/gainers as live confirmation input.
    """
    from backend.trading.opening_session_freshness import extract_payload_session_date

    ist = _now_ist(now)
    today = _session_date(ist)
    scanner = _load_json(SCANNER_FILE)
    source_date = str(extract_payload_session_date(scanner) or '')[:10]
    actions: list[str] = []
    live_blocked = False

    if not scanner:
        actions.append('scanner_missing')
        live_blocked = True
    elif source_date and source_date < today:
        actions.append('scanner_previous_session_downgraded')
        live_blocked = True
        print(
            f'[SESSION_ROLLOVER] scanner_source={source_date} today={today} '
            'status=previous_session_context_only',
            flush=True,
        )

    catalyst = _load_json(CATALYST_FILE)
    catalyst_date = str(extract_payload_session_date(catalyst) or '')[:10]
    if catalyst_date and catalyst_date < today:
        actions.append('catalyst_board_previous_session')

    return {
        'session_date': today,
        'scanner_source_date': source_date or '—',
        'live_scanner_blocked': live_blocked,
        'actions': actions,
    }


def premarket_scanner_status_line(*, now: datetime | None = None) -> str:
    """Premarket scanner headline when live data is not yet available."""
    rec = _evaluate_scanner_freshness(None, now=now)
    status = str(rec.get('freshness_status') or FRESHNESS_MISSING)
    if status == FRESHNESS_MISSING:
        return 'Scanner: waiting for market open / no current live data yet'
    if status in (FRESHNESS_PREOPEN_ONLY, FRESHNESS_PREVIOUS_SESSION):
        return 'Scanner: PREVIOUS SESSION CONTEXT — waiting for market open'
    return ''


def previous_session_context_label(row: dict[str, Any] | None, board: dict[str, Any] | None = None) -> str:
    """Label previous-session movers during premarket / stale scanner windows."""
    if not isinstance(row, dict):
        return ''
    prev = bool(row.get('previous_mover') or row.get('previous_session_mover'))
    if not prev:
        return ''
    data = board or {}
    status = str(
        data.get('scanner_freshness_status')
        or (data.get('market_freshness') or {}).get('scanner', {}).get('freshness_status')
        or ''
    )
    if status in (FRESHNESS_PREOPEN_ONLY, FRESHNESS_PREVIOUS_SESSION, FRESHNESS_STALE, FRESHNESS_MISSING, ''):
        return 'PREVIOUS SESSION CONTEXT'
    return ''
