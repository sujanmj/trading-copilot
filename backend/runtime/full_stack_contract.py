"""Pure 54B source contract shared by source construction and the adapter."""
from __future__ import annotations

import math
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
SCHEMA_VERSION = '54B'
MAX_QUOTE_AGE_SECONDS = 90
SCALAR_KEYS = ('previous_close', 'observation_price', 'premarket_reference_price',
               'premarket_high', 'premarket_low')
BUNDLE_KEYS = {'schema_version', 'symbol', 'session_date', 'observation_cutoff',
               'source_state', 'missing_inputs', 'source_times', 'frames', *SCALAR_KEYS}
TIME_KEYS = {'quote_trade_time', 'quote_feed_time', 'previous_close_session',
             'preopen_event_time', 'preopen_coverage_state', 'preopen_completed_at'}


def aware_time(value):
    if not isinstance(value, str):
        raise ValueError('INVALID_TIMESTAMP')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('NAIVE_TIMESTAMP')
    return parsed.astimezone(IST)


def valid_number(value, positive=True):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def completed_candles(rows, minutes, cutoff):
    """Drop an in-progress bar; reject malformed, future, duplicate or wrong-day rows."""
    result = []
    previous = None
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 6:
            raise ValueError('MALFORMED_CANDLE')
        start = aware_time(row[0])
        if start.date() != cutoff.date() or start > cutoff:
            raise ValueError('WRONG_SESSION_OR_FUTURE_CANDLE')
        if (start.time() < time(9, 15) or start.time() >= time(15, 30)
                or start.second or start.microsecond
                or (start.hour * 60 + start.minute - 555) % minutes
                or (previous is not None and start != previous + timedelta(minutes=minutes))):
            raise ValueError('INVALID_CANDLE_SEQUENCE')
        previous = start
        open_, high, low, close, volume = row[1:]
        if (not all(valid_number(v) for v in (open_, high, low, close))
                or not valid_number(volume, positive=False)
                or high < max(open_, close, low) or low > min(open_, close, high)):
            raise ValueError('MALFORMED_OHLCV')
        if start + timedelta(minutes=minutes) <= cutoff:
            result.append({'timestamp': start.isoformat(), 'open': open_, 'high': high,
                           'low': low, 'close': close, 'volume': volume})
    return result


def validate_bundle(bundle):
    """Revalidate caller-supplied READY envelopes before invoking frozen analysis."""
    if not isinstance(bundle, dict) or set(bundle) != BUNDLE_KEYS:
        return ['INVALID_SOURCE_CONTRACT']
    if (bundle['schema_version'] != SCHEMA_VERSION
            or not isinstance(bundle['symbol'], str)
            or not re.fullmatch(r'[A-Z0-9&_.-]{1,40}', bundle['symbol'])
            or not isinstance(bundle['missing_inputs'], list)
            or any(not isinstance(r, str) for r in bundle['missing_inputs'])):
        return ['INVALID_SOURCE_CONTRACT']
    if bundle['source_state'] != 'READY':
        return bundle['missing_inputs'] or ['SOURCE_NOT_READY']
    if bundle['missing_inputs']:
        return ['INCONSISTENT_SOURCE_STATE']
    try:
        cutoff = aware_time(bundle['observation_cutoff'])
        if cutoff.date().isoformat() != bundle['session_date'] or not time(9, 15, 30) <= cutoff.time() <= time(15, 30):
            return ['INVALID_OBSERVATION_SESSION']
        if not all(valid_number(bundle[k]) for k in SCALAR_KEYS):
            return ['INVALID_SNAPSHOT_VALUE']
        if not bundle['premarket_low'] <= bundle['premarket_reference_price'] <= bundle['premarket_high']:
            return ['INVALID_PREOPEN_RANGE']
        times = bundle['source_times']
        if not isinstance(times, dict) or set(times) != TIME_KEYS:
            return ['INVALID_SOURCE_TIMES']
        previous_session = datetime.strptime(times['previous_close_session'], '%Y-%m-%d').date()
        if not previous_session < cutoff.date():
            return ['PREVIOUS_CLOSE_SESSION_INVALID']
        for key in ('quote_trade_time', 'quote_feed_time'):
            source_time = aware_time(times[key])
            if source_time.date() != cutoff.date() or not time(9, 15) <= source_time.time() <= time(15, 30):
                return ['QUOTE_WRONG_SESSION']
            age = (cutoff - source_time).total_seconds()
            if not 0 <= age <= MAX_QUOTE_AGE_SECONDS:
                return ['QUOTE_FUTURE_OR_STALE']
        if aware_time(times['quote_trade_time']) > aware_time(times['quote_feed_time']):
            return ['QUOTE_TIME_ORDER_INVALID']
        event = aware_time(times['preopen_event_time'])
        completed = aware_time(times['preopen_completed_at'])
        if (times['preopen_coverage_state'] != 'COMPLETE' or event.date() != cutoff.date()
                or completed.date() != cutoff.date() or not time(9, 0) <= event.time() <= time(9, 15, 30)
                or event > completed or completed > cutoff or completed.time() < time(9, 15, 30)):
            return ['PREOPEN_COVERAGE_INVALID']
        frames = bundle['frames']
        if not isinstance(frames, list) or len(frames) != 2 or {f['timeframe'] for f in frames} != {'1m', '5m'}:
            return ['INVALID_FRAMES']
        for frame in frames:
            if set(frame) != {'timeframe', 'candles'} or not isinstance(frame['candles'], list) or not frame['candles']:
                return ['CANDLES_MISSING']
            minutes = int(frame['timeframe'][:-1])
            rows = []
            for candle in frame['candles']:
                if not isinstance(candle, dict) or set(candle) != {'timestamp', 'open', 'high', 'low', 'close', 'volume'}:
                    return ['MALFORMED_CANDLE']
                rows.append([candle[k] for k in ('timestamp', 'open', 'high', 'low', 'close', 'volume')])
            checked = completed_candles(rows, minutes, cutoff)
            if len(checked) != len(rows):
                return ['PARTIAL_CANDLE']
            latest_end = aware_time(checked[-1]['timestamp']) + timedelta(minutes=minutes)
            if (cutoff - latest_end).total_seconds() >= minutes * 60:
                return ['STALE_CANDLES']
        return []
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return ['INVALID_SOURCE_CONTRACT']
