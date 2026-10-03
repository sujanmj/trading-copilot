"""Official NSE pre-open observations; coverage is measured, never inferred.

Ordinary HTTP only. A blocked/unavailable source remains unavailable. This
module collects facts and cannot place orders or send Telegram messages.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import datetime, time as wall_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
SCHEMA_VERSION = '54B'
SOURCE = 'NSE_OFFICIAL_PREOPEN'
ENDPOINT = 'https://www.nseindia.com/api/market-data-pre-open?key=ALL'
LAUNCH = wall_time(8, 58)
OPEN = wall_time(9, 0)
END = wall_time(9, 15, 30)
POLL_SECONDS = 25
START_TOLERANCE_SECONDS = 30
MAX_POLL_GAP_SECONDS = 60
MAX_EVENTS_PER_SYMBOL = 128
MAX_SYMBOLS = 2500
_guard = threading.Lock()
_worker = None
_monitor = None
_started_sessions = set()


def timestamp(value):
    """Require dated source timestamps; never invent a date for a time string."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            parsed = None
            for fmt in ('%d-%b-%Y %H:%M:%S', '%d-%b-%Y %H:%M', '%d-%m-%Y %H:%M:%S'):
                try:
                    parsed = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    pass
            if parsed is None:
                raise ValueError('INVALID_SOURCE_TIMESTAMP')
    else:
        raise ValueError('INVALID_SOURCE_TIMESTAMP')
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)


def number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('INVALID_MARKET_VALUE')
    if not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise ValueError('INVALID_MARKET_VALUE')
    return value


