"""
Cross-market correlation engine — rule-based macro transmission signals.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _chg(global_data: dict, *names: str) -> float:
    flat = global_data.get('flat_markets') or {}
    grouped = global_data.get('markets') or {}
    for name in names:
        if name in flat:
            return float(flat[name].get('change_percent') or flat[name].get('change_pct') or 0)
        for group in grouped.values():
            if isinstance(group, dict) and name in group:
                return float(group[name].get('change_percent') or group[name].get('change_pct') or 0)
    return 0.0


def evaluate_cross_market_correlations(global_data: Optional[dict] = None) -> Dict[str, Any]:
    """
    Rule-based correlations for India open and market-close synthesis.
    """
    global_data = global_data if isinstance(global_data, dict) else {}
    nasdaq = _chg(global_data, 'NASDAQ')
    sp = _chg(global_data, 'S&P_500')
    vix = _chg(global_data, 'VIX')
    gold = _chg(global_data, 'GOLD')
    oil = _chg(global_data, 'CRUDE_OIL')
    dxy = _chg(global_data, 'DXY')
    yields = _chg(global_data, 'US_10Y')

    signals: List[Dict[str, Any]] = []
    india_sectors_bullish: List[str] = []
    india_sectors_bearish: List[str] = []
    risk_score = 0.0

    # Gold↑ + DXY↓ + geo stress → safe haven sectors
    geo = global_data.get('geopolitics') or global_data.get('alerts') or []
    geo_stress = len(geo) >= 2 or any(
        k in str(geo[0].get('keywords') or geo[0].get('message') or '').lower()
        for k in ('war', 'iran', 'sanction', 'missile')
    ) if geo else False

    if gold >= 1.0 and dxy <= -0.2 and geo_stress:
        signals.append({
            'rule': 'safe_haven_rotation',
            'narrative': 'Gold strength with dollar softness under geopolitical stress — defensive positioning favored',
            'sectors_bullish': ['GOLD_ETF', 'PHARMA', 'FMCG'],
            'sectors_bearish': ['AVIATION', 'METALS'],
        })
        india_sectors_bullish.extend(['PHARMA', 'FMCG'])
        india_sectors_bearish.extend(['AVIATION'])
        risk_score += 0.25

    # NASDAQ weak + yields↑ → IT/growth warning
    tech_weak = nasdaq <= -0.8 or sp <= -0.6
    yields_up = yields >= 0.15
    if tech_weak and yields_up:
        signals.append({
            'rule': 'growth_rate_pressure',
            'narrative': 'NASDAQ weakness with rising yields — IT and high-beta growth face institutional headwinds',
            'sectors_bullish': ['BANKS', 'ENERGY'],
            'sectors_bearish': ['IT', 'TECH', 'HIGH_BETA'],
        })
        india_sectors_bearish.extend(['IT', 'TECH'])
        risk_score += 0.35

    if vix >= 3:
        signals.append({
            'rule': 'volatility_expansion',
            'narrative': 'Volatility expansion — reduce position size, favor quality over beta',
            'sectors_bearish': ['SMALLCAP', 'HIGH_BETA'],
        })
        risk_score += 0.3

    if oil >= 2:
        signals.append({
            'rule': 'energy_transmission',
            'narrative': 'Crude strength — energy complex supported, aviation and downstream margins pressured',
            'sectors_bullish': ['ENERGY', 'ONGC'],
            'sectors_bearish': ['AVIATION', 'PAINTS'],
        })
        india_sectors_bullish.extend(['ENERGY'])
        india_sectors_bearish.extend(['AVIATION'])

    if dxy >= 0.4 and nasdaq < 0:
        signals.append({
            'rule': 'dollar_fii_headwind',
            'narrative': 'Dollar firmness with weak US equities — FII-sensitive sectors may lag at open',
            'sectors_bearish': ['IT', 'PHARMA', 'METALS'],
        })
        india_sectors_bearish.extend(['IT', 'PHARMA'])
        risk_score += 0.2

    risk_level = 'LOW'
    if risk_score >= 0.75:
        risk_level = 'PANIC'
    elif risk_score >= 0.55:
        risk_level = 'HIGH'
    elif risk_score >= 0.3:
        risk_level = 'MODERATE'

    return {
        'signals': signals,
        'risk_level': risk_level,
        'risk_score': round(risk_score, 2),
        'india_sectors_bullish': sorted(set(india_sectors_bullish))[:8],
        'india_sectors_bearish': sorted(set(india_sectors_bearish))[:8],
        'macro_moves': {
            'nasdaq_pct': nasdaq,
            'sp500_pct': sp,
            'vix_pct': vix,
            'gold_pct': gold,
            'oil_pct': oil,
            'dxy_pct': dxy,
            'yields_pct': yields,
        },
    }
