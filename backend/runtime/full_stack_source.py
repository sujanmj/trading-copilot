"""Timestamped real-source facts for one final candidate; no scanner integration."""
from __future__ import annotations

from datetime import timedelta

from backend.collectors.nse_preopen_iep import derive_premarket, is_cash_session, load_capture, timestamp
from backend.runtime.full_stack_contract import SCALAR_KEYS, completed_candles, valid_number, validate_bundle

SAFE_FAILURE_REASONS = {
    'NOT_TRADING_SESSION', 'CASH_CALENDAR_UNAVAILABLE', 'PREVIOUS_SESSION_UNAVAILABLE',
    'PREVIOUS_CLOSE_SESSION_UNAVAILABLE', 'PREVIOUS_CLOSE_MALFORMED',
    'PREVIOUS_CLOSE_SOURCE_MISMATCH', 'DAILY_SOURCE_UNAVAILABLE', 'QUOTE_UNAVAILABLE',
    'QUOTE_IDENTITY_MISMATCH', 'CANDLES_1M_UNAVAILABLE', 'CANDLES_5M_UNAVAILABLE',
    'INVALID_SOURCE_TIMESTAMP', 'INVALID_TIMESTAMP', 'NAIVE_TIMESTAMP',
    'INVALID_MARKET_VALUE', 'MALFORMED_CANDLE', 'WRONG_SESSION_OR_FUTURE_CANDLE',
    'INVALID_CANDLE_SEQUENCE', 'MALFORMED_OHLCV', 'ANGEL_UNAVAILABLE',
    'INVALID_SYMBOL_BATCH', 'TOKEN_NOT_FOUND', 'ANGEL_QUOTE_FAILED',
    'QUOTE_BATCH_INCOMPLETE', 'ANGEL_QUOTE_ERROR',
}


def previous_session(session_date):
    day = timestamp(f'{session_date}T00:00:00+05:30').date()
    for offset in range(1, 11):
        candidate = day - timedelta(days=offset)
        if is_cash_session(candidate):
            return candidate.isoformat()
    raise ValueError('PREVIOUS_SESSION_UNAVAILABLE')


def daily_previous_close(rows, session_date):
    expected = previous_session(session_date)
    matching = [r for r in rows if isinstance(r, (list, tuple)) and len(r) == 6
                and timestamp(r[0]).date().isoformat() == expected]
    if len(matching) != 1:
        raise ValueError('PREVIOUS_CLOSE_SESSION_UNAVAILABLE')
    row = matching[0]
    if (not all(valid_number(v) for v in row[1:5]) or not valid_number(row[5], positive=False)
            or row[2] < max(row[1], row[3], row[4]) or row[3] > min(row[1], row[2], row[4])):
        raise ValueError('PREVIOUS_CLOSE_MALFORMED')
    return row[4], expected


def build_source_bundle(symbol, cutoff, *, capture=None, quote_fetch=None, candle_fetch=None):
    """Fetch only one requested symbol. Providers may be injected for offline tests.

An explicit cutoff is mandatory. A live fetch newer than that cutoff is not
historical evidence and remains not ready. No synthetic fallback is used.
"""
    bundle = {
        'schema_version': '54B', 'symbol': symbol, 'session_date': None,
        'observation_cutoff': cutoff, 'source_state': 'INPUT_NOT_READY',
        'missing_inputs': [], 'source_times': {}, 'frames': [],
        **{key: None for key in SCALAR_KEYS},
    }
    try:
        observed = timestamp(cutoff)
        # Public cutoff must be explicitly timezone aware.
        from backend.runtime.full_stack_contract import aware_time
        aware_time(cutoff)
        bundle['session_date'] = observed.date().isoformat()
        bundle['observation_cutoff'] = observed.isoformat()
        if not is_cash_session(observed.date()):
            raise ValueError('NOT_TRADING_SESSION')
        capture = capture if capture is not None else load_capture(bundle['session_date'])
        preopen = derive_premarket(capture, symbol, observed)
        for key in ('premarket_reference_price', 'premarket_high', 'premarket_low'):
            bundle[key] = preopen[key]
        bundle['missing_inputs'].extend(preopen['missing_inputs'])
        # Fail cheaply before requesting broker candles if auction truth is absent.
        if bundle['missing_inputs']:
            return bundle
        if quote_fetch is None or candle_fetch is None:
            from backend.utils.angel_one_client import fetch_full_quotes, fetch_source_candles
            quote_fetch = quote_fetch or fetch_full_quotes
            candle_fetch = candle_fetch or fetch_source_candles
        response = quote_fetch([symbol])
        if response.get('source_state') != 'READY':
            raise ValueError(response.get('reason') or 'QUOTE_UNAVAILABLE')
        quote = response['data'][symbol]
        if quote['symbol'] != symbol or quote['source'] != 'ANGEL_FULL':
            raise ValueError('QUOTE_IDENTITY_MISMATCH')
        bundle['observation_price'] = quote['ltp']
        prior = previous_session(bundle['session_date'])
        daily = candle_fetch(symbol, 'ONE_DAY', timestamp(f'{prior}T00:00:00+05:30'),
                             timestamp(f"{bundle['session_date']}T00:00:00+05:30"))
        if daily.get('source_state') != 'READY' or daily.get('symbol') != symbol or daily.get('interval') != 'ONE_DAY':
            raise ValueError('DAILY_SOURCE_UNAVAILABLE')
        close, close_session = daily_previous_close(daily['data'], bundle['session_date'])
        # FULL.close may roll on the provider; the completed daily bar is proof.
        full_close = quote.get('previous_close')
        bundle['previous_close'] = (full_close if valid_number(full_close)
                                   and abs(full_close - close) <= max(0.01, close * 0.000001)
                                   else close)
        relevant = capture['events_by_symbol'][symbol]
        if any(abs(e['previous_close'] - close) > max(0.01, close * 0.000001) for e in relevant):
            raise ValueError('PREVIOUS_CLOSE_SOURCE_MISMATCH')
        bundle['source_times'] = {
            'quote_trade_time': timestamp(quote['exch_trade_time']).isoformat(),
            'quote_feed_time': timestamp(quote['exch_feed_time']).isoformat(),
            'previous_close_session': close_session,
            'preopen_event_time': preopen['source_event_time'],
            'preopen_coverage_state': capture['coverage_state'],
            'preopen_completed_at': capture['last_successful_poll_at'],
        }
        start = timestamp(f"{bundle['session_date']}T09:15:00+05:30")
        for interval, minutes in (('ONE_MINUTE', 1), ('FIVE_MINUTE', 5)):
            response = candle_fetch(symbol, interval, start, observed)
            if (response.get('source_state') != 'READY' or response.get('symbol') != symbol
                    or response.get('interval') != interval):
                raise ValueError(f'CANDLES_{minutes}M_UNAVAILABLE')
            candles = completed_candles(response['data'], minutes, observed)
            bundle['frames'].append({'timeframe': f'{minutes}m', 'candles': candles})
        bundle['source_state'] = 'READY'
        bundle['missing_inputs'] = validate_bundle(bundle)
        if bundle['missing_inputs']:
            bundle['source_state'] = 'INPUT_NOT_READY'
    except ValueError as exc:
        bundle['missing_inputs'].append(str(exc) if str(exc) in SAFE_FAILURE_REASONS else 'INVALID_SOURCE_INPUT')
        bundle['source_state'] = 'INPUT_NOT_READY'
    except Exception:
        bundle['missing_inputs'].append('SOURCE_ERROR')
        bundle['source_state'] = 'INPUT_NOT_READY'
    return bundle
