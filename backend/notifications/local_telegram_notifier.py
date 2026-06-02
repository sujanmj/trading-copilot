"""
Local-only Telegram send path (Stage 42A).

Send allowed only when LOCAL_ONLY/LOCAL_DEV_MODE, listener disabled,
DISABLE_TELEGRAM_SENDS=0, ENABLE_LOCAL_TELEGRAM_NOTIFICATIONS=1.
Does not use telegram_guard outbound (legacy bot remains disabled by default).
"""

from __future__ import annotations

import os
import re
from typing import Any

SAFETY_LINES = (
    'LOCAL ONLY',
    'Shadow analysis only',
    'Not trade execution',
)

ALLOWED_NOTIFICATION_TYPES = frozenset({
    'test',
    'daily_report_pack_summary',
    'tomorrow_watchlist_summary',
    'system_readiness_summary',
})

NOTIFICATION_TYPE_ALIASES = {
    'daily_pack': 'daily_report_pack_summary',
    'daily_report_pack': 'daily_report_pack_summary',
    'watchlist': 'tomorrow_watchlist_summary',
    'tomorrow_watchlist': 'tomorrow_watchlist_summary',
    'readiness': 'system_readiness_summary',
    'system_readiness': 'system_readiness_summary',
}

BLOCKED_TYPE_FRAGMENTS = (
    'trade',
    'order',
    'buy',
    'sell',
    'execution',
    'scanner',
    'ultra',
    'alert',
    'signal',
    'govt',
    'morning_brief',
    'outcome',
    'auto_',
)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _env_explicitly_off(name: str) -> bool:
    val = os.environ.get(name)
    if val is None:
        return False
    return str(val).strip().lower() in ('0', 'false', 'no', 'off')


def _local_mode_active() -> bool:
    try:
        from backend.utils.config import IS_LOCAL_DEV, LOCAL_ONLY

        if LOCAL_ONLY or IS_LOCAL_DEV:
            return True
    except Exception:
        pass
    return _env_truthy('LOCAL_ONLY') or _env_truthy('LOCAL_DEV_MODE')


def _listener_disabled() -> bool:
    if _env_truthy('DISABLE_TELEGRAM_LISTENER'):
        return True
    try:
        from backend.utils.config import DISABLE_TELEGRAM_LISTENER

        return bool(DISABLE_TELEGRAM_LISTENER)
    except Exception:
        return False


def _sends_gate_open() -> bool:
    if _env_explicitly_off('DISABLE_TELEGRAM_SENDS'):
        return True
    try:
        from backend.utils.config import DISABLE_TELEGRAM_SENDS

        return not DISABLE_TELEGRAM_SENDS
    except Exception:
        return False


def _local_notifications_enabled() -> bool:
    return _env_truthy('ENABLE_LOCAL_TELEGRAM_NOTIFICATIONS')


def _credentials_configured() -> bool:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    return bool(token and chat_id)


def _ensure_env_loaded() -> None:
    try:
        from backend.utils.config import load_env

        load_env()
    except Exception:
        pass


def _normalize_notification_type(notification_type: str) -> str:
    raw = (notification_type or 'test').strip().lower().replace('-', '_').replace(' ', '_')
    return NOTIFICATION_TYPE_ALIASES.get(raw, raw)


def _is_blocked_notification_type(notification_type: str) -> bool:
    normalized = _normalize_notification_type(notification_type)
    if normalized in ALLOWED_NOTIFICATION_TYPES:
        return False
    lowered = normalized
    return any(fragment in lowered for fragment in BLOCKED_TYPE_FRAGMENTS)


def _refusal(reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'ok': False,
        'sent': False,
        'skipped': True,
        'reason': reason,
    }
    payload.update(extra)
    return payload


def _apply_safety_footer(text: str) -> str:
    body = (text or '').strip()
    for line in SAFETY_LINES:
        if line not in body:
            body = f'{body}\n\n{line}' if body else line
    return body


def telegram_notifications_enabled() -> dict[str, Any]:
    """Return gate status for local Telegram send-only (no secrets)."""
    _ensure_env_loaded()
    local_mode = _local_mode_active()
    listener_disabled = _listener_disabled()
    sends_gate = _sends_gate_open()
    local_flag = _local_notifications_enabled()
    creds = _credentials_configured()

    reasons: list[str] = []
    if not local_mode:
        reasons.append('local_mode_inactive')
    if not listener_disabled:
        reasons.append('telegram_listener_not_disabled')
    if not sends_gate:
        reasons.append('telegram_sends_disabled')
    if not local_flag:
        reasons.append('local_telegram_notifications_disabled')

    if local_mode and listener_disabled and sends_gate and local_flag and not creds:
        reasons.append('missing_credentials')

    enabled = local_mode and listener_disabled and sends_gate and local_flag and creds

    return {
        'enabled': enabled,
        'local_mode': local_mode,
        'listener_disabled': listener_disabled,
        'sends_allowed_flag': sends_gate,
        'local_notifications_flag': local_flag,
        'credentials_configured': creds,
        'reasons': reasons,
        'reason': ';'.join(reasons) if reasons else '',
    }


