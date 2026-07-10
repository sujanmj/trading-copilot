"""
Live scanner auto-refresh guard — AstraEdge 52M.

During MARKET_ACTIVE, /radar and /tradecards (and opening workflow) attempt one
lightweight scanner refresh when data is STALE, then block confirmed/quality
output if scanner remains stale. Paper/research only — no LLM calls.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from backend.trading.market_freshness_guard import (
    FRESHNESS_CURRENT,
    FRESHNESS_MISSING,
    FRESHNESS_PREOPEN_ONLY,
    FRESHNESS_PREVIOUS_SESSION,
    FRESHNESS_STALE,
    evaluate_all_source_freshness,
    is_live_scanner_ready,
    refresh_scanner_scopes,
)

STAGE = '52M'
AUTO_REFRESH_COOLDOWN_SECONDS = 60
BLOCKED_STALE_DATA = 'BLOCKED_STALE_DATA'

LIVE_SCANNER_COMMANDS = frozenset({
    'radar',
    'tradecards',
    'opening_radar_0920',
    'early_tradecards_0925',
    'final_opening_confirmation_0931',
    'today',
    'action_plan',
})

_cooldown_last_at: float = 0.0


def _now_ist(now: datetime | None = None) -> datetime:
    from backend.trading.market_freshness_guard import _now_ist as _guard_now

    return _guard_now(now)


def reset_auto_refresh_cooldown_for_tests() -> None:
    """Test helper — clear global auto-refresh cooldown."""
    global _cooldown_last_at
    _cooldown_last_at = 0.0


def _macro_red_active(board: dict[str, Any] | None) -> bool:
    data = board or {}
    if bool(data.get('emergency_macro') or data.get('macro_crash') or data.get('gap_down_risk')):
        return True
    macro = data.get('macro_shock') if isinstance(data.get('macro_shock'), dict) else {}
    if macro.get('active') and str(macro.get('severity') or '').upper() in ('HIGH', 'CRITICAL'):
        return True
    try:
        from backend.trading.live_confirmation_guard import emergency_macro_crash_active

        return emergency_macro_crash_active(board=data)
    except Exception:
        return False


def evaluate_live_freshness_policy(
    *,
    command_name: str,
    board: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Shared live freshness policy for scanner-dependent commands."""
    from backend.trading.opening_session_freshness import resolve_market_lifecycle

    ist = _now_ist(now)
    data = dict(board or {})
    lifecycle = str(resolve_market_lifecycle(ist) or '')
    table = data.get('market_freshness') if isinstance(data.get('market_freshness'), dict) else {}
    if not table:
        table = evaluate_all_source_freshness(board=data, now=ist)

    scanner_status = str(
        data.get('scanner_freshness_status')
        or (table.get('scanner') or {}).get('freshness_status')
        or FRESHNESS_MISSING
    )
    gainers_status = str((table.get('gainers') or {}).get('freshness_status') or FRESHNESS_MISSING)
    news_status = str((table.get('news') or {}).get('freshness_status') or FRESHNESS_MISSING)
    macro_red = _macro_red_active(data)
    live_ready = bool(data.get('live_scanner_ready')) or scanner_status == FRESHNESS_CURRENT
    scanner_stale = bool(data.get('scanner_stale')) or (
        lifecycle == 'MARKET_ACTIVE' and scanner_status != FRESHNESS_CURRENT
    )
    cmd = str(command_name or '').strip().lower()

    premarket_watch_only = lifecycle in ('PRE_MARKET', 'PREMARKET', 'INDIA_PREMARKET_MODE', 'INDIA_PREOPEN_MODE')
    after_hours_reference = lifecycle in ('AFTER_HOURS', 'POST_MARKET', 'WEEKEND')

    requires_auto_refresh = (
        cmd in LIVE_SCANNER_COMMANDS
        and lifecycle == 'MARKET_ACTIVE'
        and scanner_stale
        and not data.get('reference_only')
    )

    live_confirmation_blocked = False
    quality_tradecard_blocked = False

    if lifecycle == 'MARKET_ACTIVE':
        if not live_ready or scanner_stale:
            live_confirmation_blocked = True
            quality_tradecard_blocked = True
        if macro_red and scanner_stale:
            live_confirmation_blocked = True
            quality_tradecard_blocked = True
    elif premarket_watch_only:
        live_confirmation_blocked = True
    elif after_hours_reference:
        live_confirmation_blocked = True

    allows_live_confirmation = (
        lifecycle == 'MARKET_ACTIVE'
        and live_ready
        and not scanner_stale
        and not (macro_red and not live_ready)
    )
    allows_quality_tradecard = allows_live_confirmation

    return {
        'command': cmd,
        'market_lifecycle': lifecycle,
        'scanner_status': scanner_status,
        'gainers_status': gainers_status,
        'news_status': news_status,
        'board_session_date': str(data.get('source_session_date') or data.get('session_date') or '')[:10],
        'requires_auto_refresh': requires_auto_refresh,
        'allows_live_confirmation': allows_live_confirmation,
        'allows_quality_tradecard': allows_quality_tradecard,
        'live_confirmation_blocked': live_confirmation_blocked,
        'quality_tradecard_blocked': quality_tradecard_blocked,
        'premarket_watch_only': premarket_watch_only,
        'after_hours_reference': after_hours_reference,
        'macro_red_active': macro_red,
        'scanner_stale': scanner_stale,
    }


