"""
Alert quality filters (Stage 46H).

Open setup confidence tightening, emergency macro dedupe, clickbait filtering.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
EMERGENCY_STATE_FILE = get_data_path('emergency_macro_dedupe_state.json')

EMERGENCY_DEDUPE_MINUTES = 75
EMERGENCY_MIN_CONFIDENCE = 0.75

CLICKBAIT_PATTERNS = (
    r'do you own',
    r'are you holding',
    r"what'?s behind",
    r'you won\'?t believe',
    r'shocking',
    r'must read',
    r'click here',
)

THEME_KEYWORDS = {
    'market_crash': ('market crash', 'sensex crash', 'nifty crash', 'broader market crash', 'indices crash'),
    'it_crash': ('it stocks crash', 'it sector crash', 'tech crash', 'nifty it'),
    'single_stock': ('shares plunge', 'stock crashes', 'single stock', 'shares tank'),
    'macro_policy': ('rbi', 'sebi', 'rate hike', 'rate cut', 'budget', 'fii outflow'),
    'geopolitical': ('war', 'sanction', 'conflict', 'emergency'),
}

DIRECT_IMPACT_KEYWORDS = (
    'nifty', 'sensex', 'bank nifty', 'market halt', 'circuit', 'fii', 'dii',
    'rbi', 'sebi', 'sector', 'index', 'broader market', 'banking', 'it sector',
)

INDIA_RELEVANCE_KEYWORDS = DIRECT_IMPACT_KEYWORDS + (
    'india', 'indian', 'nse', 'bse', 'rupee', 'inr', 'mpc', 'repo rate',
)

GENERIC_GLOBAL_ONLY = (
    'wall street', 'dow jones', 'nasdaq', 's&p 500', 'fed chair', 'us jobs',
    'european markets', 'china markets', 'japan markets',
)

RBI_SURPRISE_KEYWORDS = (
    'surprise', 'unexpected', 'hike', 'cut', 'emergency', 'out of turn',
    'deviation', 'shock', 'unscheduled',
)

BROAD_MACRO_KEYWORDS = (
    'nifty', 'sensex', 'bank nifty', 'broader market', 'market crash', 'indices',
    'banking sector', 'it sector', 'sector-wide', 'sector wide', 'fii outflow',
    'circuit', 'market halt', 'repo rate', 'mpc', 'rbi policy', 'rate hike', 'rate cut',
)

SINGLE_STOCK_MACRO_PATTERNS = (
    r'\bsebi\b.*\b(warning|probe|fine|penalty|investigation)\b',
    r'\b(shares?|stock)\s+(plunge|crash|tank|sink)\b',
    r'\b(warning|probe|fine)\b.*\b(shares?|stock)\b',
)


def _log(tag: str, msg: str) -> None:
    print(f'[{tag}] {msg}', flush=True)


def _now() -> datetime:
    return datetime.now(IST)


def _load_emergency_state() -> dict:
    if not EMERGENCY_STATE_FILE.is_file():
        return {'themes': {}, 'headlines': {}}
    try:
        data = json.loads(EMERGENCY_STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'themes': {}, 'headlines': {}}
    except (OSError, json.JSONDecodeError):
        return {'themes': {}, 'headlines': {}}


def _save_emergency_state(state: dict) -> None:
    atomic_write_json(EMERGENCY_STATE_FILE, state)


def normalize_headline(headline: str) -> str:
    text = str(headline or '').lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text[:200]


def classify_emergency_theme(headline: str) -> str:
    norm = normalize_headline(headline)
    for theme, keywords in THEME_KEYWORDS.items():
        if any(k in norm for k in keywords):
            return theme
    if any(w in norm for w in ('crash', 'plunge', 'tank', 'selloff', 'meltdown')):
        return 'market_crash'
    return 'general_macro'


def is_clickbait_headline(headline: str) -> bool:
    lower = str(headline or '').lower()
    return any(re.search(pat, lower) for pat in CLICKBAIT_PATTERNS)


def is_scheduled_rbi_mpc(headline: str) -> bool:
    lower = str(headline or '').lower()
    if 'rbi' not in lower and 'mpc' not in lower and 'repo' not in lower:
        return False
    calendar_words = ('calendar', 'scheduled', 'meeting today', 'policy meet', 'mpc meet')
    return any(w in lower for w in calendar_words) and not any(w in lower for w in RBI_SURPRISE_KEYWORDS)


def has_india_market_relevance(headline: str, item: Optional[dict] = None) -> bool:
    """India/Nifty/sector impact — blocks generic global-only headlines."""
    lower = str(headline or '').lower()
    if any(k in lower for k in INDIA_RELEVANCE_KEYWORDS):
        return True
    if has_direct_market_impact(headline, item):
        return True
    if item and (item.get('sectors') or item.get('affected_sectors')):
        return True
    if any(g in lower for g in GENERIC_GLOBAL_ONLY) and not any(
        k in lower for k in ('nifty', 'sensex', 'india', 'rupee', 'fii', 'rbi', 'sebi')
    ):
        return False
    return False


def has_direct_market_impact(headline: str, item: Optional[dict] = None) -> bool:
    lower = str(headline or '').lower()
    if any(k in lower for k in DIRECT_IMPACT_KEYWORDS):
        return True
    if item:
        score = float(item.get('impact_score') or 0)
        if score >= 8.5:
            return True
        sectors = item.get('sectors') or item.get('affected_sectors') or []
        if sectors:
            return True
    return False


def count_open_confirmations(signal: dict, intel: dict, state: dict) -> int:
    """Count strong confirmations beyond raw price move."""
    count = 0
    vol_r = float(signal.get('volume_ratio') or 0)
    chg = abs(float(signal.get('change_percent') or 0))
    strength = str(signal.get('strength', '')).upper()
    sector = str(signal.get('sector') or '')

    if vol_r >= 1.5:
        count += 1
    if chg >= 3.0:
        count += 1
    if strength == 'ULTRA':
        count += 1

    sectors = (intel or {}).get('sector_rotation') or {}
    bullish = [str(s).lower() for s in (sectors.get('bullish') or [])]
    if sector.lower() in bullish:
        count += 1

    disagree = float((state or {}).get('disagreement_score') or 0)
    if disagree < 0.35:
        count += 1

    signals_list = signal.get('signals') or []
    if len(signals_list) >= 2:
        count += 1

    return count


def adjust_open_setup_confidence(
    signal: dict,
    base_confidence: float,
    intel: dict,
    state: dict,
) -> Tuple[float, str, bool, str]:
    """
    Returns (adjusted_confidence, label, watch_only, reason).

    participation uses volume_ratio as proxy.
    """
    participation = float(signal.get('participation') or signal.get('volume_ratio') or 0)
    confirmations = count_open_confirmations(signal, intel, state)
    conf = float(base_confidence)
    watch_only = False
    label = 'OPEN SETUP'
    reason_parts: list[str] = []

    if participation < 0.5:
        watch_only = True
        label = 'OPEN SETUP — WATCH ONLY'
        conf = min(conf, 0.62)
        reason_parts.append('price move strong but participation weak')
    elif participation < 0.7:
        if confirmations < 3:
            conf = min(conf, 0.65)
        reason_parts.append(f'participation {participation:.1f}x below threshold')

    if watch_only:
        reason_parts.append('wait for volume confirmation')
    elif confirmations >= 3:
        reason_parts.append('multiple confirmations aligned')

    reason = '; '.join(reason_parts) if reason_parts else 'standard open filter'
    return round(max(0.2, min(0.95, conf)), 3), label, watch_only, reason


def format_open_setup_alert(
    signal: dict,
    intel: dict,
    state: dict,
    base_confidence: float,
    regime: str,
) -> Tuple[str, float, bool]:
    """Build open setup Telegram text with participation-aware confidence."""
    conf, label, watch_only, reason = adjust_open_setup_confidence(signal, base_confidence, intel, state)
    ticker = signal.get('ticker', '?')
    sector = signal.get('sector', '?')
    direction = str(signal.get('direction', '?')).upper()
    chg = float(signal.get('change_percent') or 0)
    participation = float(signal.get('participation') or signal.get('volume_ratio') or 0)
    price = float(signal.get('price') or 0)
    confirmations = count_open_confirmations(signal, intel, state)

    sector_support = 'yes' if sector.lower() in [
        str(s).lower() for s in ((intel or {}).get('sector_rotation') or {}).get('bullish') or []
    ] else 'weak'

    conf_status = 'WATCH ONLY — weak participation' if watch_only else (
        'Confirmed' if confirmations >= 3 and participation >= 0.7 else 'Awaiting confirmation'
    )

    text = f"""<b>🎯 {label}</b> <code>{regime.replace('_', ' ').upper()}</code>
