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
    (r'\belite\s+meta[- ]labeler\b', 'high-conviction confirmation'),
    (r'\belite\s+meta\b', 'high-conviction confirmation'),
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
    (r'\bcrazy\s+volume\b', 'elevated participation'),
    (r'\bultra\s+breakout\b', 'continuation structure'),
    (r'\bscanner\s+hype\b', 'scanner observation'),
    (r'\bScanner\s+High\s+Conviction\s·\s*vol\b', 'Elevated participation'),
    (r'\bScanner\s+(\w+(?:\s+\w+)?)\s·\s*vol\b', r'\1 participation'),
    (r'\bvol\s+([\d.]+)x\b', r'participation \1x'),
    (r'\b([\d.]+)%\s+move\b', r'directional extension \1%'),
    (r'\bmomentum\s+detected\b', 'participation improving'),
    (r'\bbreakdown\b(?!\s+continuation\b)', 'breakdown continuation'),
    (r'\bscanner[- ]ranked\b', 'conditional continuation structure'),
    (r'\bmeta[- ]labeler\s+threshold\b', 'high-conviction threshold'),
    (r'\bhigh-conviction\s+meta[- ]labeler\b', 'high-conviction confirmation'),
    (r'\bmeta[- ]labeler\b', 'confirmation model'),
    (r'\bweak\s+participation\b', 'directional weakness'),
    (r'\bconfirmation\s+pending\b', 'confirmation pending'),
    (r'\bdefensive\s+posture\b', 'defensive posture'),
    (r'\bcapital\s+preservation\b', 'capital preservation'),
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


def dedupe_repeated_phrases(text: str) -> str:
    """Collapse accidental duplicate words/phrases from repeated normalization passes."""
    if not text:
        return text
    out = str(text)
    prev = None
    while prev != out:
        prev = out
        out = re.sub(r'\b(\w+)(\s+\1\b)+', r'\1', out, flags=re.IGNORECASE)
        out = re.sub(
            r'\b([\w-]+(?:\s+[\w-]+){0,3})(\s+\1\b)+',
            r'\1',
            out,
            flags=re.IGNORECASE,
        )
    return out


def dedupe_session_banners(text: str) -> str:
    """Ensure at most one after-hours banner per rendered message."""
    if not text or AFTER_HOURS_HEADER.lower() not in text.lower():
        return text
    marker = '🌙'
    first = text.lower().find('after-hours intelligence mode active')
    if first < 0:
        return text
    head = text[:first]
    tail = text[first:]
    rest = tail
    while True:
        idx = rest.lower().find('after-hours intelligence mode active', 1)
        if idx < 0:
            break
        line_start = rest.rfind('\n', 0, idx) + 1
        line_end = rest.find('\n', idx)
        if line_end < 0:
            rest = rest[:line_start]
        else:
            rest = rest[:line_start] + rest[line_end + 1:]
    return head + rest


def apply_institutional_tone(text: str) -> str:
    """Replace retail phrases with institutional equivalents."""
    if not text:
        return text
    out = str(text)
    for pattern, replacement in PHRASE_MAP:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return dedupe_repeated_phrases(out)


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
    """Bloomberg-style compressed desk note (session banner rendered separately)."""
    del after_hours  # canonical banner via session_notice / after_hours_notice_html only
    regime_line = institutional_regime_label(regime)
    return (
        f"Regime: {regime_line}\n"
        f"Leadership: {leaders}\n"
        f"Risk focus: {risks}\n"
        f"India bias: {apply_institutional_tone(bias)}\n"
        f"Conviction: {confidence}"
    )


def compress_risk_logic(logic: str, *, max_lines: int = 2, max_chars: int = 140) -> str:
    """Hard-truncate risk copy — max N institutional lines per ticker."""
    if not logic:
        return ''
    text = apply_institutional_tone(str(logic).strip())
    chunks = [x.strip() for x in re.split(r'[\n;]+', text) if x.strip()]
    lines: List[str] = []
    for chunk in chunks[:max_lines]:
        sentence = re.split(r'(?<=[.!?])\s+', chunk)[0].strip()
        if len(sentence) > max_chars:
            sentence = sentence[: max_chars - 1].rsplit(' ', 1)[0] + '…'
        if sentence:
            lines.append(sentence)
    if not lines:
        return ''
    return lines[0] if max_lines == 1 else '\n'.join(lines[:max_lines])


def format_scanner_participation(
    strength_label: str,
    *,
    volume_ratio: Optional[float] = None,
    change_pct: Optional[float] = None,
) -> str:
    """Replace retail scanner phrasing with desk-note participation language."""
    label = apply_institutional_tone(str(strength_label or 'Observation').strip())
    if label.lower().endswith('elevated participation'):
        parts = [label]
    else:
        parts = [f'{label} — elevated participation']
    if volume_ratio is not None:
        try:
            vr = float(volume_ratio)
            if vr >= 1.2:
                parts.append(f'volume {vr:.1f}x baseline')
        except (TypeError, ValueError):
            pass
    if change_pct is not None:
        try:
            ch = float(change_pct)
            if abs(ch) >= 0.5:
                tone = 'extension' if ch > 0 else 'weakness'
                parts.append(f'directional {tone} {abs(ch):.1f}%')
        except (TypeError, ValueError):
            pass
    return apply_institutional_tone(' · '.join(parts))


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
            logic = compress_risk_logic(str(r.get('logic') or ''), max_lines=max_lines_per_ticker)
            if sym and sym != 'UNKNOWN':
                bits.append(f'{sym} — {logic}' if logic else sym)
            elif logic:
                bits.append(logic)
    return '\n'.join(bits) if bits else 'Macro transmission risk'


def elite_empty_block() -> str:
    return f"<i>🛡️ {EMPTY_ELITE_MESSAGE}</i>"


def after_hours_notice_html() -> str:
    """Single canonical after-hours banner — use once per message/command."""
    return f"<i>🌙 {AFTER_HOURS_HEADER}</i>\n"


def canonical_session_prefix(runtime_state: Optional[dict] = None) -> str:
    """After-hours banner OR stale snapshot notice — never both."""
    try:
        if runtime_state is None:
            from backend.runtime.runtime_state import get_runtime_state
            runtime_state = get_runtime_state()
        session = (runtime_state or {}).get('session') or {}
        if session.get('after_hours_mode'):
            return after_hours_notice_html()
        fresh = (runtime_state or {}).get('snapshot_freshness') or {}
        if fresh.get('stale'):
            age = fresh.get('age_display') or 'freshness unavailable'
            return f'⚠️ <i>Snapshot stale — {age}</i>\n'
    except Exception:
        pass
    return ''
