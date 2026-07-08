"""
Live confirmation guard — Phase 4B.18D / AstraEdge 52B.

Ensures scheduled 09:31 Final Opening Confirmation uses the same safety gate
as /tradecard: no CONFIRMED without live scanner/price support.
Paper/research only — no LLM calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18D'

CONFIRMED = 'CONFIRMED'
WAIT_LIVE_CONFIRM = 'WAIT_LIVE_CONFIRM'
NO_TRADE = 'NO_TRADE'
PULLBACK_ONLY = 'PULLBACK_ONLY'
WATCH_ONLY = 'WATCH_ONLY'

NEGATIVE_MOVE_PCT = -1.0
SHARP_NEGATIVE_PCT = -2.0
EXTENDED_MOVE_PCT = 5.0


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def session_date_ist(now: datetime | None = None) -> str:
    return _now_ist(now).date().isoformat()


def is_same_session_timestamp(ts: object, *, now: datetime | None = None) -> bool:
    """True when timestamp falls on the current IST trading date."""
    text = str(ts or '').strip()
    if not text:
        return False
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).date().isoformat() == session_date_ist(now)
    except ValueError:
        return text[:10] == session_date_ist(now)


def is_fresh_session_catalyst(
    catalyst: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Current-session fresh stock-specific catalyst only (not previous-day)."""
    if not isinstance(catalyst, dict) or not catalyst:
        return False
    label = str(catalyst.get('freshness_label') or '').lower()
    if label in ('stale', 'previous', 'previous_day', 'old'):
        return False
    for key in ('published_at', 'timestamp', 'created_at', 'imported_at', 'session_date'):
        if key in catalyst and catalyst.get(key):
            if key == 'session_date':
                return str(catalyst.get(key) or '')[:10] == session_date_ist(now)
            return is_same_session_timestamp(catalyst.get(key), now=now)
    # Broker/app alerts without timestamp: treat as fresh only when explicitly today/recent.
    if label in ('today', 'recent'):
        return True
    if bool(catalyst.get('broker_app_alert')) and label in ('', 'today', 'recent'):
        # Prefer explicit session stamp; without it, do not auto-confirm at 09:31.
        return False
    return False


def emergency_macro_crash_active(*, board: dict[str, Any] | None = None) -> bool:
    """True when board/macro state indicates crash / sharply red risk."""
    data = board or {}
    if bool(data.get('emergency_macro') or data.get('macro_crash') or data.get('crash_mode')):
        return True
    try:
        from backend.trading.macro_shock_sentinel import macro_shock_active_for_trading

        if macro_shock_active_for_trading():
            return True
    except Exception:
        pass
    try:
        penalty = float(data.get('macro_penalty') or 0)
    except (TypeError, ValueError):
        penalty = 0.0
    if penalty >= 12:
        return True
    try:
        from backend.orchestration.alert_quality_filters import EMERGENCY_STATE_FILE
        import json

        if EMERGENCY_STATE_FILE.is_file():
            payload = json.loads(EMERGENCY_STATE_FILE.read_text(encoding='utf-8'))
            if isinstance(payload, dict) and payload.get('active'):
                return True
            severity = str(payload.get('severity') or '').lower()
            if severity in ('emergency_macro', 'crash', 'red'):
                return True
    except Exception:
        pass
    return False