def attempt_lightweight_scanner_refresh(
    *,
    now: datetime | None = None,
    respect_cooldown: bool = True,
) -> dict[str, Any]:
    """Refresh scanner + prices only (no news, no full refresh, no AI)."""
    global _cooldown_last_at

    ist = _now_ist(now)
    if respect_cooldown and _cooldown_last_at > 0:
        elapsed = time.monotonic() - _cooldown_last_at
        if elapsed < AUTO_REFRESH_COOLDOWN_SECONDS:
            return {
                'attempted': False,
                'refreshed': False,
                'skipped_cooldown': True,
                'scanner_ok': False,
                'prices_ok': False,
                'reason': 'cooldown active',
            }

    _cooldown_last_at = time.monotonic()
    from backend.telegram.lazy_command_runner import _scoped_refresh

    scanner_ok = False
    prices_ok = False
    errors: list[str] = []
    for scope in refresh_scanner_scopes():
        result = _scoped_refresh(scope)
        ok = bool(result.get('ok'))
        if scope == 'scanner':
            scanner_ok = ok
        elif scope == 'prices':
            prices_ok = ok
        if not ok:
            errors.append(str(result.get('error') or result.get('scope') or scope))

    refreshed = is_live_scanner_ready(now=ist)
    reason = ''
    if not refreshed:
        reason = errors[0] if errors else 'scanner still stale'

    print(
        f'[LIVE_SCANNER_AUTOREFRESH] refreshed={refreshed} scanner_ok={scanner_ok} '
        f'prices_ok={prices_ok} reason={reason or "ok"}',
        flush=True,
    )
    return {
        'attempted': True,
        'refreshed': refreshed,
        'skipped_cooldown': False,
        'scanner_ok': scanner_ok,
        'prices_ok': prices_ok,
        'reason': reason,
    }


def prepare_board_for_live_command(
    command_name: str,
    *,
    board: dict[str, Any] | None = None,
    now: datetime | None = None,
    allow_auto_refresh: bool = True,
) -> dict[str, Any]:
    """Build or refresh board with optional one-shot scanner auto-refresh."""
    from backend.trading.opening_rally_radar import build_opening_rally_board, rerank_opening_candidates

    ist = _now_ist(now)
    data = dict(board) if board else build_opening_rally_board(now=ist)
    policy = evaluate_live_freshness_policy(command_name=command_name, board=data, now=ist)
    auto_refresh: dict[str, Any] = {
        'attempted': False,
        'refreshed': False,
        'skipped_cooldown': False,
        'scanner_ok': False,
        'prices_ok': False,
        'reason': '',
    }

    if allow_auto_refresh and policy.get('requires_auto_refresh'):
        auto_refresh = attempt_lightweight_scanner_refresh(now=ist)
        if auto_refresh.get('refreshed'):
            data = build_opening_rally_board(now=ist)
        policy = evaluate_live_freshness_policy(command_name=command_name, board=data, now=ist)

    data['auto_refresh'] = auto_refresh
    data['live_freshness_policy'] = policy

    if policy.get('live_confirmation_blocked'):
        data['live_confirmation_blocked'] = True
    if policy.get('quality_tradecard_blocked'):
        data['quality_tradecard_blocked'] = True

    if (
        policy.get('market_lifecycle') == 'MARKET_ACTIVE'
        and auto_refresh.get('attempted')
        and not auto_refresh.get('refreshed')
        and not auto_refresh.get('skipped_cooldown')
    ):
        data['stale_after_auto_refresh'] = True
        data['live_confirmation_blocked'] = True
        data['quality_tradecard_blocked'] = True

    if auto_refresh.get('skipped_cooldown') and policy.get('scanner_stale'):
        data['auto_refresh_skipped_cooldown'] = True
        data['live_confirmation_blocked'] = True
        data['quality_tradecard_blocked'] = True

    if not data.get('reference_only') and not data.get('session_stale'):
        data['ranked_candidates'] = rerank_opening_candidates(
            list(data.get('ranked_candidates') or []),
        )
    return data


def format_auto_refresh_block(board: dict[str, Any] | None) -> list[str]:
    """Telegram lines for auto-refresh attempt outcome."""
    data = board or {}
    auto = data.get('auto_refresh') if isinstance(data.get('auto_refresh'), dict) else {}
    if data.get('auto_refresh_skipped_cooldown'):
        return [
            'Auto-refresh skipped: cooldown active',
            'Try /refresh scanner manually.',
        ]
    if not auto.get('attempted') and not auto.get('skipped_cooldown'):
        return []
    if auto.get('skipped_cooldown'):
        return [
            'Auto-refresh skipped: cooldown active',
            'Try /refresh scanner manually.',
        ]
    if auto.get('refreshed'):
        parts = ['scanner: refreshed']
        if auto.get('prices_ok'):
            parts.append('prices: ok')
        return [f'Auto-refresh: {" · ".join(parts)}']
    reason = str(auto.get('reason') or 'scanner refresh failed').strip()
    return [
        'Auto-refresh: failed',
        f'Reason: {reason}',
        'Live data stale — no confirmed setup allowed.',
    ]


def format_stale_scanner_no_quality_block() -> list[str]:
    return [
        'NO QUALITY TRADECARD',
        'Reason: live scanner stale after refresh attempt',
    ]


def format_stale_radar_reference_block() -> list[str]:
    return [
        'Live scanner stale — radar is reference only.',
        '',
        'No confirmed setup allowed until scanner is CURRENT.',
        'Try: /refresh scanner',
    ]
