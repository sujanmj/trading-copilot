"""
India next-open engine — US close → Asia → India open bias synthesis.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
OUTPUT_FILE = DATA_DIR / 'india_next_open.json'
GLOBAL_FILE = DATA_DIR / 'global_markets.json'

SECTOR_MAP = {
    'CRUDE_OIL': {'bearish': ['AVIATION', 'PAINTS', 'TYRES'], 'bullish': ['ONGC', 'OIL']},
    'NAT_GAS': {'bearish': ['FERTILIZER'], 'bullish': ['GAIL']},
    'GOLD': {'bullish': ['GOLD_ETF', 'JEWELLERY'], 'bearish': []},
    'DXY': {'bearish': ['IT', 'PHARMA'], 'bullish': ['METAL_IMPORTERS']},
    'VIX': {'bearish': ['HIGH_BETA', 'SMALLCAP'], 'bullish': []},
    'NASDAQ': {'bullish': ['IT', 'TECH'], 'bearish': []},
    'BTC': {'bullish': ['CRYPTO_PROXY'], 'bearish': []},
}


def _load_global() -> dict:
    if not GLOBAL_FILE.exists():
        return {}
    try:
        return json.loads(GLOBAL_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _get_change(global_data: dict, *names: str) -> Optional[float]:
    flat = global_data.get('flat_markets') or {}
    grouped = global_data.get('markets') or {}
    for name in names:
        if name in flat:
            return float(flat[name].get('change_percent') or flat[name].get('change_pct') or 0)
        for group in grouped.values():
            if isinstance(group, dict) and name in group:
                return float(group[name].get('change_percent') or group[name].get('change_pct') or 0)
    return None


def _headline_from_geo(alerts: List[dict]) -> str:
    if not alerts:
        return ''
    top = alerts[0]
    msg = str(top.get('message') or '')[:120]
    keys = top.get('keywords') or []
    if any(k in keys for k in ('iran', 'war', 'sanction')):
        return f'{msg} → gold/oil volatility risk, Indian aviation/metals sensitive'
    if any(k in keys for k in ('tariff', 'trump', 'china')):
        return f'{msg} → trade-sensitive sectors (auto, metals, IT) on watch'
    if any(k in keys for k in ('fed', 'rate')):
        return f'{msg} → FII flow and rate-sensitive banks/NBFCs in focus'
    return msg


def _build_global_snapshot(global_data: dict) -> Dict[str, Any]:
    nasdaq = _get_change(global_data, 'NASDAQ') or 0
    sp = _get_change(global_data, 'S&P_500') or 0
    vix = _get_change(global_data, 'VIX') or 0
    gold = _get_change(global_data, 'GOLD') or 0
    oil = _get_change(global_data, 'CRUDE_OIL') or 0
    dxy = _get_change(global_data, 'DXY') or 0
    nikkei = _get_change(global_data, 'NIKKEI') or 0
    hs = _get_change(global_data, 'HANG_SENG') or 0
    return {
        'us_close': {'nasdaq_pct': nasdaq, 'sp500_pct': sp, 'vix_pct': vix},
        'asian_futures': {'nikkei_pct': nikkei, 'hang_seng_pct': hs},
        'commodities': {'gold_pct': gold, 'oil_pct': oil},
        'overnight_vol': {'vix_pct': vix, 'dxy_pct': dxy},
        'lines': [
            f"US: Nasdaq {nasdaq:+.2f}% · S&P {sp:+.2f}% · VIX {vix:+.2f}%",
            f"Asia: Nikkei {nikkei:+.2f}% · Hang Seng {hs:+.2f}%",
            f"Commodities: Gold {gold:+.2f}% · Oil {oil:+.2f}%",
        ],
    }


def _gap_probability(open_bias_score: float, vix: float, us_bias: float) -> Dict[str, Any]:
    gap_up = min(0.92, max(0.08, 0.5 + open_bias_score * 0.35 - max(0, vix - 2) * 0.05))
    gap_down = min(0.92, max(0.08, 0.5 - open_bias_score * 0.35 + max(0, vix - 2) * 0.06))
    if us_bias >= 0.5:
        gap_up += 0.08
    if us_bias <= -0.5:
        gap_down += 0.08
    total = gap_up + gap_down
    gap_up /= total
    gap_down /= total
    label = 'GAP_UP_LIKELY' if gap_up >= 0.58 else ('GAP_DOWN_LIKELY' if gap_down >= 0.58 else 'MIXED_OPEN')
    return {
        'gap_up_probability': round(gap_up, 2),
        'gap_down_probability': round(gap_down, 2),
        'gap_probability_label': label,
    }


def build_india_next_open_report(global_data: Optional[dict] = None) -> Dict[str, Any]:
    """Deterministic overnight impact synthesis for India open (5:00 AM IST job)."""
    global_data = global_data or _load_global()
    sentiment = global_data.get('sentiment') or {}
    usa = sentiment.get('usa') or {}
    asia = sentiment.get('asia') or {}
    geo = global_data.get('geopolitics') or global_data.get('alerts') or []

    nasdaq = _get_change(global_data, 'NASDAQ') or 0
    sp = _get_change(global_data, 'S&P_500') or 0
    vix = _get_change(global_data, 'VIX') or 0
    gold = _get_change(global_data, 'GOLD') or 0
    oil = _get_change(global_data, 'CRUDE_OIL') or 0
    dxy = _get_change(global_data, 'DXY') or 0
    nikkei = _get_change(global_data, 'NIKKEI') or 0
    hs = _get_change(global_data, 'HANG_SENG') or 0

    try:
        from backend.intelligence.cross_market_correlation import evaluate_cross_market_correlations
        correlation = evaluate_cross_market_correlations(global_data)
    except Exception:
        correlation = {'risk_level': 'MODERATE', 'india_sectors_bullish': [], 'india_sectors_bearish': []}

    us_bias = (nasdaq * 0.4 + sp * 0.35 + (usa.get('average_change') or 0) * 0.25)
    asia_bias = (nikkei * 0.5 + hs * 0.5) if (nikkei or hs) else (asia.get('average_change') or 0)
    macro_penalty = 0.0
    if vix >= 5:
        macro_penalty -= 0.4
    elif vix >= 2:
        macro_penalty -= 0.15
    if oil >= 2:
        macro_penalty -= 0.2
    if dxy >= 0.5:
        macro_penalty -= 0.1

    open_bias_score = us_bias * 0.55 + asia_bias * 0.35 + macro_penalty
    if open_bias_score >= 0.35:
        open_bias = 'GAP_UP_BIAS'
        india_outlook = 'BULLISH'
    elif open_bias_score <= -0.35:
        open_bias = 'GAP_DOWN_BIAS'
        india_outlook = 'BEARISH'
    else:
        open_bias = 'FLAT_TO_MIXED'
        india_outlook = 'NEUTRAL'

    sectors_at_risk: List[str] = list(correlation.get('india_sectors_bearish') or [])
    sectors_supported: List[str] = list(correlation.get('india_sectors_bullish') or [])
    for symbol, mapping in SECTOR_MAP.items():
        ch = _get_change(global_data, symbol) or 0
        if ch >= 1.5:
            sectors_supported.extend(mapping.get('bullish') or [])
        if ch <= -1.5:
            sectors_at_risk.extend(mapping.get('bearish') or [])
        if ch >= 2 and mapping.get('bearish'):
            sectors_at_risk.extend(mapping.get('bearish') or [])

    warnings = []
    if vix >= 3:
        warnings.append(f'VIX elevated ({vix:+.1f}%) — reduce size, widen stops')
    if abs(oil) >= 2:
        warnings.append(f'Oil move ({oil:+.1f}%) — energy/aviation transmission risk')
    if abs(gold) >= 1:
        warnings.append(f'Gold ({gold:+.1f}%) — safe-haven / geopolitical stress signal')
    if abs(dxy) >= 0.4:
        warnings.append(f'Dollar ({dxy:+.1f}%) — FII-sensitive sectors may lag')

    headline = _headline_from_geo(geo)
    global_snapshot = _build_global_snapshot(global_data)
    gap = _gap_probability(open_bias_score, vix, us_bias)
    _risk_levels = ['LOW', 'MODERATE', 'HIGH', 'PANIC']
    risk_score = correlation.get('risk_level') or 'MODERATE'
    if risk_score not in _risk_levels:
        risk_score = 'MODERATE'
    if vix >= 5 and open_bias_score < -0.2:
        risk_score = 'PANIC'
    elif vix >= 3:
        risk_score = _risk_levels[max(_risk_levels.index(risk_score), _risk_levels.index('HIGH'))]

    india_impact = {
        'sectors_affected': sorted(set(sectors_at_risk + sectors_supported))[:10],
        'bullish_sectors': sorted(set(sectors_supported))[:8],
        'risk_sectors': sorted(set(sectors_at_risk))[:8],
        'macro_pressure': warnings[:4] or ['No acute macro pressure flagged'],
        'correlation_signals': [s.get('narrative', '')[:100] for s in (correlation.get('signals') or [])[:3]],
    }

    narrative_parts = []
    if headline:
        narrative_parts.append(headline)
    narrative_parts.append(
        f"US close bias {us_bias:+.2f}% · Asia {asia_bias:+.2f}% → India {open_bias.replace('_', ' ').lower()}"
    )
    if oil >= 2 and gold >= 1:
        narrative_parts.append('Safe-haven bid with energy volatility — defensive positioning vs cyclicals')

    report = {
        'generated_at': datetime.now(IST).isoformat(),
        'india_open_bias': open_bias,
        'india_outlook': india_outlook,
        'open_bias_score': round(open_bias_score, 2),
        'global_snapshot': global_snapshot,
        'india_impact': india_impact,
        'risk_score': risk_score,
        'gap_probability': gap,
        'sectors_at_risk': sorted(set(sectors_at_risk))[:8],
        'sectors_supported': sorted(set(sectors_supported))[:8],
        'macro_volatility_warnings': warnings,
        'macro_moves': global_snapshot.get('us_close', {}),
        'geopolitical_headline': headline,
        'narrative': ' '.join(narrative_parts)[:500],
        'expected_gap_behavior': open_bias,
        'global_sentiment': sentiment,
        'cross_market_correlation': correlation,
    }
    atomic_write_json(OUTPUT_FILE, report)
    return report
