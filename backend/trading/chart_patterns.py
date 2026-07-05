"""
Chart pattern detection — Phase 4B.15.

OHLCV-only pattern evidence for opening radar / tradecards.
Support evidence only — no LLM, no image matching.
"""

from __future__ import annotations

import statistics
from typing import Any

STAGE = '4B.15'
MIN_CANDLES = 12
PATTERN_BOOST_CAP = 15
DEFAULT_LOOKBACK = 24


def _safe_float(value: object, default: float | None = None) -> float | None:
    if value in (None, '', '—', '-', 'NA', 'N/A'):
        return default
    try:
        text = str(value).strip().replace(',', '')
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _normalize_candle(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    close = _safe_float(raw.get('close'))
    high = _safe_float(raw.get('high'))
    low = _safe_float(raw.get('low'))
    open_ = _safe_float(raw.get('open'))
    if close is None or high is None or low is None:
        return None
    if open_ is None:
        open_ = close
    volume = _safe_float(raw.get('volume'), 0.0) or 0.0
    ts = str(raw.get('timestamp') or raw.get('date') or '')
    return {
        'timestamp': ts,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }


def load_candles_for_symbol(symbol: str, *, limit: int = DEFAULT_LOOKBACK) -> list[dict[str, Any]]:
    """Load OHLCV candles from historical store; empty list if unavailable."""
    sym = str(symbol or '').strip().upper()
    if not sym:
        return []
    try:
        from backend.storage.historical_market_store import get_prices

        rows = get_prices(market='NSE', ticker=sym, limit=max(MIN_CANDLES, limit))
    except Exception:
        return []
    candles = [c for c in (_normalize_candle(r) for r in rows) if c]
    if len(candles) < MIN_CANDLES:
        return []
    return candles[-limit:]


def _recent_volume_confirmed(candles: list[dict[str, Any]]) -> bool:
    if len(candles) < 8:
        return False
    recent = [c['volume'] for c in candles[-3:]]
    prior = [c['volume'] for c in candles[-11:-3]]
    if not prior or not recent:
        return False
    return statistics.mean(recent) > statistics.mean(prior) * 1.08


def _vwap_confirmed(current_price: float | None, vwap: float | None) -> bool:
    if current_price is None or vwap is None or vwap <= 0:
        return False
    return current_price >= vwap


def _flat_level(values: list[float], tolerance_pct: float = 0.025) -> float | None:
    if len(values) < 3:
        return None
    avg = statistics.mean(values)
    if avg <= 0:
        return None
    spread = (max(values) - min(values)) / avg
    if spread <= tolerance_pct:
        return avg
    return None


def _rising(values: list[float], min_gain_pct: float = 0.015) -> bool:
    if len(values) < 4:
        return False
    return values[-1] > values[0] * (1 + min_gain_pct) and values[-1] >= statistics.mean(values[-3:])


def _falling(values: list[float], min_drop_pct: float = 0.015) -> bool:
    if len(values) < 4:
        return False
    return values[-1] < values[0] * (1 - min_drop_pct) and values[-1] <= statistics.mean(values[-3:])


def _compressing(candles: list[dict[str, Any]]) -> bool:
    if len(candles) < 10:
        return False
    early = candles[-12:-6]
    late = candles[-6:]
    early_range = statistics.mean(c['high'] - c['low'] for c in early)
    late_range = statistics.mean(c['high'] - c['low'] for c in late)
    if early_range <= 0:
        return False
    return late_range <= early_range * 0.75


def _detect_ascending_triangle(
    candles: list[dict[str, Any]],
    current_price: float | None,
    vwap: float | None,
) -> dict[str, Any] | None:
    window = candles[-DEFAULT_LOOKBACK:]
    highs = [c['high'] for c in window]
    lows = [c['low'] for c in window]
    resistance = _flat_level(sorted(highs)[-5:])
    if resistance is None or not _rising(lows):
        return None
    support = min(lows[-6:])
    close = current_price if current_price is not None else window[-1]['close']
    vol_ok = _recent_volume_confirmed(window)
    vwap_ok = _vwap_confirmed(close, vwap)
    near = close >= resistance * 0.985
    breakout = close > resistance * 1.002
    status = 'forming'
    confidence = 55
    reasons: list[str] = ['rising lows against flat resistance']
    risks: list[str] = []
    if breakout:
        status = 'breakout_confirmed' if vol_ok else 'near_breakout'
        confidence = 82 if vol_ok else 70
        reasons.append('close above resistance')
    elif near:
        status = 'near_breakout'
        confidence = 68
        reasons.append('price near triangle resistance')
    if not breakout:
        risks.append('breakout not confirmed yet')
    return {
        'pattern': 'ascending_triangle',
        'label': 'Ascending triangle',
        'confidence': confidence,
        'status': status,
        'breakout_level': round(resistance, 2),
        'support_level': round(support, 2),
        'resistance_level': round(resistance, 2),
        'volume_confirmed': vol_ok,
        'vwap_confirmed': vwap_ok,
        'retest_confirmed': False,
        'risk_flags': risks,
        'reasons': reasons,
    }


def _detect_descending_triangle(
    candles: list[dict[str, Any]],
    current_price: float | None,
    vwap: float | None,
) -> dict[str, Any] | None:
    window = candles[-DEFAULT_LOOKBACK:]
    highs = [c['high'] for c in window]
    lows = [c['low'] for c in window]
    support = _flat_level(sorted(lows)[:5], tolerance_pct=0.03)
    if support is None or not _falling(highs):
        return None
    resistance = max(highs[-6:])
    close = current_price if current_price is not None else window[-1]['close']
    vol_ok = _recent_volume_confirmed(window)
    vwap_ok = _vwap_confirmed(close, vwap)
    breakdown = close < support * 0.998
    upward_break = close > resistance * 1.002
    status = 'forming'
    confidence = 52
    reasons: list[str] = ['falling highs against flat support']
    risks: list[str] = ['descending triangle caution']
    if breakdown:
        status = 'failed_breakout'
        confidence = 75
        risks.append('break below support')
    elif upward_break:
        status = 'breakout_confirmed'
        confidence = 70
        reasons.append('upward breakout from descending triangle')
    return {
        'pattern': 'descending_triangle',
        'label': 'Descending triangle',
        'confidence': confidence,
        'status': status,
        'breakout_level': round(resistance, 2),
        'support_level': round(support, 2),
        'resistance_level': round(resistance, 2),
        'volume_confirmed': vol_ok,
        'vwap_confirmed': vwap_ok,
        'retest_confirmed': False,
        'risk_flags': risks,
        'reasons': reasons,
    }


def _detect_symmetrical_triangle(
    candles: list[dict[str, Any]],
    current_price: float | None,
    vwap: float | None,
) -> dict[str, Any] | None:
    window = candles[-DEFAULT_LOOKBACK:]
    highs = [c['high'] for c in window]
    lows = [c['low'] for c in window]
    if not (_falling(highs) and _rising(lows) and _compressing(window)):
        return None
    resistance = max(highs[-4:])
    support = min(lows[-4:])
    close = current_price if current_price is not None else window[-1]['close']
    vol_ok = _recent_volume_confirmed(window)
    vwap_ok = _vwap_confirmed(close, vwap)
    status = 'near_breakout' if close >= resistance * 0.99 or close <= support * 1.01 else 'forming'
    confidence = 60 if status == 'near_breakout' else 50
    return {
        'pattern': 'symmetrical_triangle',
        'label': 'Symmetrical triangle',
        'confidence': confidence,
        'status': status,
        'breakout_level': round(resistance, 2),
        'support_level': round(support, 2),
        'resistance_level': round(resistance, 2),
        'volume_confirmed': vol_ok,
        'vwap_confirmed': vwap_ok,
        'retest_confirmed': False,
        'risk_flags': ['await directional breakout'],
        'reasons': ['range compression — highs falling, lows rising'],
    }


def _detect_breakout_retest(
    candles: list[dict[str, Any]],
    current_price: float | None,
    vwap: float | None,
) -> dict[str, Any] | None:
    if len(candles) < 14:
        return None
    window = candles[-DEFAULT_LOOKBACK:]
    resistance = max(c['high'] for c in window[:-6])
    post = window[-6:]
    close = current_price if current_price is not None else window[-1]['close']
    vol_ok = _recent_volume_confirmed(window)
    vwap_ok = _vwap_confirmed(close, vwap)
    broke = any(c['close'] > resistance * 1.003 for c in post)
    if not broke:
        return None
    if close < resistance * 0.995:
        return {
            'pattern': 'breakout_retest',
            'label': 'Breakout retest',
            'confidence': 72,
            'status': 'failed_breakout',
            'breakout_level': round(resistance, 2),
            'support_level': round(min(c['low'] for c in post), 2),
            'resistance_level': round(resistance, 2),
            'volume_confirmed': vol_ok,
            'vwap_confirmed': vwap_ok,
            'retest_confirmed': False,
            'risk_flags': ['failed breakout — fell back below resistance'],
            'reasons': ['prior breakout lost'],
        }
    retest_hold = any(
        resistance * 0.985 <= c['low'] <= resistance * 1.015 and c['close'] >= resistance * 0.995
        for c in post[-3:]
    )
    if not retest_hold:
        return None
    return {
        'pattern': 'breakout_retest',
        'label': 'Breakout retest',
        'confidence': 78,
        'status': 'retest_confirmed',
        'breakout_level': round(resistance, 2),
        'support_level': round(resistance * 0.99, 2),
        'resistance_level': round(resistance, 2),
        'volume_confirmed': vol_ok,
        'vwap_confirmed': vwap_ok,
        'retest_confirmed': True,
        'risk_flags': [],
        'reasons': ['old resistance holding as support after breakout'],
    }


def detect_chart_patterns(
    symbol: str,
    candles: list[dict[str, Any]],
    *,
    current_price: float | None = None,
    vwap: float | None = None,
) -> dict[str, Any]:
    """Detect v1 chart patterns from OHLCV candles."""
    sym = str(symbol or '').strip().upper()
    normalized = [c for c in (_normalize_candle(c) for c in (candles or [])) if c]
    if len(normalized) < MIN_CANDLES:
        return {'symbol': sym, 'patterns': [], 'best_pattern': None}

    price = current_price if current_price is not None else normalized[-1]['close']
    detectors = (
        _detect_breakout_retest,
        _detect_ascending_triangle,
        _detect_descending_triangle,
        _detect_symmetrical_triangle,
    )
    patterns: list[dict[str, Any]] = []
    for detector in detectors:
        try:
            found = detector(normalized, price, vwap)
        except Exception:
            found = None
        if found:
            patterns.append(found)

    best = max(patterns, key=lambda p: int(p.get('confidence') or 0)) if patterns else None
    return {'symbol': sym, 'patterns': patterns, 'best_pattern': best}


def has_live_radar_confirmation(row: dict[str, Any]) -> bool:
    """True when live radar/tradecard confirmation exists beyond pattern alone."""
    if bool(row.get('has_catalyst')):
        return True
    if row.get('themes'):
        return True
    if bool(row.get('previous_mover')):
        return True
    if bool(row.get('gainer_promoted')):
        return True
    if bool((row.get('sector_breadth') or {}).get('boost')):
        return True
    if _safe_float(row.get('volume_ratio'), 0.0) >= 1.2:
        return True
    if bool(row.get('above_open')) or bool(row.get('above_vwap')):
        return True
    return False


def pattern_score_delta(
    best_pattern: dict[str, Any] | None,
    *,
    live_confirmed: bool,
) -> tuple[int, list[str], list[str]]:
    """Compute capped score delta and reason/risk phrases."""
    if not best_pattern:
        return 0, [], []
    status = str(best_pattern.get('status') or 'forming')
    pattern_key = str(best_pattern.get('pattern') or '')
    vol_ok = bool(best_pattern.get('volume_confirmed'))
    vwap_ok = bool(best_pattern.get('vwap_confirmed'))
    retest_ok = bool(best_pattern.get('retest_confirmed'))
    label = str(best_pattern.get('label') or pattern_key).lower()
    reasons: list[str] = []
    risks: list[str] = list(best_pattern.get('risk_flags') or [])

    boost = 0
    if status == 'failed_breakout':
        boost = -12
        risks.append('failed breakout')
    elif pattern_key == 'descending_triangle' and status == 'forming' and 'break below support' not in ' '.join(risks):
        boost = -10
        risks.append('descending triangle caution')
    elif status == 'retest_confirmed' and live_confirmed:
        boost = 10
        reasons.append(f'{label} retest confirmed')
    elif status == 'breakout_confirmed' and live_confirmed:
        boost = 12 if vol_ok else 8
        if vwap_ok and boost < 12:
            boost = max(boost, 8)
        reasons.append(f'{label} breakout confirmed')
    elif status == 'near_breakout' and live_confirmed:
        boost = 6
        reasons.append(f'{label} near breakout')
    elif status in ('forming', 'near_breakout') and pattern_key == 'symmetrical_triangle' and live_confirmed:
        boost = 4
        reasons.append(f'{label} compression')
    elif status == 'forming' and live_confirmed:
        boost = 4
        reasons.append(f'{label} forming')

    if boost > 0 and not live_confirmed:
        boost = 0
        reasons = []

    boost = max(-PATTERN_BOOST_CAP, min(PATTERN_BOOST_CAP, boost))
    return boost, reasons[:4], risks[:4]


def pattern_phrase_for_why(best_pattern: dict[str, Any] | None) -> str:
    if not best_pattern:
        return ''
    label = str(best_pattern.get('label') or 'Pattern')
    status = str(best_pattern.get('status') or 'forming').replace('_', ' ')
    return f'{label} {status}'


def apply_pattern_evidence_to_row(
    row: dict[str, Any],
    *,
    scanner_row: dict[str, Any] | None = None,
    candles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach pattern detection and capped score boost to an opening-board row."""
    sym = str(row.get('ticker') or '').strip().upper()
    if not sym or str(row.get('state') or '').upper() == 'REJECTED':
        return row

    candle_list = list(candles) if candles is not None else load_candles_for_symbol(sym)
    if len(candle_list) < MIN_CANDLES:
        return row

    scanner = scanner_row or row.get('scanner_row') or {}
    current_price = _safe_float(scanner.get('price') or scanner.get('close'))
    vwap = _safe_float(scanner.get('vwap'))
    result = detect_chart_patterns(sym, candle_list, current_price=current_price, vwap=vwap)
    best = result.get('best_pattern')
    if not best:
        return row

    live_confirmed = has_live_radar_confirmation(row)
    boost, reasons, risks = pattern_score_delta(best, live_confirmed=live_confirmed)

    updated = dict(row)
    if boost:
        updated['score'] = max(0, int(updated.get('score') or 0) + boost)
    why = list(updated.get('why') or [])
    phrase = pattern_phrase_for_why(best)
    if phrase and live_confirmed and phrase.lower() not in ' '.join(why).lower():
        why.insert(0, phrase)
    updated['why'] = why[:8]
    updated['pattern_boost'] = boost
    updated['chart_pattern'] = str(best.get('label') or '')
    updated['pattern_status'] = str(best.get('status') or '')
    updated['breakout_level'] = best.get('breakout_level')
    updated['pattern_confidence'] = int(best.get('confidence') or 0)
    updated['pattern_reasons'] = list(best.get('reasons') or []) + reasons
    updated['pattern_risks'] = list(dict.fromkeys(list(best.get('risk_flags') or []) + risks))[:6]
    updated['best_pattern'] = best
    updated['above_open'] = bool(row.get('above_open'))
    updated['above_vwap'] = bool(row.get('above_vwap'))
    if risks and not live_confirmed:
        updated['pattern_risks'] = updated['pattern_risks'][:6]
    return updated


def pattern_fields_for_memory(row: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(row or {})
    best = base.get('best_pattern') if isinstance(base.get('best_pattern'), dict) else {}
    return {
        'chart_pattern': str(base.get('chart_pattern') or best.get('label') or ''),
        'pattern_status': str(base.get('pattern_status') or best.get('status') or ''),
        'breakout_level': base.get('breakout_level') if base.get('breakout_level') is not None else best.get('breakout_level'),
        'pattern_confidence': int(base.get('pattern_confidence') or best.get('confidence') or 0),
        'pattern_reasons': list(base.get('pattern_reasons') or best.get('reasons') or [])[:6],
        'pattern_risks': list(base.get('pattern_risks') or best.get('risk_flags') or [])[:6],
    }
