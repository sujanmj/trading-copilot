"""
Tactical trade planner — ATR/volatility-based levels for scanner-led setups.
Distinct from elite ML-validated swing setups.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

MIN_RR = 1.5
MIN_VOLUME_RATIO = 0.8


def _estimate_atr(price: float, change_pct: float, volume_ratio: float) -> float:
    vol_pct = max(0.6, min(6.0, abs(change_pct) * 0.35 + max(1.0, volume_ratio) * 0.25))
    return price * vol_pct / 100.0


def build_tactical_plan(
    item: dict,
    *,
    scanner_row: Optional[dict] = None,
    sector_strength: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Generate entry/SL/targets or WATCH-only when liquidity/RR fails."""
    item = item if isinstance(item, dict) else {}
    scan = scanner_row if isinstance(scanner_row, dict) else {}

    price = float(scan.get('price') or item.get('price') or item.get('last_price') or 0)
    if price <= 0:
        return None

    change_pct = float(scan.get('change_percent') or item.get('change_percent') or 2.0)
    volume_ratio = float(scan.get('volume_ratio') or item.get('volume_ratio') or 1.0)
    atr = _estimate_atr(price, change_pct, volume_ratio)

    entry_low = price - atr * 0.15
    entry_high = price + atr * 0.10
    stop = price - atr * 1.2
    target_1 = price + atr * 2.0
    target_2 = price + atr * 3.2

    risk = max(0.01, price - stop)
    reward = max(0.0, target_1 - price)
    rr = reward / risk if risk else 0.0

    conviction = 'LOW'
    if sector_strength >= 0.75 and volume_ratio >= 2.0:
        conviction = 'HIGH'
    elif sector_strength >= 0.55 or volume_ratio >= 1.2:
        conviction = 'MEDIUM'

    if volume_ratio < MIN_VOLUME_RATIO:
        return {
            'watch_only': True,
            'entry_range': f'{entry_low:.2f}-{entry_high:.2f}',
            'stop_loss': round(stop, 2),
            'target_1': round(target_1, 2),
            'target_2': round(target_2, 2),
            'risk_reward': round(rr, 2),
            'invalidation': f'Liquidity filter — volume ratio {volume_ratio:.1f}x below tactical threshold',
            'conviction': 'LOW',
            'atr': round(atr, 2),
            'tier': 'WATCH',
        }

    if rr < MIN_RR:
        return None

    invalidation = f'Close below {stop:.2f} or momentum fades with sector strength < {sector_strength:.0%}'
    return {
        'watch_only': False,
        'entry_range': f'{entry_low:.2f}-{entry_high:.2f}',
        'stop_loss': round(stop, 2),
        'target_1': round(target_1, 2),
        'target_2': round(target_2, 2),
        'target': round(target_1, 2),
        'risk_reward': round(rr, 2),
        'invalidation': invalidation,
        'conviction': conviction,
        'atr': round(atr, 2),
        'tier': 'TACTICAL',
    }


def attach_tactical_plans(items: list, scanner_index: dict, intel: dict) -> list:
    """Attach tactical_plan + normalized levels to ranked items."""
    sectors = (intel.get('sector_rotation') or {}) if isinstance(intel, dict) else {}
    bullish = {str(s).upper() for s in (sectors.get('bullish') or [])}
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        sym = str(item.get('symbol') or '').upper()
        sector = str(item.get('sector') or '').upper()
        sector_strength = 0.85 if sector in bullish or sym in bullish else 0.45
        plan = build_tactical_plan(item, scanner_row=(scanner_index or {}).get(sym), sector_strength=sector_strength)
        enriched = dict(item)
        if plan:
            enriched['tactical_plan'] = plan
            if not enriched.get('entry_zone'):
                enriched['entry_zone'] = plan.get('entry_range')
            if not enriched.get('stop_loss'):
                enriched['stop_loss'] = plan.get('stop_loss')
            if not enriched.get('target'):
                enriched['target'] = plan.get('target_1')
            enriched['target_2'] = plan.get('target_2')
            enriched['risk_reward'] = plan.get('risk_reward')
            enriched['invalidation'] = plan.get('invalidation')
            enriched['tactical_conviction'] = plan.get('conviction')
            if plan.get('watch_only'):
                enriched['display_tier'] = 'WATCHLIST'
        out.append(enriched)
    return out