def has_live_scanner_row(row: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """True when candidate carries a fresh live scanner/price row for this session."""
    if not isinstance(row, dict):
        return False
    scanner = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else {}
    if not scanner and (
        row.get('price') not in (None, '')
        or row.get('ltp') not in (None, '')
        or row.get('change_percent') not in (None, '')
    ):
        scanner = row
    if not scanner:
        return False
    # Prefer explicit session stamp when present.
    for key in ('session_date', 'scan_date', 'as_of', 'timestamp', 'scan_time_local'):
        if scanner.get(key):
            if key == 'session_date' or key == 'scan_date':
                if str(scanner.get(key) or '')[:10] != session_date_ist(now):
                    return False
            elif not is_same_session_timestamp(scanner.get(key), now=now):
                # If stamped but stale, reject.
                text = str(scanner.get(key) or '')
                if len(text) >= 10 and text[:10] != session_date_ist(now):
                    return False
            break
    price = _safe_float(scanner.get('price') or scanner.get('ltp') or scanner.get('last_price') or scanner.get('close'))
    change = scanner.get('change_percent')
    volume = scanner.get('volume_ratio')
    if price <= 0 and change in (None, '') and volume in (None, ''):
        return False
    if bool(row.get('scanner_stale') or row.get('quote_stale') or scanner.get('stale')):
        return False
    return True


def has_live_gainer_or_radar(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    if bool(row.get('gainer_promoted') or row.get('promoted_from_gainers')):
        return True
    state = str(row.get('state') or '').upper()
    return state in {
        'TOP_GAINER_CONFIRM',
        'VOLUME_IGNITION',
        'PRICE_IGNITION',
        'SECTOR_BREADTH_CONFIRM',
        'TRADECARD_CANDIDATE',
        'NEW_LISTING_MOMENTUM',
        'DEMERGER_MOMENTUM',
    } and bool(row.get('scanner_row') or row.get('price') or row.get('change_percent') is not None)


def price_action_invalid(row: dict[str, Any] | None) -> tuple[bool, str]:
    """Reject sharply negative / selling-pressure setups."""
    if not isinstance(row, dict):
        return True, 'missing price action'
    scanner = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else row
    change = _safe_float(scanner.get('change_percent') if scanner else row.get('change_percent'))
    price = _safe_float((scanner or {}).get('price') or (scanner or {}).get('ltp') or row.get('price'))
    open_price = _safe_float((scanner or {}).get('open_price') or (scanner or {}).get('open'))
    vwap = _safe_float((scanner or {}).get('vwap'))
    volume = _safe_float((scanner or {}).get('volume_ratio') or row.get('volume_ratio'))

    if change <= SHARP_NEGATIVE_PCT:
        return True, f'sharply negative move ({change:.1f}%)'
    if change <= NEGATIVE_MOVE_PCT and volume < 1.2:
        return True, f'negative move with weak volume ({change:.1f}%)'
    if price > 0 and open_price > 0 and price < open_price and change < 0:
        return True, 'below open with selling pressure'
    if price > 0 and vwap > 0 and price < vwap and change < 0:
        return True, 'below VWAP with selling pressure'
    direction = str((scanner or {}).get('direction') or row.get('direction') or '').upper()
    if direction == 'BEARISH' and change < 0:
        return True, 'bearish scanner direction'
    return False, ''


def provisional_label_for_row(
    row: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    board: dict[str, Any] | None = None,
) -> str:
    """09:25 display label for catalyst-only / watch-only names."""
    verdict = evaluate_live_confirmation(row, now=now, board=board)
    state = str(verdict.get('state') or '')
    if state == CONFIRMED:
        return 'TRADECARD CANDIDATE'
    if state == PULLBACK_ONLY:
        return 'PULLBACK ONLY'
    if state == WAIT_LIVE_CONFIRM:
        return 'WAIT LIVE CONFIRM'
    if state == WATCH_ONLY:
        return 'WATCH ONLY'
    return 'NO TRADE'


def evaluate_live_confirmation(
    row: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    board: dict[str, Any] | None = None,
    require_tradecard_alignment: bool = True,
) -> dict[str, Any]:
    """
    Evaluate whether a candidate may be CONFIRMED at 09:31.

    Returns:
      state, reasons, live_scanner, fresh_catalyst, macro_crash, price_invalid
    """
    ist_now = _now_ist(now)
    data = board or {}
    if not isinstance(row, dict) or not _normalize_ticker(row.get('ticker')):
        return {
            'state': NO_TRADE,
            'reasons': ['no candidate'],
            'live_scanner': False,
            'fresh_catalyst': False,
            'macro_crash': False,
            'price_invalid': True,
        }

    if data.get('session_stale') or data.get('reference_only'):
        return {
            'state': NO_TRADE,
            'reasons': ['session data missing or reference-only'],
            'live_scanner': False,
            'fresh_catalyst': False,
            'macro_crash': False,
            'price_invalid': True,
        }

    macro_crash = emergency_macro_crash_active(board=data)
    live_scanner = has_live_scanner_row(row, now=ist_now) or has_live_gainer_or_radar(row)
    catalyst = row.get('catalyst') if isinstance(row.get('catalyst'), dict) else None
    if catalyst is None:
        classification = row.get('catalyst_classification')
        if isinstance(classification, dict):
            catalyst = classification.get('catalyst') if isinstance(classification.get('catalyst'), dict) else None
    fresh_catalyst = bool(row.get('has_catalyst')) and is_fresh_session_catalyst(catalyst, now=ist_now)
    if not fresh_catalyst and bool(row.get('has_catalyst')):
        # Explicit session-stale catalyst path.
        fresh_catalyst = False

    invalid, invalid_reason = price_action_invalid(row)
    change = _safe_float(
        (row.get('scanner_row') or {}).get('change_percent')
        if isinstance(row.get('scanner_row'), dict)
        else row.get('change_percent')
    )
    state_upper = str(row.get('state') or '').upper()
    score = int(row.get('score') or 0)
    extended = (
        state_upper in ('CHASE_RISK', 'PULLBACK_ONLY_PLAN')
        or bool(row.get('pullback_only'))
        or change >= EXTENDED_MOVE_PCT
    )

    reasons: list[str] = []

    if macro_crash and not (live_scanner and change > 0):
        reasons.append('market risk active; live scanner confirmation missing')
        return {
            'state': NO_TRADE if not fresh_catalyst else WAIT_LIVE_CONFIRM,
            'reasons': reasons,
            'live_scanner': live_scanner,
            'fresh_catalyst': fresh_catalyst,
            'macro_crash': True,
            'price_invalid': invalid,
        }

    if invalid and live_scanner:
        reasons.append(invalid_reason or 'price action invalid')
        return {
            'state': NO_TRADE,
            'reasons': reasons,
            'live_scanner': live_scanner,
            'fresh_catalyst': fresh_catalyst,
            'macro_crash': macro_crash,
            'price_invalid': True,
        }

    if not live_scanner:
        if fresh_catalyst or bool(row.get('has_catalyst')):
            reasons.append(
                'catalyst exists but live scanner/price evidence missing'
                if fresh_catalyst
                else 'catalyst not fresh for current session; live scanner missing'
            )
            return {
                'state': WAIT_LIVE_CONFIRM,
                'reasons': reasons,
                'live_scanner': False,
                'fresh_catalyst': fresh_catalyst,
                'macro_crash': macro_crash,
                'price_invalid': invalid,
            }
        if row.get('themes'):
            reasons.append('theme/old watchlist evidence only')
            return {
                'state': WATCH_ONLY,
                'reasons': reasons,
                'live_scanner': False,
                'fresh_catalyst': False,
                'macro_crash': macro_crash,
                'price_invalid': invalid,
            }
        reasons.append('scanner candidate missing')
        return {
            'state': NO_TRADE,
            'reasons': reasons,
            'live_scanner': False,
            'fresh_catalyst': False,
            'macro_crash': macro_crash,
            'price_invalid': invalid,
        }

    # Live evidence present.
    if extended and score >= 55:
        reasons.append('extended/chase risk with live evidence')
        return {
            'state': PULLBACK_ONLY,
            'reasons': reasons,
            'live_scanner': True,
            'fresh_catalyst': fresh_catalyst,
            'macro_crash': macro_crash,
            'price_invalid': False,
        }

    if require_tradecard_alignment and not _aligns_with_tradecard_gate(row, live_scanner=live_scanner, fresh_catalyst=fresh_catalyst):
        reasons.append('/tradecard gate would reject — live confirmation/scanner missing')
        return {
            'state': WAIT_LIVE_CONFIRM if fresh_catalyst else NO_TRADE,
            'reasons': reasons,
            'live_scanner': live_scanner,
            'fresh_catalyst': fresh_catalyst,
            'macro_crash': macro_crash,
            'price_invalid': False,
        }

    if live_scanner and (fresh_catalyst or change >= 0 or _safe_float(row.get('volume_ratio')) >= 1.2):
        reasons.append('live scanner/price confirmation present')
        return {
            'state': CONFIRMED,
            'reasons': reasons,
            'live_scanner': True,
            'fresh_catalyst': fresh_catalyst,
            'macro_crash': macro_crash,
            'price_invalid': False,
        }

    reasons.append('live evidence incomplete')
    return {
        'state': WAIT_LIVE_CONFIRM,
        'reasons': reasons,
        'live_scanner': live_scanner,
        'fresh_catalyst': fresh_catalyst,
        'macro_crash': macro_crash,
        'price_invalid': False,
    }


def _aligns_with_tradecard_gate(
    row: dict[str, Any],
    *,
    live_scanner: bool,
    fresh_catalyst: bool,
) -> bool:
    """Mirror /tradecard: no active confirm without scanner OR fresh catalyst + live support."""
    if live_scanner:
        return True
    if fresh_catalyst:
        # Catalyst alone is research-watch, not confirmation.
        return False
    return False


def select_final_confirmation_pick(
    board: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Choose 09:31 best pick under live confirmation gate.

    Returns pick dict with confirm_state, best_sym, best_row, best_score, watch_sym, reason.
    """
    from backend.trading.opening_rally_radar import (
        _normalize_ticker,
        pick_best_opening_tradecard,
        rerank_opening_candidates,
    )

    data = board or {}
    ist_now = _now_ist(now)
    ranked = rerank_opening_candidates([
        r for r in (data.get('ranked_candidates') or [])
        if str(r.get('state') or '').upper() != 'REJECTED'
    ])

    provisional_best, _, _ = pick_best_opening_tradecard(data)
    watch_sym = _normalize_ticker(provisional_best) if provisional_best else (
        _normalize_ticker(ranked[0].get('ticker')) if ranked else ''
    )

    for row in ranked:
        verdict = evaluate_live_confirmation(row, now=ist_now, board=data)
        state = str(verdict.get('state') or '')
        if state in (CONFIRMED, PULLBACK_ONLY):
            sym = _normalize_ticker(row.get('ticker'))
            return {
                'confirm_state': state if state != PULLBACK_ONLY else 'PULLBACK_ONLY_PLAN',
                'best_sym': sym,
                'best_row': row,
                'best_score': int(row.get('score') or 0),
                'watch_sym': watch_sym,
                'reason': ' + '.join(verdict.get('reasons') or []) or 'live confirmation passed',
                'verdict': verdict,
                'no_trade': False,
            }

    # No candidate passed confirm/pullback gate — pick best watch for message.
    watch_row = next(
        (r for r in ranked if _normalize_ticker(r.get('ticker')) == watch_sym),
        ranked[0] if ranked else None,
    )
    watch_verdict = evaluate_live_confirmation(watch_row, now=ist_now, board=data) if watch_row else {
        'state': NO_TRADE,
        'reasons': ['no candidate passed live confirmation gate'],
    }
    downgrade = str(watch_verdict.get('state') or NO_TRADE)
    if downgrade == CONFIRMED:
        downgrade = WAIT_LIVE_CONFIRM
    if downgrade == PULLBACK_ONLY:
        downgrade = 'PULLBACK_ONLY_PLAN'
    if downgrade == WATCH_ONLY:
        downgrade = WAIT_LIVE_CONFIRM
    reason = ' + '.join(watch_verdict.get('reasons') or []) or 'no candidate passed live confirmation gate'
    return {
        'confirm_state': NO_TRADE if downgrade == NO_TRADE else downgrade,
        'best_sym': '',
        'best_row': watch_row or {},
        'best_score': int((watch_row or {}).get('score') or 0),
        'watch_sym': watch_sym,
        'reason': reason,
        'verdict': watch_verdict,
        'no_trade': True,
    }
