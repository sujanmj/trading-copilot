"""
Institutional market language — replace retail phrasing with professional tone.
Bloomberg-style desk notes for executive summaries.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Internal scanner tier still stored as ULTRA in DB — never surface in user copy
HIGH_CONVICTION_INTERNAL = frozenset({'ULTRA', 'HIGH_CONVICTION', 'HIGH CONVICTION'})

# Retail phrase → institutional replacement (case-insensitive word boundaries where possible)
PHRASE_MAP = [
    (r'\bULTRA\s+bearish\b', 'elevated downside participation'),
    (r'\bULTRA\s+bullish\b', 'directional strength extension'),
    (r'\bULTRA\s+today\b', 'High Conviction leadership today'),
    (r'\bVERY\s+STRONG\b', 'Strong'),
    (r'\bELITE\b', 'High Conviction'),
    (r'\btop\s+movers?\b', 'relative strength leaders'),
    (r'\bmomentum\s+spam\b', 'broad participation extension'),
    (r'\bscanner\s+ULTRA\b', 'High Conviction scanner signal'),
    (r'\bULTRA\s+SIGNALS?\b', 'High Conviction signals'),
    (r'\bULTRA\b', 'High Conviction'),
    (r'\belite\s+threshold\b', 'high-conviction threshold'),
    (r'\belite\s+meta[- ]labeler\b', 'high-conviction meta-labeler'),
    (r'\belite\s+meta\b', 'high-conviction meta-labeler'),
    (r'\bmajor\s+move\b', 'high-volatility continuation'),
    (r'\bmoonshot\b', 'speculative extension'),
    (r'\bwatch\s+low\b', 'Watchlist — Low confidence'),
    (r'\bConf:\s*WATCH\b', 'Status: Watchlist · Confidence: Low'),
    (r'\bWEAK\b', 'Weak'),
    (r'\btop\s+opportunities\b', 'priority setups'),
    (r'\bbull\s+run\b', 'risk-on extension'),
    (r'\bbear\s+market\b', 'risk-off regime'),
    (r'\bcrash\b', 'dislocation event'),
    (r'\bpump\b', 'short-covering rally'),
    (r'\bdump\b', 'institutional selling'),
    (r'\bFOMO\b', 'retail chase risk'),
    (r'\bhot\s+stocks\b', 'leadership names'),
    (r'\bmovers\b', 'relative strength'),
    (r'\bmomentum\s+names\b', 'participation leaders'),
    (r'\brisk\s+off\b', 'defensive positioning'),
    (r'\brisk\s+on\b', 'cyclical accumulation'),
]

SECTOR_TONE = {
    'bullish': 'sector accumulation',
    'bearish': 'sector distribution',
    'neutral': 'balanced sector exposure',
}

EMPTY_ELITE_MESSAGE = (
    'No High Conviction setups detected. Capital Preservation mode active.'
)

AFTER_HOURS_HEADER = 'After-hours intelligence mode active — observation only, no execution framing.'

DISPLAY_TIER_LABELS = {
    'ELITE': 'High Conviction',
    'WATCH': 'Watchlist',
    'AVOID': 'Elevated Risk',
    'MOMENTUM': 'Momentum Candidate',
    'CONFLICT': 'Regime Conflict',
    'PRESERVE': 'Capital Preservation',
}


def is_high_conviction_strength(strength: Optional[str]) -> bool:
    s = str(strength or '').upper().strip()
    return s in HIGH_CONVICTION_INTERNAL or s.startswith('VERY STRONG')


def normalize_strength_label(strength: Optional[str], direction: Optional[str] = None) -> str:
    """Map legacy tiers to: High Conviction, Strong, Moderate, Weak."""
    s = str(strength or '').upper().strip()
    d = str(direction or '').upper().strip()
    if s in HIGH_CONVICTION_INTERNAL or s == 'ELITE':
        return 'High Conviction'
    if s.startswith('VERY STRONG') or s == 'STRONG':
        return 'Strong'
    if s == 'MODERATE':
        return 'Moderate'
    if s == 'WEAK':
        return 'Weak'
    if s == 'ULTRA':
        return 'High Conviction'
    out = apply_institutional_tone(s.replace('_', ' '))
    if 'BEAR' in d and out == 'Strong':
        return 'Strong bearish'
    if 'BULL' in d and out == 'Strong':
        return 'Strong bullish'
    return out


def tier_display_label(tier: Optional[str]) -> str:
    key = str(tier or '').upper().strip()
    if key == 'WATCH':
        return 'Watchlist'
    return DISPLAY_TIER_LABELS.get(key, tier or 'Watchlist')


def confidence_display_label(confidence: Optional[str]) -> str:
    """Map raw confidence bands to institutional labels."""
    key = str(confidence or '').upper().strip()
    mapping = {
        'HIGH': 'High',
        'MEDIUM': 'Medium',
        'MODERATE': 'Medium',
        'LOW': 'Low',
        'WATCH': 'Low',
        'SPECULATIVE': 'Low',
    }
    return mapping.get(key, key.title() if key else 'Medium')


def format_signal_status_line(
    item: Optional[dict] = None,
    *,
    tier: Optional[str] = None,
    confidence: Optional[str] = None,
) -> str:
    """Separate status tier from confidence — never 'Conf: WATCH LOW'."""
    o = item if isinstance(item, dict) else {}
    tier_key = str(tier or o.get('display_tier') or o.get('action') or 'WATCH').upper()
    conf_raw = confidence or o.get('display_confidence') or o.get('confidence') or 'MEDIUM'
    conf_key = str(conf_raw).upper().strip()
    if conf_key == 'WATCH' or (tier_key == 'WATCH' and conf_key in ('HIGH', 'WATCH')):
        status = 'Watchlist'
        conf_label = 'Low' if conf_key in ('WATCH', 'LOW', 'SPECULATIVE') else confidence_display_label(conf_key)
    elif tier_key == 'ELITE':
        status = 'High Conviction'
        conf_label = confidence_display_label(conf_key if conf_key != 'WATCH' else 'HIGH')
    elif tier_key == 'AVOID':
        status = 'Elevated Risk'
        conf_label = confidence_display_label(conf_key)
    else:
        status = tier_display_label(tier_key)
        conf_label = confidence_display_label(conf_key)
    return f'Status: {status} · Confidence: {conf_label}'


def apply_institutional_tone(text: str) -> str:
    """Replace retail phrases with institutional equivalents."""
    if not text:
        return text
    out = str(text)
    for pattern, replacement in PHRASE_MAP:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def institutional_sector_line(bullish: List[str], bearish: List[str]) -> str:
    bull = ', '.join(bullish[:4]) if bullish else 'none dominant'
    bear = ', '.join(bearish[:4]) if bearish else 'none dominant'
    return (
        f"Leadership concentration: {bull}\n"
        f"Risk rotation / distribution: {bear}"
    )


def institutional_regime_label(regime: str) -> str:
    mapping = {
        'bullish_trend': 'risk-on trend',
        'panic_volatile': 'volatility expansion',
        'macro_uncertainty': 'macro headline risk',
        'sideways': 'range-bound consolidation',
        'regime_transition': 'regime transition',
    }
    key = str(regime or '').lower().replace(' ', '_')
    return mapping.get(key, apply_institutional_tone(regime.replace('_', ' ')))


def format_executive_summary(
    *,
    regime: str,
    leaders: str,
    risks: str,
    bias: str,
    confidence: str,
    after_hours: bool = False,
) -> str:
    """Bloomberg-style compressed desk note."""
    regime_line = institutional_regime_label(regime)
    header = AFTER_HOURS_HEADER if after_hours else 'Desk note — session intelligence'
    return (
        f"{header}\n"
        f"Regime: {regime_line}\n"
        f"Leadership: {leaders}\n"
        f"Risk focus: {risks}\n"
        f"India bias: {apply_institutional_tone(bias)}\n"
        f"Conviction: {confidence}"
    )


def format_compressed_leaders(sectors: Dict[str, Any]) -> str:
    sectors = sectors if isinstance(sectors, dict) else {}
    bullish = sectors.get('bullish') or []
    if not bullish:
        return 'Leadership not yet concentrated'
    leaders = ', '.join(str(s) for s in bullish[:4])
    return apply_institutional_tone(f"Leadership concentration: {leaders}")


def format_compressed_risks(risks: List[Any], *, max_lines_per_ticker: int = 2) -> str:
    if not risks:
        return 'Overnight headline risk — monitor liquidity'
    bits = []
    for r in risks[:3]:
        if isinstance(r, dict):
            sym = str(r.get('symbol') or '').strip()
            logic_raw = str(r.get('logic') or '')
            logic_lines = [x.strip() for x in logic_raw.splitlines() if x.strip()][:max_lines_per_ticker]
            logic = apply_institutional_tone(' '.join(logic_lines)[:160])
            if sym and sym != 'UNKNOWN':
                bits.append(f'{sym} — {logic}' if logic else sym)
            elif logic:
                bits.append(logic)
    return '\n'.join(bits) if bits else 'Macro transmission risk'


def elite_empty_block() -> str:
    return f"<i>🛡️ {EMPTY_ELITE_MESSAGE}</i>"


def after_hours_notice_html() -> str:
    return f"<i>🌙 {AFTER_HOURS_HEADER}</i>\n\n"
