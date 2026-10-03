"""
Angel One SmartAPI — shared session for collectors and prediction logger.
Credentials from config/keys.env: ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_SECRET
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import pyotp
import requests

from backend.utils.config import get_env

_angel_session = None
_instrument_map: Dict[str, str] = {}
_configured: Optional[bool] = None
_source_lock = threading.Lock()
_initialization_lock = threading.Lock()
_source_initialization_thread = None
_source_initialization_done = threading.Event()
SOURCE_TIMEOUT_SECONDS = 7
SOURCE_INITIALIZATION_WAIT_SECONDS = 30
MAX_SOURCE_SYMBOLS = 12
MAX_CANDLE_DAYS = 10


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def is_configured() -> bool:
    global _configured
    if _configured is not None:
        return _configured
    _configured = all([
        get_env('ANGEL_API_KEY'),
        get_env('ANGEL_CLIENT_ID'),
        get_env('ANGEL_PIN'),
        get_env('ANGEL_TOTP_SECRET'),
    ])
    return _configured


def _initialize() -> bool:
    with _initialization_lock:
        return _initialize_unlocked()


def _initialize_unlocked() -> bool:
    global _angel_session, _instrument_map
    if _angel_session is not None:
        return True
    if not is_configured():
        _log('DATA SOURCE FAILOVER', 'Angel One credentials missing — using fallback sources')
        return False

    try:
        from SmartApi import SmartConnect
    except ImportError:
        _log('DATA SOURCE FAILOVER', 'SmartApi package not installed')
        return False

    try:
        _log('ANGEL ONE', 'Authenticating (Auto-TOTP)...')
        obj = SmartConnect(api_key=get_env('ANGEL_API_KEY'), timeout=SOURCE_TIMEOUT_SECONDS)
        live_totp = pyotp.TOTP(get_env('ANGEL_TOTP_SECRET')).now()
        data = obj.generateSession(get_env('ANGEL_CLIENT_ID'), get_env('ANGEL_PIN'), live_totp)
        if data.get('status') is False:
            _log('DATA SOURCE FAILOVER', 'Angel login failed')
            return False

        _angel_session = obj
        _log('ANGEL ONE', 'Authenticated successfully')

        if not _instrument_map:
            url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
            response = requests.get(url, timeout=20).json()
            for item in response:
                if item.get('exch_seg') == 'NSE' and '-EQ' in item.get('symbol', ''):
                    clean_sym = item['symbol'].replace('-EQ', '')
                    _instrument_map[clean_sym] = item['token']
            _log('ANGEL ONE', f'Loaded {len(_instrument_map)} NSE instruments')
        return True
    except Exception as e:
        _log('DATA SOURCE FAILOVER', 'Angel initialization failed')
        return False


def _reset_session():
    global _angel_session
    _angel_session = None


def fetch_ltp(symbol: str) -> Tuple[Optional[float], str]:
    """
    Fetch LTP for NSE equity symbol.
    Returns (price or None, source_tag).
    """
    global _angel_session, _instrument_map
    clean = str(symbol or '').strip().upper().replace('.NS', '').replace('.BO', '')
    if not clean:
        return None, 'invalid_symbol'

    if not _initialize():
        return None, 'angel_unavailable'

    token = _instrument_map.get(clean)
    if not token:
        return None, 'token_not_found'

    try:
        res = _angel_session.ltpData('NSE', f'{clean}-EQ', token)
        if res and res.get('status') and res.get('data'):
            return float(res['data']['ltp']), 'angel_one'
        if res and res.get('message') == 'Invalid Token':
            _log('ANGEL ONE', 'Session expired — re-authenticating')
            _reset_session()
            if _initialize():
                res = _angel_session.ltpData('NSE', f'{clean}-EQ', token)
                if res and res.get('status') and res.get('data'):
                    return float(res['data']['ltp']), 'angel_one'
    except Exception as e:
        _log('DATA SOURCE FAILOVER', f'Angel LTP error {clean}: {e}')

    return None, 'angel_failed'


def get_status() -> dict:
    return {
        'configured': is_configured(),
        'connected': _angel_session is not None,
        'instruments_loaded': len(_instrument_map),
    }


def _source_failure(reason):
    return {'source_state': 'SOURCE_NOT_READY', 'reason': reason, 'data': None}


def _initialize_sources_bounded():
    """Bound caller latency even for the SDK's import-time public-IP lookup.

