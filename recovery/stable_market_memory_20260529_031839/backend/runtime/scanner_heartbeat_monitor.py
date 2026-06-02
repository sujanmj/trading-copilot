"""
Scanner heartbeat monitor — detect scheduler / market-hours / lock stalls.

Surfaces in runtime_state: Scanner healthy | Scanner stalled: Xh
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
SCANNER_FILE = DATA_DIR / 'scanner_data.json'
DEFAULT_STALL_MINUTES = 45


def _scanner_file_age_minutes() -> Optional[int]:
    if not SCANNER_FILE.exists():
        return None
    try:
        age_sec = time.time() - SCANNER_FILE.stat().st_mtime
        return max(0, int(age_sec / 60))
    except Exception:
        return None


def _heartbeat_age_minutes() -> Optional[int]:
    try:
        from backend.runtime.snapshot_freshness_monitor import _load_heartbeats
        hb = (_load_heartbeats().get('sources') or {}).get('scanner') or {}
        ts = hb.get('at_unix')
        if ts is None:
            return None
        return max(0, int((time.time() - float(ts)) / 60))
    except Exception:
        return None


def evaluate_scanner_health(*, stall_minutes: int = DEFAULT_STALL_MINUTES) -> Dict[str, Any]:
    """Assess scanner pipeline — file mtime + collector heartbeat."""
    file_age = _scanner_file_age_minutes()
    hb_age = _heartbeat_age_minutes()
    age = file_age
    if hb_age is not None:
        age = hb_age if age is None else min(age, hb_age)

    expect_quiet = False
    market_hours = False
    try:
        from backend.utils.market_hours import get_operational_status
        op = get_operational_status()
        expect_quiet = bool(op.get('expect_quiet_collectors'))
        market_hours = bool(op.get('market_hours'))
    except Exception:
        pass

    if age is None:
        if expect_quiet:
            return {
                'healthy': True,
                'stalled': False,
                'display': 'Scanner: idle (after-hours)',
                'age_minutes': None,
                'stall_minutes': stall_minutes,
                'expect_quiet': True,
            }
        return {
            'healthy': False,
            'stalled': True,
            'display': 'Scanner stalled: no data',
            'age_minutes': None,
            'stall_minutes': stall_minutes,
            'reason': 'no_scanner_file',
        }

    effective_stall = stall_minutes
    if expect_quiet and not market_hours:
        effective_stall = max(stall_minutes, 180)

    stalled = age >= effective_stall
    if stalled:
        if age >= 60:
            display = f'Scanner stalled: {age // 60}h'
        else:
            display = f'Scanner stalled: {age}m'
    else:
        display = 'Scanner: healthy'

    lock_hint = ''
    try:
        from backend.utils.process_lock import lock_status
        sc = (lock_status() or {}).get('stock_scanner') or {}
        if sc.get('valid') and sc.get('alive'):
            lock_hint = 'lock_held'
    except Exception:
        pass

    return {
        'healthy': not stalled,
        'stalled': stalled,
        'display': display,
        'age_minutes': age,
        'file_age_minutes': file_age,
        'heartbeat_age_minutes': hb_age,
        'stall_minutes': effective_stall,
        'expect_quiet': expect_quiet,
        'market_hours': market_hours,
        'lock_hint': lock_hint,
        'scanner_file_exists': SCANNER_FILE.exists(),
        'checked_at': datetime.now(IST).isoformat(),
    }