def normalize_events(payload, session_date, received_at):
    received = timestamp(received_at)
    response_time = timestamp(payload.get('timestamp'))
    if response_time.date().isoformat() != session_date or response_time > received:
        raise ValueError('WRONG_OR_FUTURE_RESPONSE_SESSION')
    events = []
    for row in payload.get('data', [])[:MAX_SYMBOLS]:
        try:
            metadata = row['metadata']
            preopen = row['detail']['preOpenMarket']
            symbol = metadata['symbol']
            if not isinstance(symbol, str) or not symbol or symbol != symbol.strip().upper():
                continue
            event_time = timestamp(preopen['lastUpdateTime'])
            if (event_time.date().isoformat() != session_date or
                    not OPEN <= event_time.time() <= wall_time(9, 15, 30) or
                    event_time > response_time):
                continue
            iep = number(preopen['IEP'], positive=True)
            events.append({
                'schema_version': SCHEMA_VERSION, 'session_date': session_date,
                'symbol': symbol, 'source': SOURCE,
                'source_response_time': response_time.isoformat(),
                'source_event_time': event_time.isoformat(), 'iep': iep,
                'previous_close': number(metadata['previousClose'], positive=True),
                'final_price': number(preopen.get('finalPrice', 0)),
                'total_buy_quantity': number(preopen['totalBuyQuantity']),
                'total_sell_quantity': number(preopen['totalSellQuantity']),
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    if not events:
        raise ValueError('NO_VALID_OFFICIAL_EVENTS')
    return events


def new_capture(now):
    now = timestamp(now)
    return {
        'schema_version': SCHEMA_VERSION, 'session_date': now.date().isoformat(),
        'capture_started_at': now.isoformat(), 'first_successful_poll_at': None,
        'last_successful_poll_at': None, 'poll_count': 0, 'failed_poll_count': 0,
        'max_successful_poll_gap_seconds': 0, 'coverage_state': 'NOT_STARTED',
        'events_by_symbol': {}, 'symbol_coverage': {},
    }


def record_poll(capture, now, events=None):
    now = timestamp(now)
    if now.date().isoformat() != capture['session_date']:
        raise ValueError('WRONG_CAPTURE_SESSION')
    capture['poll_count'] += 1
    if not events:
        capture['failed_poll_count'] += 1
        capture['coverage_state'] = coverage_state(capture)
        return
    previous = capture['last_successful_poll_at']
    if previous:
        gap = (now - timestamp(previous)).total_seconds()
        if gap < 0:
            raise ValueError('NON_MONOTONIC_POLL')
        capture['max_successful_poll_gap_seconds'] = max(capture['max_successful_poll_gap_seconds'], gap)
    capture['first_successful_poll_at'] = capture['first_successful_poll_at'] or now.isoformat()
    capture['last_successful_poll_at'] = now.isoformat()
    for event in events:
        if event['session_date'] != capture['session_date'] or timestamp(event['source_event_time']) > now:
            raise ValueError('WRONG_OR_FUTURE_EVENT_SESSION')
        symbol = event['symbol']
        stats = capture['symbol_coverage'].setdefault(symbol, {'first': now.isoformat(), 'last': None, 'max_gap': 0})
        if stats['last']:
            stats['max_gap'] = max(stats['max_gap'], (now - timestamp(stats['last'])).total_seconds())
        stats['last'] = now.isoformat()
        existing = capture['events_by_symbol'].setdefault(symbol, [])
        identity = (event['session_date'], symbol, event['source_event_time'], event['iep'])
        if not any((e['session_date'], e['symbol'], e['source_event_time'], e['iep']) == identity for e in existing):
            existing.append(dict(event))
            existing.sort(key=lambda e: (e['source_event_time'], e['iep']))
            if len(existing) > MAX_EVENTS_PER_SYMBOL:
                # Never silently truncate and then certify a complete range.
                del existing[MAX_EVENTS_PER_SYMBOL:]
                stats['overflow'] = True
    capture['coverage_state'] = coverage_state(capture)


def _covered(first, last, max_gap, session_date):
    if not first or not last:
        return False
    start = timestamp(f'{session_date}T09:00:00+05:30')
    end = timestamp(f'{session_date}T09:15:30+05:30')
    return (start <= timestamp(first) <= start + timedelta(seconds=START_TOLERANCE_SECONDS)
            and end <= timestamp(last) <= end + timedelta(seconds=MAX_POLL_GAP_SECONDS)
            and max_gap <= MAX_POLL_GAP_SECONDS)


def coverage_state(capture):
    if not capture['first_successful_poll_at']:
        return 'SOURCE_ERROR' if capture['failed_poll_count'] else 'NOT_STARTED'
    began = timestamp(capture['capture_started_at'])
    early = began.date().isoformat() == capture['session_date'] and began.time() < OPEN
    complete = early and _covered(capture['first_successful_poll_at'], capture['last_successful_poll_at'],
                                 capture['max_successful_poll_gap_seconds'], capture['session_date'])
    return 'COMPLETE' if complete else 'PARTIAL'


def derive_premarket(capture, symbol, cutoff):
    cutoff = timestamp(cutoff)
    result = {'premarket_reference_price': None, 'premarket_high': None,
              'premarket_low': None, 'missing_inputs': [], 'source_event_time': None}
    if not capture or capture.get('session_date') != cutoff.date().isoformat():
        result['missing_inputs'] = ['PREOPEN_WRONG_OR_MISSING_SESSION']
        return result
    events = [e for e in capture.get('events_by_symbol', {}).get(symbol, [])
              if e.get('source') == SOURCE and e.get('symbol') == symbol
              and e.get('session_date') == capture['session_date']
              and timestamp(e['source_event_time']) <= cutoff
              and timestamp(e['source_response_time']) <= cutoff]
    events.sort(key=lambda e: e['source_event_time'])
    if not events:
        result['missing_inputs'] = ['PREOPEN_REFERENCE_MISSING']
        return result
    result['premarket_reference_price'] = events[-1]['iep']
    result['source_event_time'] = events[-1]['source_event_time']
    stats = capture.get('symbol_coverage', {}).get(symbol, {})
    last_poll = capture.get('last_successful_poll_at')
    if (coverage_state(capture) != 'COMPLETE' or not last_poll or timestamp(last_poll) > cutoff
            or not _covered(stats.get('first'), stats.get('last'), stats.get('max_gap', float('inf')), capture['session_date'])
            or stats.get('overflow')):
        result['missing_inputs'].append('PREOPEN_COVERAGE_INCOMPLETE')
    elif len({(e['source_event_time'], e['iep']) for e in events}) < 2:
        result['missing_inputs'].append('RANGE_SOURCE_INSUFFICIENT')
    else:
        result['premarket_high'] = max(number(e['iep'], positive=True) for e in events)
        result['premarket_low'] = min(number(e['iep'], positive=True) for e in events)
    return result


def save_capture(capture, path=None):
    path = Path(path) if path else get_data_path('runtime/nse_preopen_iep.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(capture, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def load_capture(session_date, path=None):
    path = Path(path) if path else get_data_path('runtime/nse_preopen_iep.json')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if data.get('schema_version') == SCHEMA_VERSION and data.get('session_date') == session_date else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


class OfficialNSEClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                                     'Referer': 'https://www.nseindia.com/'})
        self.bootstrapped = False

    def fetch(self):
        if not self.bootstrapped:
            self.session.get('https://www.nseindia.com/', timeout=(3, 7)).raise_for_status()
            self.bootstrapped = True
        response = self.session.get(ENDPOINT, timeout=(3, 7))
        response.raise_for_status()
        return response.json()

    def close(self):
        self.session.close()


def is_cash_session(day):
    from backend.analytics.market_calendar_router import is_india_market_day, get_holiday_calendar_summary
    # The legacy router falls back to weekdays if its calendar is missing.
    # Automated capture must not guess through an absent/old holiday file.
    india = get_holiday_calendar_summary()['india']
    if india.get('year') != day.year or india.get('holidays', 0) < 5:
        raise ValueError('CASH_CALENDAR_UNAVAILABLE')
    return is_india_market_day(day)


def is_capture_window(now):
    now = timestamp(now)
    return LAUNCH <= now.time() <= END and is_cash_session(now.date())


def _capture_worker(session_date, *, now_fn=None):
    # OS advisory lock is released automatically on crash. A restart may resume
    # the same session, but its missing interval remains visible in coverage.
    import fcntl
    now_fn = now_fn or (lambda: datetime.now(IST))
    lock_path = get_data_path('runtime/nse_preopen_iep.lock')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        capture = load_capture(session_date) or new_capture(now_fn())
        client = OfficialNSEClient()
        try:
            save_capture(capture)
            while True:
                now = now_fn()
                if now.date().isoformat() != session_date:
                    break
                if now.time() < OPEN:
                    time.sleep(min(POLL_SECONDS, (timestamp(f'{session_date}T09:00:00+05:30') - now).total_seconds()))
                    continue
                try:
                    events = normalize_events(client.fetch(), session_date, now_fn())
                except (requests.RequestException, ValueError, TypeError, KeyError):
                    events = None
                record_poll(capture, now_fn(), events)
                save_capture(capture)
                if now_fn().time() >= END:
                    break
                time.sleep(min(POLL_SECONDS, max(0, (timestamp(f'{session_date}T09:15:30+05:30') - now_fn()).total_seconds())))
        finally:
            client.close()


def start_capture(now=None):
    global _worker
    if os.environ.get('LOCAL_ONLY') == '1' or os.environ.get('DISABLE_SCHEDULER') == '1':
        return False
    now = timestamp(now or datetime.now(IST))
    if not is_capture_window(now):
        return False
    session_date = now.date().isoformat()
    with _guard:
        if session_date in _started_sessions or (_worker and _worker.is_alive()):
            return False
        _started_sessions.clear()
        _started_sessions.add(session_date)
        _worker = threading.Thread(target=_capture_worker, args=(session_date,),
                                   name='NSE-Preopen-Capture', daemon=True)
        _worker.start()
        return True


def start_automatic_capture():
    """Background clock check prevents long existing jobs missing 08:58.

Called only by the existing primary scheduler, after its singleton guard.
No second scheduler process, no new service, and no laptop dependency.
"""
    global _monitor
    if os.environ.get('LOCAL_ONLY') == '1' or os.environ.get('DISABLE_SCHEDULER') == '1':
        return False
    def monitor():
        while True:
            try:
                start_capture()
            except Exception:
                print('[NSE PREOPEN] capture dispatch unavailable', flush=True)
            time.sleep(10)
    with _guard:
        if _monitor and _monitor.is_alive():
            return False
        _monitor = threading.Thread(target=monitor, name='NSE-Preopen-Clock', daemon=True)
        _monitor.start()
        return True
