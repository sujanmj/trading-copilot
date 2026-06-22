"""
Personal intraday trade card engine — Stage 50N.

News-first catalyst radar, then scanner/anomaly + confluence inputs.
Paper-only observation card. Never places orders or emits blind BUY/SELL.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
TRADE_CARD_CACHE = DATA_DIR / 'trade_card_latest.json'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'
INTEL_FILE = DATA_DIR / 'intelligence.json'
FINAL_CONF_FILE = DATA_DIR / 'final_confidence_report.json'

VALID_STATUSES = frozenset({
    'VALID_ENTRY',
    'WAIT_FOR_PULLBACK',
    'WAIT_FOR_VOLUME',
    'ENTRY_MISSED',
    'AVOID',
    'NO_TRADE',
    'NO_ACTIVE_ENTRY',
    'NEXT_SESSION_WATCH',
})

MIN_RR = 1.5
MIN_VOLUME_RATIO = 0.8
SCALP_MAX_SL_PCT = 1.2
SCALP_IDEAL_SL_PCT = 0.6
SCALP_T1_MIN_PCT = 0.8
SCALP_T1_MAX_PCT = 1.2
SCALP_T2_MIN_PCT = 1.3
SCALP_T2_MAX_PCT = 2.0
SCALP_T1_PCT = 1.0
SCALP_T2_PCT = 1.65
MAX_SL_PCT = SCALP_MAX_SL_PCT
EXTENDED_MOVE_PCT = 5.0
ENTRY_MISSED_MOVE_PCT = 5.0
PAPER_ONLY = True

_log = logging.getLogger(__name__)

_LIVE_MARKET_PHASES = frozenset({'INDIA_MARKET_HOURS'})


def _is_live_market_hours() -> bool:
    try:
        from backend.telegram.india_mode_lock import resolve_telegram_market_phase

        return resolve_telegram_market_phase() in _LIVE_MARKET_PHASES
    except Exception:
        return False


def _is_premarket_mode() -> bool:
    try:
        from backend.telegram.india_mode_lock import is_premarket_phase

        return is_premarket_phase()
    except Exception:
        return False


def _is_after_hours_mode() -> bool:
    try:
        from backend.telegram.india_mode_lock import resolve_telegram_market_phase

        phase = resolve_telegram_market_phase()
        return phase in {
            'INDIA_AFTER_HOURS',
            'INDIA_AFTER_HOURS_MODE',
            'INDIA_POSTMARKET_MODE',
            'RESEARCH_MODE',
        }
    except Exception:
        return False


def _target_pct_from_entry(price: float, target: float | None) -> float:
    if price <= 0 or target is None:
        return 0.0
    return round((float(target) - price) / price * 100, 2)


def _scalp_levels_valid(plan: dict[str, Any]) -> tuple[bool, str]:
    price = _safe_float(plan.get('price'))
    sl_pct = _safe_float(plan.get('sl_pct'))
    if sl_pct > SCALP_MAX_SL_PCT:
        return False, f'stop too wide ({sl_pct:.1f}%) for intraday scalp'
    t1_pct = _target_pct_from_entry(price, plan.get('target_1'))
    t2_pct = _target_pct_from_entry(price, plan.get('target_2'))
    if t1_pct and not (SCALP_T1_MIN_PCT <= t1_pct <= SCALP_T1_MAX_PCT):
        return False, f'T1 {t1_pct:.1f}% outside scalp range {SCALP_T1_MIN_PCT}–{SCALP_T1_MAX_PCT}%'
    if t2_pct and not (SCALP_T2_MIN_PCT <= t2_pct <= SCALP_T2_MAX_PCT):
        return False, f'T2 {t2_pct:.1f}% outside scalp range {SCALP_T2_MIN_PCT}–{SCALP_T2_MAX_PCT}%'
    return True, ''


def _ticker_bound_data_valid(sym: str, row: dict[str, Any], plan: dict[str, Any]) -> bool:
    row_sym = _normalize_ticker(row.get('ticker'))
    if row_sym and row_sym != sym:
        return False
    source_sym = _normalize_ticker(plan.get('levels_source_ticker') or row_sym)
    if source_sym and source_sym != sym:
        _log.warning('tradecard ticker/levels mismatch: selected=%s source=%s', sym, source_sym)
        return False
    row_price = _safe_float(row.get('price') or row.get('last_price'))
    plan_price = _safe_float(plan.get('price'))
    if row_price > 0 and plan_price > 0 and abs(row_price - plan_price) / row_price > 0.02:
        return False
    return True


def _unified_today_top_ticker() -> str:
    try:
        from backend.trading.unified_live_priority_engine import build_unified_priority

        unified = build_unified_priority(mode='today')
        top = unified.get('top_pick')
        if isinstance(top, dict):
            return _normalize_ticker(top.get('ticker'))
    except Exception:
        pass
    return ''


TRADECARD_SOURCE_LABELS = frozenset({
    'Source: scanner-confirmed',
    'Source: catalyst-backed + scanner-confirmed',
    'Source: catalyst-backed',
    'Source: research-only',
})


def resolve_tradecard_source_label(card: dict[str, Any], ticker: str) -> str:
    """Prefer engine-provided source_label; do not downgrade catalyst-backed labels."""
    label = str(card.get('source_label') or '').strip()
    if label in TRADECARD_SOURCE_LABELS:
        return label
    sym = _normalize_ticker(ticker)
    if not sym:
        return 'Source: scanner-confirmed'
    try:
        from backend.trading.unified_live_priority_engine import decision_source_label

        return decision_source_label(sym)
    except Exception:
        return 'Source: scanner-confirmed'


def _ensure_source_label(card: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(card, dict):
        return card
    sym = _normalize_ticker(card.get('ticker'))
    if not sym or sym == '—':
        return card
    if str(card.get('source_label') or '').strip() in TRADECARD_SOURCE_LABELS:
        return card
    return {**card, 'source_label': resolve_tradecard_source_label(card, sym)}


def _strip_actionable_levels(card: dict[str, Any], *, reason: str, status: str = 'NO_ACTIVE_ENTRY') -> dict[str, Any]:
    updated = {
        **card,
        'status': status,
        'entry_zone': 'NO ACTIVE ENTRY',
        'stop_loss': None,
        'target_1': None,
        'target_2': None,
        'risk_reward': 0.0,
        'reason': reason[:240],
        'capital_plan': 'Paper only — no order execution.',
    }
    if _is_after_hours_mode():
        updated['status'] = 'NEXT_SESSION_WATCH'
        updated['after_hours'] = True
    return updated


def apply_tradecard_safety_gates(card: dict[str, Any]) -> dict[str, Any]:
    """Final hard gate — never expose VALID_ENTRY unless all scalp/market checks pass."""
    return _ensure_source_label(_apply_tradecard_safety_gates(card))


def _apply_tradecard_safety_gates(card: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(card, dict) or not card.get('ticker'):
        return card

    sym = _normalize_ticker(card.get('ticker'))
    source_sym = _normalize_ticker(card.get('levels_source_ticker') or sym)
    if sym and source_sym and sym != source_sym:
        return _strip_actionable_levels(
            card,
            reason='ticker/price data mismatch',
            status='NO_ACTIVE_ENTRY',
        )

    reason = str(card.get('reason') or '')
    if 'stop too wide' in reason.lower() and card.get('status') == 'VALID_ENTRY':
        return _strip_actionable_levels(
            card,
            reason=reason or 'stop too wide for intraday scalp',
            status='NO_ACTIVE_ENTRY',
        )

    if _is_after_hours_mode() and card.get('status') == 'VALID_ENTRY':
        return _strip_actionable_levels(
            card,
            reason='market closed/after-hours',
            status='NEXT_SESSION_WATCH',
        )

    if card.get('status') != 'VALID_ENTRY':
        if _is_after_hours_mode() and card.get('status') in ('WAIT_FOR_PULLBACK', 'WAIT_FOR_VOLUME'):
            return _strip_actionable_levels(
                card,
                reason='market closed/after-hours',
                status='NEXT_SESSION_WATCH',
            )
        return card

    price = _safe_float(card.get('current_price'))
    stop = card.get('stop_loss')
    sl_pct = round((price - _safe_float(stop)) / price * 100, 2) if price and stop else 0.0
    plan = {
        'price': price,
        'stop_loss': stop,
        'target_1': card.get('target_1'),
        'target_2': card.get('target_2'),
        'sl_pct': sl_pct,
        'levels_source_ticker': source_sym,
    }
    ok, scalp_reason = _scalp_levels_valid(plan)
    if not ok:
        return _strip_actionable_levels(card, reason=scalp_reason or reason, status='NO_ACTIVE_ENTRY')

    if sl_pct > SCALP_MAX_SL_PCT:
        return _strip_actionable_levels(
            card,
            reason=f'stop too wide ({sl_pct:.1f}%) for intraday scalp',
            status='NO_ACTIVE_ENTRY',
        )

    vol = _safe_float(card.get('volume_ratio'), 0.0)
    if vol < MIN_VOLUME_RATIO:
        return _strip_actionable_levels(
            card,
            reason=f'Volume participation {vol:.1f}x below threshold',
            status='WAIT_FOR_VOLUME',
        )

    rr = _safe_float(card.get('risk_reward'))
    if rr < MIN_RR:
        return _strip_actionable_levels(
            card,
            reason=f'Risk/reward {rr:.2f} below minimum {MIN_RR}',
            status='NO_TRADE',
        )

    if not _is_live_market_hours():
        if _is_premarket_mode():
            return _strip_actionable_levels(
                card,
                reason='market not open for confirmed entry yet',
                status='NO_ACTIVE_ENTRY',
            )
        return _strip_actionable_levels(
            card,
            reason='market closed/after-hours',
            status='NEXT_SESSION_WATCH',
        )

    return card



def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _today() -> str:
    return datetime.now(IST).strftime('%Y-%m-%d')


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _estimate_atr(price: float, change_pct: float, volume_ratio: float) -> float:
    vol_pct = max(0.6, min(6.0, abs(change_pct) * 0.35 + max(1.0, volume_ratio) * 0.25))
    return price * vol_pct / 100.0


def _avoid_registry() -> dict[str, str]:
    from backend.analytics.unified_decision_engine import build_live_rejection_set

    return build_live_rejection_set()


def _scanner_index(scanner: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sig in (scanner or {}).get('top_signals') or (scanner or {}).get('signals') or []:
        if not isinstance(sig, dict):
            continue
        sym = _normalize_ticker(sig.get('ticker') or sig.get('symbol'))
        if sym:
            out[sym] = sig
    return out


def _pick_candidate(
    ticker: Optional[str],
    scanner: dict[str, Any],
    registry: dict[str, str],
) -> tuple[Optional[dict[str, Any]], str]:
    if ticker:
        sym = _normalize_ticker(ticker)
        row = _scanner_index(scanner).get(sym)
        if not row:
            fc = _load_json(FINAL_CONF_FILE)
            for item in fc.get('top_candidates') or fc.get('rows') or []:
                if _normalize_ticker(item.get('ticker')) == sym:
                    row = {
                        'ticker': sym,
                        'price': item.get('price') or item.get('last_price'),
                        'change_percent': item.get('change_percent') or 0,
                        'volume_ratio': item.get('volume_ratio') or 1.0,
                        'direction': item.get('direction') or 'BULLISH',
                        'strength': item.get('strength') or 'WATCH',
                    }
                    break
        if not row:
            return None, 'ticker_not_in_scanner'
        if sym in registry:
            return row, 'avoid_override'
        return row, 'requested'

    ranked: list[tuple[float, dict[str, Any]]] = []
    for sig in (scanner or {}).get('top_signals') or []:
        if not isinstance(sig, dict):
            continue
        sym = _normalize_ticker(sig.get('ticker'))
        if not sym or sym in registry:
            continue
        direction = str(sig.get('direction') or '').upper()
        if direction == 'BEARISH':
            continue
        chg = abs(_safe_float(sig.get('change_percent')))
        vol = _safe_float(sig.get('volume_ratio'), 1.0)
        strength = str(sig.get('strength') or '').upper()
        score = chg * 1.2 + vol * 2.0 + (3.0 if strength == 'ULTRA' else 0.0)
        ranked.append((score, sig))
    if not ranked:
        return None, 'no_clean_candidate'
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1], 'top_scanner'


def detect_entry_missed(
    *,
    price: float,
    change_pct: float,
    volume_ratio: float,
    day_high: Optional[float] = None,
    vwap: Optional[float] = None,
    open_price: Optional[float] = None,
    risk_reward: float = 0.0,
    sl_pct: float = 0.0,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if price <= 0:
        return True, ['missing price']

    if abs(change_pct) >= ENTRY_MISSED_MOVE_PCT:
        reasons.append(f'extended move {change_pct:+.1f}% without pullback')

    if day_high and price > 0 and day_high > 0:
        if price >= day_high * 0.985 and abs(change_pct) >= 5.0:
            reasons.append('near day high after large move')

    if vwap and vwap > 0 and price > vwap * 1.025 and abs(change_pct) >= 5.0:
        reasons.append('extended above VWAP — chase risk')

    if open_price and open_price > 0 and price > open_price * 1.04 and abs(change_pct) >= 5.0:
        reasons.append('moved too far from open without retest')

    if risk_reward > 0 and risk_reward < MIN_RR and abs(change_pct) >= 4.0:
        reasons.append(f'risk/reward {risk_reward:.2f} below {MIN_RR}')

    if sl_pct > SCALP_MAX_SL_PCT:
        reasons.append(f'stop too wide ({sl_pct:.1f}%)')

    if volume_ratio < MIN_VOLUME_RATIO and abs(change_pct) >= 4.0:
        reasons.append('large move on weak volume — wait for participation')

    return bool(reasons), reasons


def _compute_plan(row: dict[str, Any]) -> dict[str, Any]:
    price = _safe_float(row.get('price') or row.get('last_price'))
    change_pct = _safe_float(row.get('change_percent'))
    volume_ratio = _safe_float(row.get('volume_ratio'), 1.0)
    vwap = _safe_float(row.get('vwap')) or None
    open_price = _safe_float(row.get('open')) or None
    day_high = _safe_float(row.get('day_high') or row.get('high')) or None

    if price <= 0:
        return {
            'entry_zone': '—',
            'stop_loss': None,
            'target_1': None,
            'target_2': None,
            'risk_reward': 0.0,
            'sl_pct': 0.0,
            'price': 0.0,
            'change_pct': change_pct,
            'volume_ratio': volume_ratio,
        }

    sl_pct_val = SCALP_IDEAL_SL_PCT
    stop = round(price * (1 - sl_pct_val / 100), 2)
    entry_low = round(price * (1 - 0.002), 2)
    entry_high = round(price * (1 + 0.003), 2)
    target_1 = round(price * (1 + SCALP_T1_PCT / 100), 2)
    target_2 = round(price * (1 + SCALP_T2_PCT / 100), 2)

    risk = max(0.01, price - stop)
    reward = max(0.0, target_1 - price)
    rr = round(reward / risk, 2) if risk else 0.0
    sl_pct = round((price - stop) / price * 100, 2) if price else 0.0

    return {
        'entry_zone': f'{entry_low:.2f}–{entry_high:.2f}',
        'stop_loss': stop,
        'target_1': target_1,
        'target_2': target_2,
        'risk_reward': rr,
        'sl_pct': sl_pct,
        't1_pct': round(SCALP_T1_PCT, 2),
        't2_pct': round(SCALP_T2_PCT, 2),
        'levels_source_ticker': _normalize_ticker(row.get('ticker')),
        'vwap': vwap,
        'open_price': open_price,
        'day_high': day_high,
        'volume_ratio': volume_ratio,
        'change_pct': change_pct,
        'price': price,
    }


def _confidence_label(score: float) -> str:
    if score >= 72:
        return 'HIGH'
    if score >= 55:
        return 'MEDIUM'
    return 'LOW'


def build_trade_card(
    ticker: Optional[str] = None,
    *,
    persist: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Build one paper-only trade card for the session."""
    session_date = _today()
    unified_top = _unified_today_top_ticker() if not ticker else ''
    if not force_refresh and TRADE_CARD_CACHE.is_file():
        cached = _load_json(TRADE_CARD_CACHE)
        cached_sym = _normalize_ticker(cached.get('ticker'))
        cached_src = _normalize_ticker(cached.get('levels_source_ticker') or cached_sym)
        cache_ok = (
            cached.get('session_date') == session_date
            and cached.get('ticker')
            and not ticker
            and cached.get('status') in VALID_STATUSES
            and cached_sym == cached_src
            and (not unified_top or cached_sym == unified_top)
        )
        if cache_ok:
            cached.setdefault('paper_only', True)
            return apply_tradecard_safety_gates(cached)

    scanner = _load_json(SCANNER_FILE)
    intel = _load_json(INTEL_FILE)
    registry = _avoid_registry()

    catalyst_ticker: Optional[str] = None
    pick_reason = 'top_scanner'
    if not ticker:
        try:
            from backend.trading.unified_live_priority_engine import pick_tradecard_candidate

            unified_ticker, unified_reason = pick_tradecard_candidate(registry=registry, scanner=scanner)
            if unified_ticker:
                ticker = unified_ticker
                pick_reason = unified_reason
        except Exception:
            pass
        if not ticker:
            try:
                from backend.intelligence.stock_catalyst_radar import pick_catalyst_tradecard_candidate

                catalyst_ticker, catalyst_reason = pick_catalyst_tradecard_candidate(registry=registry)
                if catalyst_ticker:
                    ticker = catalyst_ticker
                    pick_reason = catalyst_reason
            except Exception:
                pass

    row, scanner_pick_reason = _pick_candidate(ticker, scanner, registry)
    if pick_reason == 'top_scanner':
        pick_reason = scanner_pick_reason
    sym = _normalize_ticker(row.get('ticker') if row else ticker)

    base: dict[str, Any] = {
        'ok': True,
        'session_date': session_date,
        'generated_at': _now_iso(),
        'ticker': sym or '—',
        'status': 'NO_TRADE',
        'current_price': None,
        'entry_zone': '—',
        'stop_loss': None,
        'target_1': None,
        'target_2': None,
        'risk_reward': 0.0,
        'capital_plan': 'Paper only — no order execution.',
        'reason': 'No safe intraday entry identified.',
        'invalid_if': 'Price breaks below stop or volume fades.',
        'exit_rule': 'Trim at T1; trail below VWAP or prior support.',
        'confidence': 'LOW',
        'paper_only': True,
        'pick_reason': pick_reason,
    }

    if not row:
        if ticker and pick_reason.startswith('unified'):
            sym = _normalize_ticker(ticker)
            entry_status = 'NO_ACTIVE_ENTRY'
            try:
                from backend.trading.unified_live_priority_engine import build_unified_priority

                unified = build_unified_priority(mode='today')
                for urow in [unified.get('top_pick'), *(unified.get('ranked_candidates') or [])]:
                    if not isinstance(urow, dict):
                        continue
                    if _normalize_ticker(urow.get('ticker')) != sym:
                        continue
                    entry_status = str(urow.get('entry_status') or 'NO_ACTIVE_ENTRY')
                    break
            except Exception:
                pass
            status = {
                'ENTRY_MISSED': 'ENTRY_MISSED',
                'WAIT_FOR_VOLUME': 'WAIT_FOR_VOLUME',
                'WAIT_FOR_PULLBACK': 'WAIT_FOR_PULLBACK',
                'VALID_ENTRY': 'VALID_ENTRY',
            }.get(entry_status, 'NO_TRADE')
            base.update({
                'ticker': sym,
                'status': status,
                'entry_zone': 'NO ACTIVE ENTRY',
                'reason': 'Unified /today top — no valid entry on live scanner row.',
                'pick_reason': pick_reason,
            })
            if persist:
                TRADE_CARD_CACHE.parent.mkdir(parents=True, exist_ok=True)
                TRADE_CARD_CACHE.write_text(json.dumps(base, indent=2), encoding='utf-8')
            return base
        base['ok'] = False
        base['reason'] = 'No scanner candidate available for trade card.'
        if persist:
            TRADE_CARD_CACHE.parent.mkdir(parents=True, exist_ok=True)
            TRADE_CARD_CACHE.write_text(json.dumps(base, indent=2), encoding='utf-8')
        return base

    if sym in registry:
        base.update({
            'ticker': sym,
            'status': 'AVOID',
            'current_price': _safe_float(row.get('price')),
            'reason': f"Avoid/rejection override — {registry[sym][:120]}",
            'confidence': 'LOW',
        })
        if persist:
            TRADE_CARD_CACHE.write_text(json.dumps(base, indent=2), encoding='utf-8')
        return base

    plan = _compute_plan(row)
    price = plan['price']
    change_pct = plan['change_pct']
    volume_ratio = plan['volume_ratio']
    rr = plan['risk_reward']

    if not _ticker_bound_data_valid(sym, row, plan):
        blocked = _strip_actionable_levels(
            base,
            reason='ticker/price data mismatch',
            status='NO_ACTIVE_ENTRY',
        )
        blocked.update({
            'ticker': sym,
            'current_price': round(price, 2) if price else None,
            'levels_source_ticker': plan.get('levels_source_ticker'),
            'pick_reason': pick_reason,
        })
        if persist:
            TRADE_CARD_CACHE.write_text(json.dumps(blocked, indent=2), encoding='utf-8')
        return apply_tradecard_safety_gates(blocked)

    missed, missed_reasons = detect_entry_missed(
        price=price,
        change_pct=change_pct,
        volume_ratio=volume_ratio,
        day_high=plan.get('day_high'),
        vwap=plan.get('vwap'),
        open_price=plan.get('open_price'),
        risk_reward=rr,
        sl_pct=plan['sl_pct'],
    )

    scalp_ok, scalp_reason = _scalp_levels_valid(plan)

    status = 'NO_TRADE'
    reason_parts: list[str] = []

    if _is_after_hours_mode():
        status = 'NEXT_SESSION_WATCH'
        reason_parts.append('market closed/after-hours')
    elif missed:
        status = 'ENTRY_MISSED'
        reason_parts.extend(missed_reasons)
    elif not scalp_ok:
        status = 'NO_ACTIVE_ENTRY'
        reason_parts.append(scalp_reason or 'targets/stop outside scalp range')
    elif plan['sl_pct'] > SCALP_MAX_SL_PCT:
        status = 'NO_ACTIVE_ENTRY'
        reason_parts.append(f"stop too wide ({plan['sl_pct']:.1f}%) for intraday scalp")
    elif rr < MIN_RR:
        status = 'NO_TRADE'
        reason_parts.append(f'Risk/reward {rr:.2f} below minimum {MIN_RR}')
    elif volume_ratio < MIN_VOLUME_RATIO:
        status = 'WAIT_FOR_VOLUME'
        reason_parts.append(f'Volume participation {volume_ratio:.1f}x below threshold')
    elif abs(change_pct) >= EXTENDED_MOVE_PCT:
        status = 'WAIT_FOR_PULLBACK'
        reason_parts.append(f'Extended {change_pct:+.1f}% — wait for pullback toward entry zone')
    elif _is_live_market_hours():
        status = 'VALID_ENTRY'
        reason_parts.append('Price/volume/structure align for paper watch entry')
    else:
        status = 'NEXT_SESSION_WATCH'
        reason_parts.append('market closed/after-hours')

    sectors = (intel or {}).get('sector_rotation') or {}
    bullish = {_normalize_ticker(s) for s in (sectors.get('bullish') or [])}
    if sym in bullish:
        reason_parts.append('sector support aligned')

    conf_score = 40.0 + min(25.0, abs(change_pct)) + min(20.0, volume_ratio * 8)
    if status == 'ENTRY_MISSED':
        conf_score = min(conf_score, 48.0)
    elif status == 'VALID_ENTRY':
        conf_score = min(85.0, conf_score + 10.0)

    card = {
        **base,
        'ticker': sym,
        'status': status,
        'current_price': round(price, 2),
        'entry_zone': plan['entry_zone'],
        'stop_loss': plan['stop_loss'],
        'target_1': plan['target_1'],
        'target_2': plan['target_2'],
        'risk_reward': rr,
        'levels_source_ticker': plan.get('levels_source_ticker') or sym,
        'capital_plan': 'Paper only — risk 0.5–1R on manual entry if confirmed; no auto execution.',
        'reason': '; '.join(reason_parts)[:240],
        'invalid_if': f"Close below {plan['stop_loss']:.2f} or participation drops below {MIN_VOLUME_RATIO}x",
        'exit_rule': f"Partial at {plan['target_1']:.2f}; runner toward {plan['target_2']:.2f} while above VWAP",
        'confidence': _confidence_label(conf_score),
        'paper_only': True,
        'change_percent': round(change_pct, 2),
        'volume_ratio': round(volume_ratio, 2),
        'research_reference': {
            'stop_loss': plan['stop_loss'],
            'target_1': plan['target_1'],
            'target_2': plan['target_2'],
            'entry_zone': plan['entry_zone'],
        },
    }

    if status in ('ENTRY_MISSED', 'NO_ACTIVE_ENTRY', 'NEXT_SESSION_WATCH', 'NO_TRADE') or missed:
        card.update({
            'entry_zone': 'NO ACTIVE ENTRY',
            'stop_loss': None,
            'target_1': None,
            'target_2': None,
            'risk_reward': 0.0,
            'capital_plan': 'No trade until valid entry forms after pullback.',
            'invalid_if': 'No active entry — extended move.',
            'exit_rule': 'Wait for pullback/retest — no chase. If no pullback: NO TRADE.',
        })
        if status == 'ENTRY_MISSED':
            card['reason'] = '; '.join(reason_parts)[:240] or 'Strong move, but do not chase.'
        if status == 'NEXT_SESSION_WATCH':
            card['after_hours'] = True
            card['capital_plan'] = 'Paper only — confirm next session after 09:20 with fresh price + volume.'
            card['exit_rule'] = 'Wait for next session confirmation — no live entry now.'

    if status == 'ENTRY_MISSED':
        pass  # reason already set above

    card = apply_tradecard_safety_gates(card)

    if persist:
        TRADE_CARD_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TRADE_CARD_CACHE.write_text(json.dumps(card, indent=2), encoding='utf-8')
    return card


