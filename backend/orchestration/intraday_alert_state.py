"""
Intraday alert repeat control (Stage 46G).

Maintains last_intraday_alert_state.json to suppress unchanged ticker repeats.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STATE_FILE = get_data_path('last_intraday_alert_state.json')

MATERIAL_PRICE_DELTA_PCT = 1.5
MATERIAL_VOLUME_DELTA = 0.35


def _log(msg: str) -> None:
    print(f'[INTRADAY_STATE] {msg}', flush=True)


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def load_intraday_alert_state() -> dict:
    if not STATE_FILE.is_file():
        return {'tickers': {}, 'updated_at': None}
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'tickers': {}, 'updated_at': None}
    except (OSError, json.JSONDecodeError):
        return {'tickers': {}, 'updated_at': None}


def save_intraday_alert_state(state: dict) -> None:
    state['updated_at'] = _now_iso()
    atomic_write_json(STATE_FILE, state)


def _reason_hash(ev: dict) -> str:
    payload = f"{ev.get('type')}|{ev.get('detail', '')[:80]}|{ev.get('setup_status', '')}"
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]


def _extract_move(ev: dict) -> float:
    signal = ev.get('signal') or {}
    if signal.get('change_percent') is not None:
        return abs(float(signal['change_percent']))
    detail = str(ev.get('detail') or '')
    import re
    m = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', detail)
    if m:
        return abs(float(m.group(1)))
    return 0.0


def _extract_volume(ev: dict) -> float:
    signal = ev.get('signal') or {}
    return float(signal.get('volume_ratio') or signal.get('participation') or ev.get('volume') or 0)


def classify_intraday_event(ev: dict) -> Tuple[str, Optional[str]]:
    """
    Returns (category, change_detail) where category is new|changed|suppressed.
    change_detail describes material change when changed.
    """
    ticker = str(ev.get('ticker') or '').upper()
    if not ticker:
        return 'new', None

    state = load_intraday_alert_state()
    tickers = state.get('tickers') or {}
    prev = tickers.get(ticker)
    move = _extract_move(ev)
    volume = _extract_volume(ev)
    regime = str(ev.get('regime') or '')
    reason_hash = _reason_hash(ev)

    if not prev:
        return 'new', None

    prev_move = float(prev.get('last_price_move') or 0)
    prev_vol = float(prev.get('last_volume') or 0)
    prev_regime = str(prev.get('last_regime') or '')
    prev_hash = str(prev.get('last_reason_hash') or '')

    changes: list[str] = []
    if move >= prev_move + MATERIAL_PRICE_DELTA_PCT:
        changes.append(f'price +{move:.1f}% (was {prev_move:.1f}%)')
    if volume >= prev_vol + MATERIAL_VOLUME_DELTA:
        changes.append(f'volume improved {prev_vol:.1f}x → {volume:.1f}x')
    if regime and prev_regime and regime != prev_regime:
        changes.append(f'regime {prev_regime} → {regime}')
    if reason_hash != prev_hash:
        changes.append('setup/news changed')

    setup_status = str(ev.get('setup_status') or '')
    prev_status = str(prev.get('setup_status') or '')
    if setup_status and prev_status and setup_status != prev_status:
        changes.append(f'status {prev_status} → {setup_status}')

    if changes:
        return 'changed', '; '.join(changes)

    _log(f'INTRADAY_ALERT_SUPPRESSED ticker={ticker} reason=no_material_change')
    return 'suppressed', None


def record_intraday_sent(ev: dict) -> None:
    ticker = str(ev.get('ticker') or '').upper()
    if not ticker:
        return
    state = load_intraday_alert_state()
    tickers = state.setdefault('tickers', {})
    tickers[ticker] = {
        'ticker': ticker,
        'last_sent_at': _now_iso(),
        'last_price_move': _extract_move(ev),
        'last_volume': _extract_volume(ev),
        'last_regime': str(ev.get('regime') or ''),
        'last_reason_hash': _reason_hash(ev),
        'setup_status': str(ev.get('setup_status') or ev.get('type') or ''),
    }
    save_intraday_alert_state(state)


def filter_intraday_events(events: list[dict], regime: str) -> dict[str, Any]:
    """
    Partition events into new/changed/suppressed lists for batch formatting.
    """
    new_events: list[dict] = []
    changed_events: list[dict] = []
    suppressed_count = 0

    for ev in events:
        ev = dict(ev)
        ev['regime'] = regime
        category, change_detail = classify_intraday_event(ev)
        if category == 'suppressed':
            suppressed_count += 1
            continue
        if category == 'changed':
            ev['change_detail'] = change_detail
            changed_events.append(ev)
        else:
            new_events.append(ev)

    return {
        'new': new_events,
        'changed': changed_events,
        'suppressed_count': suppressed_count,
    }


def format_intraday_batch(partition: dict, regime: str) -> str:
    lines = [f"<b>⚡ INTRADAY BATCH</b> <code>{regime.replace('_', ' ').upper()}</code>", '']

    if partition.get('new'):
        lines.append('<b>New:</b>')
        for ev in partition['new'][:3]:
            lines.append(f"• {ev.get('ticker') or ev.get('type', '?')} {ev.get('detail', '')[:70]}")
        lines.append('')

    if partition.get('changed'):
        lines.append('<b>Changed:</b>')
        for ev in partition['changed'][:3]:
            detail = ev.get('change_detail') or ev.get('detail', '')[:70]
            ticker = ev.get('ticker') or ev.get('type', '?')
            lines.append(f"• {ticker} {detail}")
        lines.append('')

    suppressed = int(partition.get('suppressed_count') or 0)
    lines.append(f'<b>Suppressed:</b> {suppressed} unchanged repeats hidden')

    if not partition.get('new') and not partition.get('changed'):
        lines.insert(1, '<i>No material intraday changes this cycle.</i>')

    return '\n'.join(lines)
