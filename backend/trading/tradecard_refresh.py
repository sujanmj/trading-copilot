"""
Lightweight on-demand tradecard market refresh — Stage 50V.

Refreshes quote/prices + scanner only during INDIA_MARKET_HOURS.
Never triggers full AI/news/broker/govt refresh on /tradecard.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from backend.storage.data_paths import get_data_path
from backend.telegram.india_mode_lock import is_live_market_hours_phase

QUOTE_FILE = 'latest_market_data.json'
SCANNER_FILE = 'scanner_data.json'

# chat_id -> monotonic timestamp of last refresh attempt
_last_refresh_by_chat: dict[str, float] = {}

LIGHTWEIGHT_SCOPES: tuple[str, ...] = ('prices', 'scanner')
FORBIDDEN_HEAVY_SCOPES: frozenset[str] = frozenset({
    'news', 'brokers', 'govt', 'intelligence', 'closed-market', 'all', 'runtime',
})


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default)).strip()))
    except ValueError:
        return default


def force_refresh_enabled() -> bool:
    return os.environ.get('TRADECARD_FORCE_REFRESH', '').strip().lower() in ('1', 'true', 'yes', 'on')


def cooldown_seconds() -> int:
    return _env_int('TRADECARD_REFRESH_COOLDOWN_SECONDS', 30)


def max_cache_age_seconds() -> int:
    return _env_int('TRADECARD_MAX_CACHE_AGE_SECONDS', 60)


def _file_age_seconds(filename: str) -> int | None:
    path = get_data_path(filename)
    if not path.is_file():
        return None
    try:
        return max(0, int(datetime.now(timezone.utc).timestamp() - path.stat().st_mtime))
    except OSError:
        return None


def _format_age_short(seconds: int) -> str:
    if seconds < 60:
        return f'{seconds}s'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes}m'
    return f'{minutes // 60}h'


def format_freshness_line(meta: dict[str, Any] | None) -> str:
    """Human-readable freshness line for tradecard Telegram output."""
    if not isinstance(meta, dict):
        return 'Freshness: cache age unknown'

    if meta.get('cooldown_reused'):
        age = int(meta.get('cooldown_age_seconds') or 0)
        return f'Freshness: reused {age}s cache due cooldown'

    if meta.get('refresh_failed'):
        ages = [
            int(meta[k])
            for k in ('quote_age_seconds', 'scanner_age_seconds')
            if meta.get(k) is not None
        ]
        cache_age = max(ages) if ages else 0
        return f'Freshness: refresh failed, using cache {_format_age_short(cache_age)} old'

    parts: list[str] = []
    if meta.get('quote_refreshed_now'):
        parts.append('quote refreshed now')
    elif meta.get('quote_age_seconds') is not None:
        parts.append(f"quote {_format_age_short(int(meta['quote_age_seconds']))} old")

    if meta.get('scanner_refreshed_now'):
        parts.append('scanner refreshed now')
    elif meta.get('scanner_age_seconds') is not None:
        parts.append(f"scanner {_format_age_short(int(meta['scanner_age_seconds']))} old")

    if not parts:
        return 'Freshness: cache age unknown'
    return 'Freshness: ' + ' · '.join(parts)


def _base_freshness_meta() -> dict[str, Any]:
    return {
        'quote_age_seconds': _file_age_seconds(QUOTE_FILE),
        'scanner_age_seconds': _file_age_seconds(SCANNER_FILE),
        'quote_refreshed_now': False,
        'scanner_refreshed_now': False,
        'cooldown_reused': False,
        'cooldown_age_seconds': 0,
        'refresh_failed': False,
        'refresh_skipped': False,
        'data_stale': False,
        'scopes_called': [],
    }


def is_tradecard_data_stale(meta: dict[str, Any]) -> bool:
    """True when refresh failed and cache exceeds TRADECARD_MAX_CACHE_AGE_SECONDS."""
    if not meta.get('refresh_failed'):
        return False
    max_age = max_cache_age_seconds()
    ages = [
        int(meta[k])
        for k in ('quote_age_seconds', 'scanner_age_seconds')
        if meta.get(k) is not None
    ]
    if not ages:
        return True
    return max(ages) > max_age


def _scope_succeeded(result: dict[str, Any], scope: str) -> bool:
    if not isinstance(result, dict):
        return False
    status = result.get(scope)
    if status == 'failed':
        return False
    if status in ('ok', 'skipped'):
        return True
    if result.get('partial') and scope in result:
        return result.get(scope) != 'failed'
    return bool(result.get('ok'))


def _run_lightweight_refresh() -> tuple[bool, bool, list[str]]:
    """Refresh prices + scanner only. Returns (prices_ok, scanner_ok, scopes_called)."""
    from backend.telegram.lazy_command_runner import _scoped_refresh

    scopes_called: list[str] = []
    prices_ok = True
    scanner_ok = True

    for scope in LIGHTWEIGHT_SCOPES:
        scopes_called.append(scope)
        try:
            result = _scoped_refresh(scope)
        except Exception:
            if scope == 'prices':
                prices_ok = False
            else:
                scanner_ok = False
            continue
        if scope == 'prices':
            prices_ok = _scope_succeeded(result, 'prices')
        else:
            scanner_ok = _scope_succeeded(result, 'scanner')

    return prices_ok, scanner_ok, scopes_called


def _rebuild_unified_and_card() -> None:
    unified_top = ''
    try:
        from backend.trading.unified_live_priority_engine import build_unified_priority

        unified = build_unified_priority(mode='today')
        top = unified.get('top_pick')
        if isinstance(top, dict):
            unified_top = str(top.get('ticker') or '').strip().upper()
    except Exception:
        pass

    try:
        from backend.trading.trade_card_engine import build_trade_card

        build_trade_card(ticker=unified_top or None, force_refresh=True, persist=True)
    except Exception:
        pass


def parse_tradecard_args(args: str) -> tuple[bool, bool]:
    """Return (force_refresh, explain) from /tradecard subcommand args."""
    tokens = [t.strip().lower() for t in str(args or '').split() if t.strip()]
    force = 'fresh' in tokens or force_refresh_enabled()
    explain = 'explain' in tokens
    return force, explain


def refresh_tradecard_market_data(
    chat_id: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Lightweight on-demand refresh for /tradecard during INDIA_MARKET_HOURS.

    Respects per-chat cooldown unless force=True or TRADECARD_FORCE_REFRESH=1.
    """
    cid = str(chat_id or 'default')
    meta = _base_freshness_meta()

    if not is_live_market_hours_phase():
        meta['refresh_skipped'] = True
        return meta

    now = time.monotonic()
    cooldown = cooldown_seconds()
    force = force or force_refresh_enabled()

    if not force and cid in _last_refresh_by_chat:
        elapsed = now - _last_refresh_by_chat[cid]
        if elapsed < cooldown:
            meta['cooldown_reused'] = True
            meta['cooldown_age_seconds'] = int(elapsed)
            meta['refresh_skipped'] = True
            return meta

    _last_refresh_by_chat[cid] = now

    prices_ok, scanner_ok, scopes_called = _run_lightweight_refresh()
    meta['scopes_called'] = scopes_called
    meta['quote_age_seconds'] = _file_age_seconds(QUOTE_FILE)
    meta['scanner_age_seconds'] = _file_age_seconds(SCANNER_FILE)
    meta['quote_refreshed_now'] = prices_ok
    meta['scanner_refreshed_now'] = scanner_ok
    meta['refresh_failed'] = not (prices_ok and scanner_ok)

    if prices_ok or scanner_ok:
        _rebuild_unified_and_card()

    meta['data_stale'] = is_tradecard_data_stale(meta)
    return meta


def reset_tradecard_cooldown_state() -> None:
    """Test helper — clear in-memory cooldown map."""
    _last_refresh_by_chat.clear()
