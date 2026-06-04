"""
Operational alert severity routing.

Separates full OPS telemetry from high-signal Telegram delivery.
Watchdog and runtime systems log everything; Telegram receives CRITICAL/HIGH only
(with market-period-aware thresholds and cooldowns).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

OPERATIONAL_ALERTS_FILE = DATA_DIR / 'operational_alerts.json'

# Severity tiers (highest → lowest rank for comparison)
CRITICAL = 'CRITICAL'
HIGH = 'HIGH'
MEDIUM = 'MEDIUM'
LOW = 'LOW'
SILENT = 'SILENT'

SEVERITY_RANK = {
    CRITICAL: 5,
    HIGH: 4,
    MEDIUM: 3,
    LOW: 2,
    SILENT: 1,
}

# Minimum severity required to reach Telegram, by IST market period
TELEGRAM_MIN_BY_PERIOD = {
    'market': HIGH,
    'pre_market': HIGH,
    'after_hours': CRITICAL,
    'night': CRITICAL,
    'weekend': CRITICAL,
}

# Cooldown seconds before the same alert code can Telegram again
SEVERITY_COOLDOWNS_SEC = {
    CRITICAL: int(os.environ.get('ALERT_COOLDOWN_CRITICAL', '3600')),
    HIGH: int(os.environ.get('ALERT_COOLDOWN_HIGH', '14400')),
    MEDIUM: int(os.environ.get('ALERT_COOLDOWN_MEDIUM', '28800')),
}

CONTRADICTION_TELEGRAM_WARN = float(os.environ.get('CONTRADICTION_TELEGRAM_WARN', '0.85'))
CONTRADICTION_TELEGRAM_CRITICAL = float(os.environ.get('CONTRADICTION_TELEGRAM_CRITICAL', '0.95'))
CONTRADICTION_REFRESH_OVERRIDE = float(os.environ.get('CONTRADICTION_REFRESH_OVERRIDE', '0.55'))

VOLATILITY_TELEGRAM_WARN = float(os.environ.get('VOLATILITY_TELEGRAM_WARN', '0.80'))
VOLATILITY_TELEGRAM_CRITICAL = float(os.environ.get('VOLATILITY_TELEGRAM_CRITICAL', '0.90'))


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _load_state() -> dict:
    default = {
        'date': _today(),
        'events': [],
        'telegram_last_sent': {},
        'escalation_track': {},
        'counters': {'telegram_sent': 0, 'telegram_suppressed': 0, 'ops_logged': 0},
    }
    if not OPERATIONAL_ALERTS_FILE.exists():
        return default
    try:
        with open(OPERATIONAL_ALERTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        if data.get('date') != _today():
            data['events'] = []
            data['date'] = _today()
        for key, val in default.items():
            data.setdefault(key, val if not isinstance(val, dict) else dict(val))
        return data
    except Exception:
        return default


def _save_state(data: dict):
    atomic_write_json(OPERATIONAL_ALERTS_FILE, data)


def classify_contradiction(score: float) -> str:
    if score >= CONTRADICTION_TELEGRAM_CRITICAL:
        return CRITICAL
    if score >= CONTRADICTION_TELEGRAM_WARN:
        return HIGH
    if score >= 0.65:
        return MEDIUM
    if score >= 0.45:
        return LOW
    return SILENT


def classify_volatility(vol: float) -> str:
    if vol >= VOLATILITY_TELEGRAM_CRITICAL:
        return CRITICAL
    if vol >= VOLATILITY_TELEGRAM_WARN:
        return HIGH
    if vol >= 0.68:
        return MEDIUM
    return LOW


def emergency_requires_refresh(state: dict) -> Tuple[bool, str]:
    """
    Watchdog refresh override (unchanged policy) — may force refresh during night mode.
    Separate from Telegram severity.
    """
    try:
        disagree = float(state.get('disagreement_score') or 0)
        vol = float(state.get('volatility_index') or 0)
        if disagree >= CONTRADICTION_REFRESH_OVERRIDE:
            return True, f'contradiction_spike={disagree:.2f}'
        if vol >= 0.68:
            return True, f'volatility_spike={vol:.2f}'

        govt_path = DATA_DIR / 'govt_intelligence.json'
        if govt_path.exists():
            with open(govt_path, 'r', encoding='utf-8') as f:
                govt = json.load(f) or {}
            for item in (govt.get('high_impact_items') or [])[:5]:
                if float(item.get('impact_score') or 0) >= 8.5:
                    return True, 'govt_high_impact'

        scanner_path = DATA_DIR / 'scanner_data.json'
        if scanner_path.exists():
            with open(scanner_path, 'r', encoding='utf-8') as f:
                scanner = json.load(f) or {}
            for sig in (scanner.get('top_signals') or [])[:6]:
                if str(sig.get('strength', '')).upper() == 'ULTRA' and abs(float(sig.get('change_percent') or 0)) >= 5:
                    return True, f"scanner_ultra:{sig.get('ticker')}"
    except Exception:
        pass
    return False, ''


def classify_emergency_severity(reason: str, state: Optional[dict] = None) -> str:
    """Map emergency reason string to alert severity for Telegram routing."""
    state = state or {}
    if reason.startswith('contradiction_spike='):
        try:
            score = float(reason.split('=', 1)[1])
        except ValueError:
            score = float(state.get('disagreement_score') or 0)
        return classify_contradiction(score)
    if reason.startswith('volatility_spike='):
        try:
            vol = float(reason.split('=', 1)[1])
        except ValueError:
            vol = float(state.get('volatility_index') or 0)
        return classify_volatility(vol)
    if reason == 'govt_high_impact':
        return HIGH
    if reason.startswith('scanner_ultra:'):
        return HIGH
    return MEDIUM


def _meets_period_threshold(severity: str, period: str) -> bool:
    minimum = TELEGRAM_MIN_BY_PERIOD.get(period, CRITICAL)
    return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(minimum, 5)


def _check_cooldown(state: dict, code: str, severity: str, meta: Optional[dict]) -> Tuple[bool, str]:
    key = f'{code}:{severity}'
    last = (state.get('telegram_last_sent') or {}).get(key)
    if not last:
        return True, ''

    elapsed = datetime.now().timestamp() - float(last)
    need = SEVERITY_COOLDOWNS_SEC.get(severity, 14400)
    if elapsed >= need:
        return True, ''

    # Escalation: allow if metric worsened materially
    track = (state.get('escalation_track') or {}).get(code) or {}
    if meta:
        for field in ('contradiction_score', 'volatility', 'age_hours', 'recovery_failures'):
            prev = track.get(field)
            cur = meta.get(field)
            if prev is not None and cur is not None:
                try:
                    if float(cur) >= float(prev) + 0.12:
                        return True, 'escalation_worsening'
                except (TypeError, ValueError):
                    pass
    return False, f'cooldown {int(need - elapsed)}s'


def record_operational_event(
    code: str,
    severity: str,
    message: str,
    *,
    meta: Optional[dict] = None,
    telegram_decision: Optional[str] = None,
) -> dict:
    """Always persist for OPS — regardless of Telegram routing."""
    state = _load_state()
    entry = {
        'time': datetime.now().isoformat(),
        'code': code,
        'severity': severity,
        'message': message[:500],
        'meta': meta or {},
        'telegram': telegram_decision or 'not_evaluated',
    }
    state.setdefault('events', []).insert(0, entry)
    state['events'] = state['events'][:120]
    state.setdefault('counters', {})['ops_logged'] = int(state['counters'].get('ops_logged', 0)) + 1

    if meta:
        track = state.setdefault('escalation_track', {})
        prev = track.get(code) or {}
        merged = dict(prev)
        merged.update({k: v for k, v in meta.items() if v is not None})
        track[code] = merged

    _save_state(state)
    return entry


def route_operational_alert(
    code: str,
    severity: str,
    message: str,
    *,
    period: str = 'market',
    meta: Optional[dict] = None,
) -> dict:
    """
    Decide Telegram delivery. Always logs to OPS journal first.
    Returns decision dict: {telegram, reason, severity, code}.
    """
    state = _load_state()
    decision = {'telegram': False, 'reason': 'silent', 'severity': severity, 'code': code}

    if SEVERITY_RANK.get(severity, 0) <= SEVERITY_RANK[SILENT]:
        decision['reason'] = 'silent_severity'
        record_operational_event(code, severity, message, meta=meta, telegram_decision=decision['reason'])
        return decision

    if not _meets_period_threshold(severity, period):
        decision['reason'] = f'below_period_minimum_{period}'
        state.setdefault('counters', {})['telegram_suppressed'] = int(state['counters'].get('telegram_suppressed', 0)) + 1
        _save_state(state)
        record_operational_event(code, severity, message, meta=meta, telegram_decision=decision['reason'])
        _log('ALERT SUPPRESSED', f'{code} {severity} — {decision["reason"]}')
        return decision

    ok, cooldown_reason = _check_cooldown(state, code, severity, meta)
    if not ok:
        decision['reason'] = cooldown_reason
        state.setdefault('counters', {})['telegram_suppressed'] = int(state['counters'].get('telegram_suppressed', 0)) + 1
        _save_state(state)
        record_operational_event(code, severity, message, meta=meta, telegram_decision=decision['reason'])
        _log('ALERT SUPPRESSED', f'{code} cooldown')
        return decision

    decision['telegram'] = True
    decision['reason'] = cooldown_reason or 'routed'
    record_operational_event(code, severity, message, meta=meta, telegram_decision='sent')
    return decision


def send_operational_telegram(message: str, *, severity: str, code: str) -> dict:
    from backend.utils.telegram_guard import is_telegram_send_enabled, telegram_send_skipped
    if not is_telegram_send_enabled():
        return telegram_send_skipped('alert_routing.send_operational_telegram')

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return {'ok': False, 'sent': False, 'skipped': False, 'reason': 'missing_credentials'}

    icons = {CRITICAL: '🚨', HIGH: '⚠️', MEDIUM: 'ℹ️', LOW: '🔧', SILENT: '·'}
    icon = icons.get(severity, '⚠️')
    text = f"{icon} <b>{severity}</b> · {code.replace('_', ' ').upper()}\n{message}"

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
        }, timeout=10)
        if resp.status_code != 200:
            _log('ALERT ROUTER', f'Telegram HTTP {resp.status_code}')
            return {'ok': False, 'sent': False, 'skipped': False, 'reason': f'http_{resp.status_code}'}
    except Exception as e:
        _log('ALERT ROUTER', f'Telegram failed: {e}')
        return {'ok': False, 'sent': False, 'skipped': False, 'reason': str(e)[:120]}

    state = _load_state()
    key = f'{code}:{severity}'
    state.setdefault('telegram_last_sent', {})[key] = datetime.now().timestamp()
    state.setdefault('counters', {})['telegram_sent'] = int(state['counters'].get('telegram_sent', 0)) + 1
    _save_state(state)
    try:
        from backend.metrics.execution_metrics import record_reliability_event
        record_reliability_event('telegram_sent')
    except Exception:
        pass
    return {'ok': True, 'sent': True, 'skipped': False, 'reason': ''}


def emit_operational_alert(
    code: str,
    severity: str,
    message: str,
    *,
    period: str = 'market',
    meta: Optional[dict] = None,
) -> dict:
    """Route + optionally send Telegram. OPS always receives the event."""
    try:
        from backend.orchestration.watchdog_throttle import (
            can_send_emergency_telegram,
            can_send_stale_telegram,
            record_emergency_telegram_sent,
            record_stale_telegram_sent,
        )
        if code == 'watchdog_stale_unrecovered' and not can_send_stale_telegram():
            record_operational_event(
                code, severity, message, meta=meta, telegram_decision='watchdog_throttle_stale',
            )
            return {'telegram': False, 'reason': 'watchdog_throttle_stale', 'severity': severity, 'code': code}
        if code == 'watchdog_emergency' and not can_send_emergency_telegram():
            record_operational_event(
                code, severity, message, meta=meta, telegram_decision='watchdog_throttle_emergency',
            )
            return {'telegram': False, 'reason': 'watchdog_throttle_emergency', 'severity': severity, 'code': code}
    except Exception:
        pass

    decision = route_operational_alert(code, severity, message, period=period, meta=meta)
    if decision.get('telegram'):
        send_result = send_operational_telegram(message, severity=severity, code=code)
        if send_result.get('sent'):
            try:
                from backend.orchestration.watchdog_throttle import (
                    record_emergency_telegram_sent,
                    record_stale_telegram_sent,
                )
                if code == 'watchdog_stale_unrecovered':
                    record_stale_telegram_sent()
                elif code == 'watchdog_emergency':
                    record_emergency_telegram_sent()
            except Exception:
                pass
        if send_result.get('skipped'):
            decision['telegram'] = False
            decision['reason'] = send_result.get('reason', 'telegram_disabled')
        elif not send_result.get('sent'):
            decision['telegram'] = False
            decision['reason'] = send_result.get('reason', 'send_failed')
    return decision


def get_operational_alert_summary(limit: int = 20) -> dict:
    state = _load_state()
    events = state.get('events') or []
    return {
        'date': state.get('date'),
        'counters': state.get('counters') or {},
        'telegram_policy': {
            'min_by_period': TELEGRAM_MIN_BY_PERIOD,
            'contradiction_warn': CONTRADICTION_TELEGRAM_WARN,
            'contradiction_critical': CONTRADICTION_TELEGRAM_CRITICAL,
            'cooldowns_sec': SEVERITY_COOLDOWNS_SEC,
        },
        'recent_events': events[:limit],
        'recent_suppressed': [
            e for e in events if str(e.get('telegram', '')).startswith(('below_', 'cooldown', 'silent'))
        ][:12],
    }