The SDK performs an unbounded lookup on first import. Only one daemon may
initialize; timing out never creates more workers. Existing fetch_ltp keeps
its synchronous behavior. No provider request is run after a failed wait.
"""
    global _source_initialization_thread
    if _angel_session is not None:
        return True
    if not is_configured():
        return False
    if _source_initialization_thread is None or not _source_initialization_thread.is_alive():
        _source_initialization_done.clear()
        def initialize():
            try:
                _initialize()
            finally:
                _source_initialization_done.set()
        _source_initialization_thread = threading.Thread(target=initialize, name='Angel-Source-Init', daemon=True)
        _source_initialization_thread.start()
    if not _source_initialization_done.wait(SOURCE_INITIALIZATION_WAIT_SECONDS):
        return False
    return _angel_session is not None


def fetch_full_quotes(symbols: list[str]) -> dict:
    """At most twelve NSE FULL quotes, using the existing shared session.

Keep exchange timestamps verbatim. No retries or persistence; a subsequent
runtime request may try again. This helper never invokes trading APIs.
"""
    from backend.collectors.nse_preopen_iep import number
    if (not isinstance(symbols, list) or not 1 <= len(symbols) <= MAX_SOURCE_SYMBOLS
            or any(not isinstance(s, str) or not s or s != s.strip().upper() for s in symbols)
            or len(set(symbols)) != len(symbols)):
        return _source_failure('INVALID_SYMBOL_BATCH')
    with _source_lock:
        if not _initialize_sources_bounded():
            return _source_failure('ANGEL_UNAVAILABLE')
        tokens = {s: _instrument_map.get(s) for s in symbols}
        if not all(tokens.values()):
            return _source_failure('TOKEN_NOT_FOUND')
        try:
            response = _angel_session.getMarketData('FULL', {'NSE': list(tokens.values())})
            if not isinstance(response, dict) or not response.get('status'):
                return _source_failure('ANGEL_QUOTE_FAILED')
            mapped = {}
            for row in response.get('data', {}).get('fetched', []):
                symbol = row.get('tradingSymbol', '').removesuffix('-EQ')
                if (symbol not in tokens or str(row.get('symbolToken')) != str(tokens[symbol])
                        or row.get('exchange') != 'NSE' or symbol in mapped):
                    return _source_failure('QUOTE_IDENTITY_MISMATCH')
                mapped[symbol] = {
                    'symbol': symbol, 'source': 'ANGEL_FULL',
                    'ltp': number(row['ltp'], positive=True),
                    'previous_close': number(row['close'], positive=True),
                    'exch_trade_time': row['exchTradeTime'],
                    'exch_feed_time': row['exchFeedTime'],
                }
            if set(mapped) != set(symbols):
                return _source_failure('QUOTE_BATCH_INCOMPLETE')
            return {'source_state': 'READY', 'reason': None, 'data': mapped}
        except Exception:
            return _source_failure('ANGEL_QUOTE_ERROR')


def fetch_source_candles(symbol: str, interval: str, start: datetime, end: datetime) -> dict:
    """Bounded raw provider rows; the runtime source enforces candle cutoffs."""
    from backend.collectors.nse_preopen_iep import timestamp
    if interval not in {'ONE_MINUTE', 'FIVE_MINUTE', 'ONE_DAY'}:
        return _source_failure('INVALID_CANDLE_INTERVAL')
    try:
        start, end = timestamp(start), timestamp(end)
        if not isinstance(symbol, str) or not symbol or symbol != symbol.strip().upper():
            raise ValueError()
        if not timedelta(0) < end - start <= timedelta(days=MAX_CANDLE_DAYS):
            raise ValueError()
    except (ValueError, TypeError):
        return _source_failure('INVALID_CANDLE_WINDOW')
    with _source_lock:
        if not _initialize_sources_bounded():
            return _source_failure('ANGEL_UNAVAILABLE')
        token = _instrument_map.get(symbol)
        if not token:
            return _source_failure('TOKEN_NOT_FOUND')
        try:
            response = _angel_session.getCandleData({
                'exchange': 'NSE', 'symboltoken': token, 'interval': interval,
                'fromdate': start.strftime('%Y-%m-%d %H:%M'),
                'todate': end.strftime('%Y-%m-%d %H:%M'),
            })
            if not isinstance(response, dict) or not response.get('status') or not isinstance(response.get('data'), list):
                return _source_failure('ANGEL_CANDLES_FAILED')
            return {'source_state': 'READY', 'reason': None, 'data': response['data'],
                    'symbol': symbol, 'interval': interval}
        except Exception:
            return _source_failure('ANGEL_CANDLES_ERROR')