def _validate_send_request(notification_type: str) -> dict[str, Any] | None:
    if not _local_mode_active():
        return _refusal('local_mode_required')

    normalized = _normalize_notification_type(notification_type)
    if _is_blocked_notification_type(notification_type):
        return _refusal('blocked_notification_type', notification_type=normalized)

    if normalized not in ALLOWED_NOTIFICATION_TYPES:
        return _refusal('disallowed_notification_type', notification_type=normalized)

    if not _listener_disabled():
        return _refusal('telegram_listener_must_be_disabled')

    if not _sends_gate_open():
        return _refusal('telegram_sends_disabled')

    if not _local_notifications_enabled():
        return _refusal('local_telegram_notifications_disabled')

    return None


def send_local_telegram_message(text: str, notification_type: str = 'test') -> dict[str, Any]:
    """Send one local-only Telegram message when all safety gates pass."""
    _ensure_env_loaded()
    refusal = _validate_send_request(notification_type)
    if refusal is not None:
        return refusal

    if not _credentials_configured():
        return _refusal('missing_credentials')

    message = _apply_safety_footer(text)
    if len(message) > 4000:
        message = message[:3950] + '\n\n... (truncated)'

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    api_url = f'https://api.telegram.org/bot{token}/sendMessage'

    try:
        import requests
    except ImportError:
        return _refusal('requests_not_installed')

    try:
        response = requests.post(
            api_url,
            json={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            timeout=10,
        )
    except requests.Timeout:
        return {'ok': False, 'sent': False, 'skipped': False, 'reason': 'timeout'}
    except Exception as exc:
        return {'ok': False, 'sent': False, 'skipped': False, 'reason': str(exc)[:120]}

    if response.status_code == 200:
        return {
            'ok': True,
            'sent': True,
            'skipped': False,
            'reason': '',
            'notification_type': _normalize_notification_type(notification_type),
        }

    try:
        err = response.json().get('description', 'unknown')
    except Exception:
        err = 'unknown'
    return {
        'ok': False,
        'sent': False,
        'skipped': False,
        'reason': f'http_{response.status_code}:{err[:80]}',
    }


def format_daily_pack_telegram_summary(report: dict) -> str:
    """Compact daily report pack summary for local Telegram."""
    summary = report.get('summary') if isinstance(report.get('summary'), dict) else {}
    tw = report.get('tomorrow_watchlist') if isinstance(report.get('tomorrow_watchlist'), dict) else {}
    market_mode = str(report.get('market_mode') or tw.get('market_mode') or 'unknown')
    generated = str(report.get('generated_at') or '')[:19]
    watch = int(tw.get('watch') or summary.get('watch') or 0)
    avoid = int(tw.get('avoid') or summary.get('avoid') or 0)
    no_decision = int(tw.get('no_decision') or summary.get('no_decision') or 0)
    risk_count = len(report.get('risk_notes') or [])
    sections = report.get('sections') if isinstance(report.get('sections'), dict) else {}
    section_names = ', '.join(sorted(sections.keys())[:8]) if sections else 'n/a'

    lines = [
        '<b>Daily Report Pack (local)</b>',
        f'Mode: {market_mode}',
        f'Generated: {generated or "n/a"}',
        f'Watchlist: watch={watch} avoid={avoid} no_decision={no_decision}',
        f'Risk notes: {risk_count}',
        f'Sections: {section_names}',
    ]
    return '\n'.join(lines)


def format_watchlist_telegram_summary(report: dict) -> str:
    """Compact tomorrow watchlist summary for local Telegram."""
    summary = report.get('summary') if isinstance(report.get('summary'), dict) else {}
    market_mode = str(report.get('market_mode') or 'unknown')
    generated = str(report.get('generated_at') or '')[:19]
    title = str(summary.get('list_title') or 'Tomorrow Watchlist')
    watch = int(summary.get('watch') or 0)
    avoid = int(summary.get('avoid') or 0)
    no_decision = int(summary.get('no_decision') or 0)
    buy_candidates = int(summary.get('buy_candidates') or 0)

    top = report.get('top_watchlist') if isinstance(report.get('top_watchlist'), list) else []
    tickers: list[str] = []
    for row in top[:5]:
        if isinstance(row, dict):
            ticker = str(row.get('ticker') or '').strip()
            if ticker:
                tickers.append(ticker)
    top_line = ', '.join(tickers) if tickers else 'none'

    lines = [
        f'<b>{title} (local)</b>',
        f'Mode: {market_mode}',
        f'Generated: {generated or "n/a"}',
        f'Counts: watch={watch} avoid={avoid} no_decision={no_decision} buy_candidates={buy_candidates}',
        f'Top watch: {top_line}',
    ]
    risk_notes = report.get('risk_notes') if isinstance(report.get('risk_notes'), list) else []
    if risk_notes:
        first = str(risk_notes[0])[:120]
        lines.append(f'Risk note: {first}')
    return '\n'.join(lines)
