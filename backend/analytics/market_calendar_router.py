"""
Market session router — India / USA session windows with holiday awareness.

Read-only calendar logic based on real session times; never invents market status
from price files or fake feeds.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from backend.utils.config import DATA_DIR, PROJECT_ROOT

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None  # type: ignore[assignment]

IST_TZ_NAME = 'Asia/Kolkata'
US_TZ_NAME = 'America/New_York'

INDIA_HOLIDAYS_PATH = DATA_DIR / 'market_holidays_india.json'
USA_HOLIDAYS_PATH = DATA_DIR / 'market_holidays_usa.json'

MIN_SAMPLE_HOLIDAYS = 5
VALID_HOLIDAY_TYPES = frozenset({'full_day', 'early_close', 'special_session'})
USA_EARLY_CLOSE_DEFAULT = time(13, 0)

# Session boundaries (local market time)
INDIA_PREMARKET = (time(7, 45), time(9, 0))
INDIA_PREOPEN = (time(9, 0), time(9, 15))
INDIA_REGULAR = (time(9, 15), time(15, 30))
INDIA_POSTMARKET = (time(15, 30), time(16, 30))
INDIA_AFTER_HOURS_END = time(23, 0)

USA_PREMARKET = (time(4, 0), time(9, 30))
USA_REGULAR = (time(9, 30), time(16, 0))
USA_POSTMARKET = (time(16, 0), time(20, 0))

MODE_INDIA = 'INDIA_MODE'
MODE_INDIA_PREMARKET = 'INDIA_PREMARKET_MODE'
MODE_INDIA_PREOPEN = 'INDIA_PREOPEN_MODE'
MODE_INDIA_POSTMARKET = 'INDIA_POSTMARKET_MODE'
MODE_INDIA_AFTER_HOURS = 'INDIA_AFTER_HOURS_MODE'
MODE_USA = 'USA_MODE'
MODE_USA_PREMARKET = 'USA_PREMARKET_MODE'
MODE_USA_POSTMARKET = 'USA_POSTMARKET_MODE'
MODE_RESEARCH = 'RESEARCH_MODE'

SESSION_CLOSED = 'closed'
SESSION_PREMARKET = 'premarket'
SESSION_REGULAR = 'regular'
SESSION_POSTMARKET = 'postmarket'

_MODE_LABELS = {
    MODE_INDIA: 'India Regular Session',
    MODE_INDIA_PREMARKET: 'India Pre-Market',
    MODE_INDIA_PREOPEN: 'India Pre-Open',
    MODE_INDIA_POSTMARKET: 'India Post-Market',
    MODE_INDIA_AFTER_HOURS: 'India After Hours',
    MODE_USA: 'USA Regular Session',
    MODE_USA_PREMARKET: 'USA Pre-Market',
    MODE_USA_POSTMARKET: 'USA Post-Market',
    MODE_RESEARCH: 'Research Mode',
}

_FOCUS_BY_MODE = {
    MODE_INDIA: 'Prioritize India equities — NSE/BSE live session',
    MODE_INDIA_PREMARKET: 'India pre-open prep — gaps, news, and opening range',
    MODE_INDIA_PREOPEN: 'India pre-open auction window — confirm setups only',
    MODE_INDIA_POSTMARKET: 'India post-close review — outcomes and next-day setup',
    MODE_INDIA_AFTER_HOURS: 'India after-hours — light intel, no emergency spam',
    MODE_USA: 'Prioritize US equities — NYSE/NASDAQ live session',
    MODE_USA_PREMARKET: 'US pre-market movers — futures, earnings, and gap watch',
    MODE_USA_POSTMARKET: 'US after-hours digest — earnings reactions and global spillover',
    MODE_RESEARCH: 'Research mode — memory review, macro synthesis, and prep for next open',
}

_holiday_cache: dict[str, dict[str, Any]] = {}


def _tz(name: str):
    if ZoneInfo is not None:
        return ZoneInfo(name)
    if pytz is not None:
        return pytz.timezone(name)
    raise RuntimeError('Neither zoneinfo nor pytz is available for timezone support')


def _now_utc(now_utc: Optional[datetime] = None) -> datetime:
    if now_utc is None:
        return datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(timezone.utc)


def _to_local(dt_utc: datetime, tz_name: str) -> datetime:
    return _now_utc(dt_utc).astimezone(_tz(tz_name))


def _parse_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if 'T' in text:
        text = text.split('T', 1)[0]
    return date.fromisoformat(text)


def _parse_time(value: object, default: time) -> time:
    if isinstance(value, time):
        return value
    text = str(value or '').strip()
    if not text:
        return default
    parts = text.split(':')
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return time(hour, minute)
    except (TypeError, ValueError, IndexError):
        return default


def _load_holiday_file(path: Path) -> dict[str, Any]:
    key = str(path.resolve())
    if key in _holiday_cache:
        return _holiday_cache[key]

    payload: dict[str, Any] = {
        'path': str(path),
        'exists': path.is_file(),
        'market': None,
        'year': None,
        'timezone': None,
        'holidays': [],
        'holiday_dates': set(),
        'holiday_names': {},
        'holiday_types': {},
        'early_closes': [],
        'early_close_dates': {},
        'special_sessions': [],
        'special_session_dates': {},
        'warnings': [],
        'valid_for_current_year': False,
    }
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                payload['market'] = raw.get('market')
                payload['year'] = raw.get('year')
                payload['timezone'] = raw.get('timezone')
                payload['warnings'] = list(raw.get('warnings') or [])

                holidays = raw.get('holidays') or []
                if isinstance(holidays, list):
                    for item in holidays:
                        if not isinstance(item, dict):
                            continue
                        day = str(item.get('date') or '').strip()
                        if not day:
                            continue
                        payload['holiday_dates'].add(day)
                        payload['holiday_names'][day] = str(item.get('name') or 'Holiday')
                        htype = str(item.get('type') or 'full_day')
                        if htype not in VALID_HOLIDAY_TYPES:
                            htype = 'full_day'
                        payload['holiday_types'][day] = htype
                        payload['holidays'].append(item)

                early_closes = raw.get('early_closes') or []
                if isinstance(early_closes, list):
                    payload['early_closes'] = early_closes
                    for item in early_closes:
                        if not isinstance(item, dict):
                            continue
                        day = str(item.get('date') or '').strip()
                        if not day:
                            continue
                        close_time = _parse_time(item.get('close_time'), USA_EARLY_CLOSE_DEFAULT)
                        payload['early_close_dates'][day] = close_time

                special_sessions = raw.get('special_sessions') or []
                if isinstance(special_sessions, list):
                    payload['special_sessions'] = special_sessions
                    for item in special_sessions:
                        if not isinstance(item, dict):
                            continue
                        day = str(item.get('date') or '').strip()
                        if not day:
                            continue
                        payload['special_session_dates'][day] = item
        except Exception:
            payload['exists'] = False

    current_year = _now_utc().year
    payload['valid_for_current_year'] = (
        payload.get('exists')
        and payload.get('year') == current_year
        and len(payload.get('holidays') or []) > 0
    )

    _holiday_cache[key] = payload
    return payload


def _calendar_warnings_for_file(path: Path, label: str) -> list[str]:
    meta = _load_holiday_file(path)
    warnings: list[str] = []
    current_year = _now_utc().year

    if not meta.get('exists'):
        warnings.append('holiday_calendar_incomplete')
        return warnings

    file_year = meta.get('year')
    if file_year is None:
        warnings.append('holiday_calendar_missing_year')
    elif file_year != current_year:
        warnings.append('holiday_calendar_missing_year')

    if not meta.get('holidays'):
        warnings.append('holiday_calendar_empty')

    return warnings


def _holiday_warnings() -> list[str]:
    warnings: list[str] = []
    warnings.extend(_calendar_warnings_for_file(INDIA_HOLIDAYS_PATH, 'india'))
    warnings.extend(_calendar_warnings_for_file(USA_HOLIDAYS_PATH, 'usa'))
    return sorted(set(warnings))


def get_holiday_calendar_summary() -> dict[str, Any]:
    """Summary for API/GUI/scripts."""
    india = _load_holiday_file(INDIA_HOLIDAYS_PATH)
    usa = _load_holiday_file(USA_HOLIDAYS_PATH)
    warnings = _holiday_warnings()
    today = _now_utc().date()

    return {
        'ok': True,
        'calendar_ok': not warnings,
        'holiday_calendar_status': 'OK' if not warnings else 'WARN',
        'warnings': warnings,
        'india': {
            'year': india.get('year'),
            'holidays': len(india.get('holidays') or []),
            'special_sessions': len(india.get('special_sessions') or []),
            'next_holiday': get_next_holiday('india', today),
        },
        'usa': {
            'year': usa.get('year'),
            'holidays': len(usa.get('holidays') or []),
            'early_closes': len(usa.get('early_closes') or []),
            'next_holiday': get_next_holiday('usa', today),
            'next_early_close': get_next_early_close('usa', today),
        },
    }


def get_next_holiday(market: str, from_day: date | None = None) -> dict[str, Any] | None:
    token = str(market or '').strip().lower()
    path = INDIA_HOLIDAYS_PATH if token == 'india' else USA_HOLIDAYS_PATH
    meta = _load_holiday_file(path)
    start = from_day or _now_utc().date()
    candidates: list[tuple[date, dict[str, Any]]] = []
    for item in meta.get('holidays') or []:
        if not isinstance(item, dict):
            continue
        day_text = str(item.get('date') or '').strip()
        if not day_text:
            continue
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        if day >= start:
            candidates.append((day, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    day, item = candidates[0]
    return {
        'date': day.isoformat(),
        'name': item.get('name'),
        'type': item.get('type') or 'full_day',
        'days_until': (day - start).days,
    }


def get_next_early_close(market: str, from_day: date | None = None) -> dict[str, Any] | None:
    token = str(market or '').strip().lower()
    if token != 'usa':
        return None
    meta = _load_holiday_file(USA_HOLIDAYS_PATH)
    start = from_day or _now_utc().date()
    candidates: list[tuple[date, dict[str, Any]]] = []
    for item in meta.get('early_closes') or []:
        if not isinstance(item, dict):
            continue
        day_text = str(item.get('date') or '').strip()
        if not day_text:
            continue
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        if day >= start:
            candidates.append((day, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    day, item = candidates[0]
    return {
        'date': day.isoformat(),
        'name': item.get('name'),
        'close_time': item.get('close_time') or '13:00',
        'days_until': (day - start).days,
    }


def _early_close_time(market: str, day: date) -> time | None:
    if market != 'usa':
        return None
    meta = _load_holiday_file(USA_HOLIDAYS_PATH)
    return meta.get('early_close_dates', {}).get(day.isoformat())


def _special_session_info(market: str, day: date) -> dict[str, Any] | None:
    path = INDIA_HOLIDAYS_PATH if market == 'india' else USA_HOLIDAYS_PATH
    meta = _load_holiday_file(path)
    item = meta.get('special_session_dates', {}).get(day.isoformat())
    if not isinstance(item, dict):
        return None
    return {
        'date': day.isoformat(),
        'name': item.get('name'),
        'type': 'special_session',
        'note': item.get('note'),
    }


def _format_early_close_label(close_t: time, tz_label: str = 'ET') -> str:
    hour = close_t.hour % 12 or 12
    ampm = 'AM' if close_t.hour < 12 else 'PM'
    minute = f':{close_t.minute:02d}' if close_t.minute else ''
    return f'Regular Session (early close {hour}{minute} {ampm} {tz_label})'


def clear_holiday_cache() -> None:
    _holiday_cache.clear()


def _holiday_name(market: str, day: date) -> Optional[str]:
    path = INDIA_HOLIDAYS_PATH if market == 'india' else USA_HOLIDAYS_PATH
    meta = _load_holiday_file(path)
    return meta.get('holiday_names', {}).get(day.isoformat())


def is_india_market_day(value: date | datetime | str) -> bool:
    """True on a weekday that is not an India exchange holiday."""
    day = _parse_date(value)
    if day.weekday() >= 5:
        return False
    meta = _load_holiday_file(INDIA_HOLIDAYS_PATH)
    return day.isoformat() not in meta.get('holiday_dates', set())


def is_us_market_day(value: date | datetime | str) -> bool:
    """True on a weekday that is not a US exchange holiday."""
    day = _parse_date(value)
    if day.weekday() >= 5:
        return False
    meta = _load_holiday_file(USA_HOLIDAYS_PATH)
    return day.isoformat() not in meta.get('holiday_dates', set())


def _in_window(local_t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= local_t < end
    return local_t >= start or local_t < end


def _session_for_market(
    market: str,
    now_utc: datetime,
) -> dict[str, Any]:
    tz_name = IST_TZ_NAME if market == 'india' else US_TZ_NAME
    local_dt = _to_local(now_utc, tz_name)
    local_day = local_dt.date()
    local_t = local_dt.time().replace(microsecond=0)

    if market == 'india':
        is_day = is_india_market_day(local_day)
        pre, preopen, reg, post = INDIA_PREMARKET, INDIA_PREOPEN, INDIA_REGULAR, INDIA_POSTMARKET
        reg_end = reg[1]
    else:
        is_day = is_us_market_day(local_day)
        pre, preopen, reg, post = USA_PREMARKET, (time(0, 0), time(0, 0)), USA_REGULAR, USA_POSTMARKET
        early_close = _early_close_time(market, local_day)
        reg_end = early_close if early_close is not None else reg[1]

    holiday = _holiday_name(market, local_day) if not is_day and local_day.weekday() < 5 else None
    special_session = _special_session_info(market, local_day)
    session = SESSION_CLOSED
    session_label = 'Closed'
    is_open = False
    early_close_today = market == 'usa' and _early_close_time(market, local_day) is not None
    early_close_t = _early_close_time(market, local_day) if early_close_today else None

    if is_day:
        if _in_window(local_t, reg[0], reg_end):
            session = SESSION_REGULAR
            session_label = 'Regular Session'
            if early_close_today and early_close_t is not None:
                session_label = _format_early_close_label(early_close_t)
            is_open = True
        elif _in_window(local_t, pre[0], pre[1]):
            session = SESSION_PREMARKET
            session_label = 'Pre-Market'
        elif market == 'india' and _in_window(local_t, preopen[0], preopen[1]):
            session = SESSION_PREMARKET
            session_label = 'Pre-Open'
        elif _in_window(local_t, post[0], post[1]) and not early_close_today:
            session = SESSION_POSTMARKET
            session_label = 'Post-Market'
        elif local_day.weekday() >= 5:
            session_label = 'Weekend'
        else:
            session_label = 'Closed (off-hours)'
            if early_close_today and local_t >= reg_end:
                session_label = 'Closed (early close day)'

    if local_day.weekday() >= 5:
        session = SESSION_CLOSED
        session_label = 'Weekend'
        is_open = False
    elif holiday:
        session = SESSION_CLOSED
        session_label = f'Holiday — {holiday}'
    elif special_session:
        session = SESSION_CLOSED
        name = special_session.get('name') or 'Special Session'
        session_label = f'Special Session — {name}'

    return {
        'market': market,
        'timezone': tz_name,
        'local_time': local_dt.isoformat(),
        'local_date': local_day.isoformat(),
        'is_market_day': is_day,
        'session': session,
        'session_label': session_label,
        'is_open': is_open,
        'holiday_name': holiday,
        'special_session': special_session,
        'early_close_today': early_close_today,
        'early_close_time': reg_end.isoformat(timespec='minutes') if early_close_today else None,
    }


def _india_after_hours(india: dict[str, Any]) -> bool:
    if not india.get('is_market_day'):
        return False
    if india.get('session') != SESSION_CLOSED:
        return False
    label = str(india.get('session_label') or '')
    if 'weekend' in label.lower() or 'holiday' in label.lower():
        return False
    try:
        local_dt = datetime.fromisoformat(str(india.get('local_time', '')))
        if local_dt.weekday() >= 5:
            return False
        local_t = local_dt.time().replace(microsecond=0)
        return local_t >= INDIA_POSTMARKET[1] and local_t < INDIA_AFTER_HOURS_END
    except (ValueError, TypeError):
        return 'off-hours' in label.lower()


def _resolve_active_mode(india: dict[str, Any], usa: dict[str, Any]) -> tuple[str, str]:
    """Return (active_mode, routing_reason)."""
    india_local = ''
    try:
        india_local = datetime.fromisoformat(str(india.get('local_time', ''))).time().replace(microsecond=0)
    except (ValueError, TypeError):
        pass
    india_preopen = (
        india.get('session') == SESSION_PREMARKET
        and india_local
        and _in_window(india_local, INDIA_PREOPEN[0], INDIA_PREOPEN[1])
    )
    india_premarket = (
        india.get('session') == SESSION_PREMARKET
        and not india_preopen
    )
    checks = (
        (india.get('session') == SESSION_REGULAR, MODE_INDIA, 'India regular session active'),
        (usa.get('session') == SESSION_REGULAR, MODE_USA, 'USA regular session active'),
        (india.get('session') == SESSION_POSTMARKET, MODE_INDIA_POSTMARKET, 'India post-market window'),
        (usa.get('session') == SESSION_POSTMARKET, MODE_USA_POSTMARKET, 'USA post-market window'),
        (india_preopen, MODE_INDIA_PREOPEN, 'India pre-open window'),
        (india_premarket, MODE_INDIA_PREMARKET, 'India pre-market window'),
        (usa.get('session') == SESSION_PREMARKET, MODE_USA_PREMARKET, 'USA pre-market window'),
        (_india_after_hours(india), MODE_INDIA_AFTER_HOURS, 'India after-hours window'),
    )
    for cond, mode, reason in checks:
        if cond:
            return mode, reason
    return MODE_RESEARCH, 'No active India or USA trading session'


def _combine_open_local(day: date, open_time: time, tz_name: str) -> datetime:
    tz = _tz(tz_name)
    naive = datetime.combine(day, open_time)
    if hasattr(tz, 'localize'):
        return tz.localize(naive)
    return naive.replace(tzinfo=tz)


def get_next_market_open(market: str, now_utc: Optional[datetime] = None) -> dict[str, Any]:
    """Next regular-session open for india or usa."""
    token = str(market or '').strip().lower()
    if token not in ('india', 'usa'):
        return {'ok': False, 'error': f'unsupported market: {market}'}

    now = _now_utc(now_utc)
    tz_name = IST_TZ_NAME if token == 'india' else US_TZ_NAME
    open_time = INDIA_REGULAR[0] if token == 'india' else USA_REGULAR[0]
    is_day_fn = is_india_market_day if token == 'india' else is_us_market_day

    local_now = _to_local(now, tz_name)
    candidate_day = local_now.date()

    # If still before today's open on a market day, next open is today.
    if is_day_fn(candidate_day) and local_now.time() < open_time:
        next_local = _combine_open_local(candidate_day, open_time, tz_name)
    else:
        candidate_day = candidate_day + timedelta(days=1)
        for _ in range(366):
            if is_day_fn(candidate_day):
                break
            candidate_day += timedelta(days=1)
        next_local = _combine_open_local(candidate_day, open_time, tz_name)

    next_utc = next_local.astimezone(timezone.utc)
    days_until = (candidate_day - local_now.date()).days

    return {
        'ok': True,
        'market': token,
        'next_open_utc': next_utc.isoformat(),
        'next_open_local': next_local.isoformat(),
        'next_open_date': candidate_day.isoformat(),
        'days_until': days_until,
        'timezone': tz_name,
    }


def get_market_session_status(now_utc: Optional[datetime] = None) -> dict[str, Any]:
    """Per-market session snapshot at now (UTC)."""
    now = _now_utc(now_utc)
    warnings = _holiday_warnings()
    india = _session_for_market('india', now)
    usa = _session_for_market('usa', now)
    calendar = get_holiday_calendar_summary()

    if usa.get('early_close_today'):
        warnings = sorted(set(warnings + ['usa_early_close_today']))

    return {
        'ok': True,
        'checked_at': now.isoformat(),
        'now_utc': now.isoformat(),
        'india': india,
        'usa': usa,
        'holiday_files': {
            'india': str(INDIA_HOLIDAYS_PATH.relative_to(PROJECT_ROOT)),
            'usa': str(USA_HOLIDAYS_PATH.relative_to(PROJECT_ROOT)),
        },
        'holiday_calendar': calendar,
        'warnings': warnings,
    }


def get_active_market_mode(now_utc: Optional[datetime] = None) -> dict[str, Any]:
    """Primary routing mode with recommended focus and next opens."""
    now = _now_utc(now_utc)
    status = get_market_session_status(now)
    india = status['india']
    usa = status['usa']
    active_mode, routing_reason = _resolve_active_mode(india, usa)

    return {
        'ok': True,
        'checked_at': now.isoformat(),
        'now_utc': now.isoformat(),
        'active_mode': active_mode,
        'active_mode_label': _MODE_LABELS.get(active_mode, active_mode),
        'recommended_focus': _FOCUS_BY_MODE.get(active_mode, ''),
        'routing_reason': routing_reason,
        'india_session': india.get('session'),
        'india_session_label': india.get('session_label'),
        'usa_session': usa.get('session'),
        'usa_session_label': usa.get('session_label'),
        'india': india,
        'usa': usa,
        'next_india_open': get_next_market_open('india', now),
        'next_usa_open': get_next_market_open('usa', now),
        'warnings': status.get('warnings') or [],
    }


def get_market_router_payload(now_utc: Optional[datetime] = None) -> dict[str, Any]:
    """Combined payload for API / GUI."""
    status = get_market_session_status(now_utc)
    mode = get_active_market_mode(now_utc)
    return {
        'ok': True,
        'checked_at': mode.get('checked_at'),
        'now_utc': mode.get('now_utc'),
        'active_mode': mode.get('active_mode'),
        'active_mode_label': mode.get('active_mode_label'),
        'recommended_focus': mode.get('recommended_focus'),
        'routing_reason': mode.get('routing_reason'),
        'india_session': mode.get('india_session'),
        'india_session_label': mode.get('india_session_label'),
        'usa_session': mode.get('usa_session'),
        'usa_session_label': mode.get('usa_session_label'),
        'india': status.get('india'),
        'usa': status.get('usa'),
        'next_india_open': mode.get('next_india_open'),
        'next_usa_open': mode.get('next_usa_open'),
        'session_status': status,
        'active_market_mode': mode,
        'holiday_calendar': status.get('holiday_calendar'),
        'warnings': sorted(set((status.get('warnings') or []) + (mode.get('warnings') or []))),
    }