<b>{ticker}</b> · {direction} MOVE
<b>Price move:</b> {chg:+.2f}% · Rs.{price:,.0f}
<b>Volume/participation:</b> {participation:.1f}x
<b>Sector support:</b> {sector_support} ({sector})
<b>Confirmation:</b> {conf_status}
<b>Confidence:</b> {conf:.0%}
<b>Reason:</b> {reason}
<b>Action:</b> {'wait for volume confirmation' if watch_only else 'watch for entry — confirm after 9:15'}"""
    return text, conf, watch_only


def is_broad_macro_emergency(headline: str, item: Optional[dict] = None) -> bool:
    """True when headline affects index/sector broadly — not a single-stock warning."""
    lower = str(headline or '').lower()
    if any(k in lower for k in BROAD_MACRO_KEYWORDS):
        return True
    if has_direct_market_impact(headline, item):
        sectors = (item or {}).get('sectors') or (item or {}).get('affected_sectors') or []
        if len(sectors) >= 2:
            return True
    return False


def is_stock_specific_risk(headline: str, item: Optional[dict] = None) -> bool:
    """Single-stock regulatory or company warning — downgrade from Emergency Macro."""
    lower = str(headline or '').lower()
    if any(re.search(pat, lower) for pat in SINGLE_STOCK_MACRO_PATTERNS):
        if not is_broad_macro_emergency(headline, item):
            return True
    tickers = (item or {}).get('tickers') or (item or {}).get('symbols') or []
    if isinstance(tickers, list) and len(tickers) == 1 and not is_broad_macro_emergency(headline, item):
        return True
    company_only = (
        any(w in lower for w in ('shares plunge', 'stock crashes', 'shares tank', 'sebi warning'))
        and not any(k in lower for k in ('nifty', 'sensex', 'sector', 'banking sector', 'broader'))
    )
    return company_only


def classify_macro_severity(headline: str, item: Optional[dict] = None) -> str:
    """
    Returns severity class: emergency_macro | stock_specific | generic_skip.
    """
    if is_stock_specific_risk(headline, item):
        return 'stock_specific'
    if is_broad_macro_emergency(headline, item):
        return 'emergency_macro'
    lower = str(headline or '').lower()
    if 'rbi' in lower or 'mpc' in lower or 'repo rate' in lower:
        return 'emergency_macro'
    return 'generic_skip'


def evaluate_emergency_macro(
    headline: str,
    confidence: float,
    *,
    item: Optional[dict] = None,
) -> Tuple[bool, str, str]:
    """
    Returns (should_send, reason, theme).
    Logs EMERGENCY_MACRO_SENT/DEDUPED/SKIPPED via caller.
    """
    theme = classify_emergency_theme(headline)
    norm = normalize_headline(headline)
    conf = float(confidence)
    severity = classify_macro_severity(headline, item)

    if severity == 'stock_specific':
        _log('EMERGENCY_MACRO_SKIPPED', f'reason=stock_specific_risk theme={theme}')
        return False, 'stock_specific', theme

    if severity == 'generic_skip' and not is_broad_macro_emergency(headline, item):
        _log('EMERGENCY_MACRO_SKIPPED', f'reason=generic_headline_downgrade theme={theme}')
        return False, 'generic_downgrade', theme

    if conf < EMERGENCY_MIN_CONFIDENCE:
        _log('EMERGENCY_MACRO_SKIPPED', f'reason=low_confidence theme={theme} conf={conf:.2f}')
        return False, 'low_confidence', theme

    if is_clickbait_headline(headline) and not has_direct_market_impact(headline, item):
        _log('EMERGENCY_MACRO_SKIPPED', f'reason=clickbait theme={theme}')
        return False, 'clickbait', theme

    if is_scheduled_rbi_mpc(headline):
        _log('EMERGENCY_MACRO_SKIPPED', f'reason=rbi_mpc_calendar theme={theme}')
        return False, 'rbi_mpc_calendar', theme

    if not has_india_market_relevance(headline, item):
        _log('EMERGENCY_MACRO_SKIPPED', f'reason=no_india_relevance theme={theme}')
        return False, 'no_india_relevance', theme

    if not has_direct_market_impact(headline, item):
        _log('EMERGENCY_MACRO_SKIPPED', f'reason=no_direct_impact theme={theme}')
        return False, 'no_direct_impact', theme

    state = _load_emergency_state()
    now = _now()
    headlines = state.setdefault('headlines', {})
    themes = state.setdefault('themes', {})

    prev_headline = headlines.get(norm)
    if prev_headline:
        last_at = datetime.fromisoformat(prev_headline['sent_at'])
        if now - last_at < timedelta(minutes=EMERGENCY_DEDUPE_MINUTES):
            _log('EMERGENCY_MACRO_DEDUPED', f'theme={theme} reason=duplicate_headline')
            return False, 'duplicate_headline', theme

    prev_theme = themes.get(theme)
    if prev_theme:
        last_at = datetime.fromisoformat(prev_theme['sent_at'])
        prev_conf = float(prev_theme.get('confidence') or 0)
        if now - last_at < timedelta(minutes=EMERGENCY_DEDUPE_MINUTES):
            if conf <= prev_conf + 0.05:
                _log('EMERGENCY_MACRO_DEDUPED', f'theme={theme} reason=theme_repeat')
                return False, 'theme_repeat', theme

    return True, 'ok', theme


def record_emergency_macro_sent(headline: str, confidence: float, theme: str) -> None:
    state = _load_emergency_state()
    now = _now().isoformat()
    norm = normalize_headline(headline)
    state.setdefault('headlines', {})[norm] = {'sent_at': now, 'confidence': confidence, 'theme': theme}
    state.setdefault('themes', {})[theme] = {'sent_at': now, 'confidence': confidence, 'headline': headline[:120]}
    _save_emergency_state(state)
    _log('EMERGENCY_MACRO_SENT', f'theme={theme}')