def is_trade_card_stale(card: dict[str, Any]) -> bool:
    if not card or card.get('session_date') != _today():
        return True
    generated = str(card.get('generated_at') or '')
    if not generated:
        return False
    try:
        dt = datetime.fromisoformat(generated.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        age_h = (datetime.now(IST) - dt.astimezone(IST)).total_seconds() / 3600.0
        return age_h > 6.0
    except ValueError:
        return False


def get_trade_card(*, rebuild: bool = False) -> dict[str, Any]:
    unified_top = _unified_today_top_ticker()
    if rebuild or not TRADE_CARD_CACHE.is_file():
        return apply_tradecard_safety_gates(
            build_trade_card(ticker=unified_top or None, force_refresh=True)
        )
    cached = _load_json(TRADE_CARD_CACHE)
    cached_sym = _normalize_ticker(cached.get('ticker'))
    cached_src = _normalize_ticker(cached.get('levels_source_ticker') or cached_sym)
    stale_cache = (
        cached.get('session_date') != _today()
        or not cached.get('ticker')
        or cached_sym != cached_src
        or (unified_top and cached_sym != unified_top)
    )
    if stale_cache:
        return apply_tradecard_safety_gates(
            build_trade_card(ticker=unified_top or None, force_refresh=True)
        )
    cached.setdefault('paper_only', True)
    return apply_tradecard_safety_gates(cached)
