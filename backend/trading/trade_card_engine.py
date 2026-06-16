"""
Personal intraday trade card engine — Stage 50N.

News-first catalyst radar, then scanner/anomaly + confluence inputs.
Paper-only observation card. Never places orders or emits blind BUY/SELL.
"""

from __future__ import annotations

import json
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
})

MIN_RR = 1.5
MIN_VOLUME_RATIO = 0.8
MAX_SL_PCT = 4.5
EXTENDED_MOVE_PCT = 8.0
ENTRY_MISSED_MOVE_PCT = 6.5
PAPER_ONLY = True


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

    if sl_pct > MAX_SL_PCT:
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
        }

    atr = _estimate_atr(price, change_pct, volume_ratio)
    entry_low = round(price - atr * 0.2, 2)
    entry_high = round(price + atr * 0.08, 2)
    stop = round(price - atr * 1.15, 2)
    target_1 = round(price + atr * 2.0, 2)
    target_2 = round(price + atr * 3.0, 2)

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
    if not force_refresh and TRADE_CARD_CACHE.is_file():
        cached = _load_json(TRADE_CARD_CACHE)
        if (
            cached.get('session_date') == session_date
            and cached.get('ticker')
            and not ticker
            and cached.get('status') in VALID_STATUSES
        ):
            cached.setdefault('paper_only', True)
            return cached

    scanner = _load_json(SCANNER_FILE)
    intel = _load_json(INTEL_FILE)
    registry = _avoid_registry()

    catalyst_ticker: Optional[str] = None
    pick_reason = 'top_scanner'
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

    status = 'NO_TRADE'
    reason_parts: list[str] = []

    if missed:
        status = 'ENTRY_MISSED'
        reason_parts.extend(missed_reasons)
    elif rr < MIN_RR:
        status = 'NO_TRADE'
        reason_parts.append(f'Risk/reward {rr:.2f} below minimum {MIN_RR}')
    elif volume_ratio < MIN_VOLUME_RATIO:
        status = 'WAIT_FOR_VOLUME'
        reason_parts.append(f'Volume participation {volume_ratio:.1f}x below threshold')
    elif abs(change_pct) >= EXTENDED_MOVE_PCT:
        status = 'WAIT_FOR_PULLBACK'
        reason_parts.append(f'Extended {change_pct:+.1f}% — wait for pullback toward entry zone')
    else:
        status = 'VALID_ENTRY'
        reason_parts.append('Price/volume/structure align for paper watch entry')

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
        'capital_plan': 'Paper only — risk 0.5–1R on manual entry if confirmed; no auto execution.',
        'reason': '; '.join(reason_parts)[:240],
        'invalid_if': f"Close below {plan['stop_loss']:.2f} or participation drops below {MIN_VOLUME_RATIO}x",
        'exit_rule': f"Partial at {plan['target_1']:.2f}; runner toward {plan['target_2']:.2f} while above VWAP",
        'confidence': _confidence_label(conf_score),
        'paper_only': True,
        'change_percent': round(change_pct, 2),
        'volume_ratio': round(volume_ratio, 2),
    }

    if persist:
        TRADE_CARD_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TRADE_CARD_CACHE.write_text(json.dumps(card, indent=2), encoding='utf-8')
    return card


def get_trade_card(*, rebuild: bool = False) -> dict[str, Any]:
    if rebuild or not TRADE_CARD_CACHE.is_file():
        return build_trade_card(force_refresh=True)
    cached = _load_json(TRADE_CARD_CACHE)
    if cached.get('session_date') == _today() and cached.get('ticker'):
        cached.setdefault('paper_only', True)
        return cached
    return build_trade_card(force_refresh=True)
