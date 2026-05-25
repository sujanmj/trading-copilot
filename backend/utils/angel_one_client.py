"""
Angel One SmartAPI — shared session for collectors and prediction logger.
Credentials from config/keys.env: ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_SECRET
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

import pyotp
import requests

from backend.utils.config import get_env

_angel_session = None
_instrument_map: Dict[str, str] = {}
_configured: Optional[bool] = None


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
        obj = SmartConnect(api_key=get_env('ANGEL_API_KEY'))
        live_totp = pyotp.TOTP(get_env('ANGEL_TOTP_SECRET')).now()
        data = obj.generateSession(get_env('ANGEL_CLIENT_ID'), get_env('ANGEL_PIN'), live_totp)
        if data.get('status') is False:
            _log('DATA SOURCE FAILOVER', f"Angel login failed: {data.get('message')}")
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
        _log('DATA SOURCE FAILOVER', f'Angel initialization error: {e}')
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
