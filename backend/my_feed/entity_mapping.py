"""
My Feed entity → ticker mapping overrides (Stage 50Y).

Hard rules run before fuzzy ticker detection to avoid PTC/PARAS/IDEA/CHINA false positives.
"""

from __future__ import annotations

import re
from typing import Any

# Longer phrases first
ENTITY_PHRASE_RULES: tuple[tuple[str, str, str], ...] = (
    (r'adani ports and special economic zone|adani ports and sez|\bapsez\b', 'ADANIPORTS', 'Adani Ports and Special Economic Zone'),
    (r'\badani ports\b', 'ADANIPORTS', 'Adani Ports and Special Economic Zone'),
    (r'\badani power\b', 'ADANIPOWER', 'Adani Power'),
    (r'\badani green\b', 'ADANIGREEN', 'Adani Green Energy'),
    (r'\bptc india\b|\bpower trading corporation\b', 'PTC', 'PTC India'),
    (r'\bparas defence\b|\bparas defense\b', 'PARAS', 'Paras Defence'),
    (r'\bvodafone idea\b', 'IDEA', 'Vodafone Idea'),
    (r'\badani enterprises\b', 'ADANIENT', 'Adani Enterprises'),
    (r'\badani airports?\b|\badani airport proposal\b|\badani group\b', 'ADANIENT', 'Adani Group'),
    (r'\badani\b', 'ADANIENT', 'Adani Group'),
)

ENTITY_ONLY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r'china communications construction|\bcccc\b', 'China Communications Construction Co'),
    (r'\bkenya airport\b|\bkenya aviation\b', 'Kenya airport proposal'),
    (r'\bchina\b.*\bkenya\b|\bkenya\b.*\bchina\b', 'China / Kenya airport proposal'),
)

CONDITIONAL_TICKER_EVIDENCE: dict[str, tuple[str, ...]] = {
    'PTC': (
        r'\bptc india\b',
        r'\bpower trading corporation\b',
        r'\bptc\b.*\bpower trading\b',
    ),
    'PARAS': (
        r'\bparas defence\b',
        r'\bparas defense\b',
        r'\bparasdefence\b',
    ),
    'IDEA': (
        r'\bvodafone idea\b',
        r'\bidea cellular\b',
    ),
}

ALWAYS_BLOCK_AS_TICKERS = frozenset({
    'CHINA', 'KENYA', 'INDIA', 'USA', 'US', 'UK', 'EU',
    'LOST', 'WINS', 'DEAL', 'PORT', 'PORTS', 'AIRPORT', 'CONTRACT', 'FEED',
})

GROUP_ENTITY_TICKERS = frozenset({'ADANI_GROUP'})


def _lower(text: str) -> str:
    return str(text or '').lower()


def map_entities_from_text(text: str) -> dict[str, Any]:
    """Return ticker/entity overrides from hard phrase rules."""
    blob = _lower(text)
    entities: list[str] = []
    tickers: list[str] = []
    ticker_confidence = 'low'

    for pattern, ticker, entity in ENTITY_PHRASE_RULES:
        if re.search(pattern, blob, flags=re.I):
            if entity not in entities:
                entities.append(entity)
            if ticker not in tickers:
                tickers.append(ticker)
            if ticker == 'ADANIPORTS':
                ticker_confidence = 'high'
            elif ticker == 'ADANIENT':
                ticker_confidence = 'medium'

    for pattern, entity in ENTITY_ONLY_PATTERNS:
        if re.search(pattern, blob, flags=re.I) and entity not in entities:
            entities.append(entity)

    # Kenya / China airport competition — entity focus, not Indian listco unless Adani named
    if re.search(r'\bkenya\b.*\bairport\b|\bairport\b.*\bkenya\b', blob, flags=re.I):
        if 'Kenya airport proposal' not in entities:
            entities.append('Kenya airport proposal')
        if 'adani' in blob and 'Adani Group' not in entities:
            entities.append('Adani Group')
        if re.search(r'\bshelved\b|\blost\b|\bcancel', blob, flags=re.I) and 'ADANIENT' not in tickers:
            tickers = ['ADANIENT'] if 'adani' in blob else tickers
            ticker_confidence = 'low'

    if tickers and 'ADANIPORTS' in tickers:
        tickers = ['ADANIPORTS']
        entities = [e for e in entities if 'Adani Ports' in e] or ['Adani Ports and Special Economic Zone']
        entity = entities[0]
        ticker_confidence = 'high'

    return {
        'tickers': tickers[:4],
        'ticker': tickers[0] if tickers else '',
        'entities': entities[:6],
        'entity': entities[0] if entities else (tickers[0] if tickers else ''),
        'ticker_confidence': ticker_confidence,
    }


def ticker_allowed_in_text(ticker: str, text: str) -> bool:
    sym = str(ticker or '').strip().upper()
    if not sym:
        return False
    if sym in ALWAYS_BLOCK_AS_TICKERS:
        return False
    patterns = CONDITIONAL_TICKER_EVIDENCE.get(sym)
    if patterns:
        blob = _lower(text)
        return any(re.search(p, blob, flags=re.I) for p in patterns)
    return True


def filter_claim_tickers(text: str, candidates: list[str] | None) -> list[str]:
    """Remove fuzzy false positives; prefer entity mapping."""
    mapped = map_entities_from_text(text)
    strong = list(mapped.get('tickers') or [])
    if strong and (
        any(t.startswith('ADANI') for t in strong)
        or re.search(r'\badani ports\b|\badani power\b|\badani green\b', _lower(text), flags=re.I)
    ):
        return strong[:4]

    out: list[str] = list(strong)
    for raw in candidates or []:
        sym = str(raw or '').strip().upper()
        if not sym or sym in out:
            continue
        if not ticker_allowed_in_text(sym, text):
            continue
        if sym in ALWAYS_BLOCK_AS_TICKERS:
            continue
        out.append(sym)
    return out[:4]


def infer_event_type_from_text(text: str, *, headline: str = '') -> str:
    blob = _lower(f'{text} {headline}')
    if re.search(r'\badani ports\b.*\b(invest|investment|capex|capacity|ai|technology)\b', blob, flags=re.I):
        return 'CAPEX / AI_TECH_UPGRADE / CAPACITY_EXPANSION'
    if re.search(r'\bkenya\b.*\bairport\b|\bairport\b.*\bkenya\b', blob, flags=re.I):
        if re.search(r'\bshelved\b|\bshelve\b', blob, flags=re.I):
            return 'CONTRACT_LOSS / SHELVED_PROPOSAL / INFRA_COMPETITION'
        if re.search(r'\blost\b|\bcancel|revok', blob, flags=re.I):
            return 'CONTRACT_LOSS / REGULATORY_RISK'
        return 'INFRA_COMPETITION'
    return ''


def refine_side_from_headline(text: str, *, headline: str = '', default: str = 'NEUTRAL') -> str:
    blob = _lower(f'{text} {headline}')
    if re.search(r'\binvest|\bcapex\b|\bcapacity expansion\b|\btechnology upgrade\b|\bai\b', blob, flags=re.I):
        if 'adani ports' in blob or 'adani port' in blob:
            return 'BULLISH'
    if re.search(r'\bshelved\b|\blost\b|\bcancel|revok|competition\b.*\bwins\b', blob, flags=re.I):
        if 'adani' in blob or 'kenya' in blob:
            return 'RISK'
    return default
