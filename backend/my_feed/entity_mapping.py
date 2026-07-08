"""
Deterministic company/ticker resolver for My Feed (Phase 4B.18G / AstraEdge 52E).

Priority:
1. explicit ticker token in text
2. exact company alias
3. known symbol map
4. high-confidence fuzzy only
5. otherwise unknown — never guess random tickers
"""

from __future__ import annotations

import re
from typing import Any

# Longer phrases first. Hard aliases for common retail shorthand.
COMPANY_ALIAS_RULES: tuple[tuple[str, str, str], ...] = (
    (r'\bstate bank of india\b', 'SBIN', 'State Bank of India'),
    (r'\bsbi bank\b', 'SBIN', 'State Bank of India'),
    (r'\bsbi funds management\b', 'SBIN', 'State Bank of India'),
    (r'\bsbi research\b', 'SBIN', 'State Bank of India'),
    (r'\bsbi dividend yield\b', 'SBIN', 'State Bank of India'),
    (r'\bsbin\b', 'SBIN', 'State Bank of India'),
    (r'(?<![a-z0-9])sbi(?![a-z0-9])', 'SBIN', 'State Bank of India'),
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
    (r'\bbharat electronics\b', 'BEL', 'Bharat Electronics'),
    (r'\bmetropolis healthcare\b', 'METROPOLIS', 'Metropolis Healthcare'),
    (r'\bdixon technologies\b', 'DIXON', 'Dixon Technologies'),
    (r'\bhitachi energy india\b', 'POWERINDIA', 'Hitachi Energy India'),
    (r'\bsiemens energy india\b', 'ENRIN', 'Siemens Energy India'),
    (r'\bh t media\b|\bht media\b', 'HTMEDIA', 'H T Media'),
    (r'\breliance industries\b|\breliance\b', 'RELIANCE', 'Reliance Industries'),
    (r'\btata consultancy services\b|\btcs\b', 'TCS', 'Tata Consultancy Services'),
    (r'\binfosys\b', 'INFY', 'Infosys'),
    (r'\bwipro\b', 'WIPRO', 'Wipro'),
    (r'\bhdfc bank\b', 'HDFCBANK', 'HDFC Bank'),
    (r'\bicici bank\b', 'ICICIBANK', 'ICICI Bank'),
)

# Re-export style compatibility with older entity_mapping consumers.
ENTITY_PHRASE_RULES = COMPANY_ALIAS_RULES

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
    'SBIN': (
        r'\bsbin\b',
        r'\bsbi\b',
        r'\bstate bank of india\b',
        r'\bsbi bank\b',
        r'\bsbi funds management\b',
        r'\bsbi research\b',
    ),
}

ALWAYS_BLOCK_AS_TICKERS = frozenset({
    'CHINA', 'KENYA', 'INDIA', 'USA', 'US', 'UK', 'EU',
    'LOST', 'WINS', 'DEAL', 'PORT', 'PORTS', 'AIRPORT', 'CONTRACT', 'FEED',
    'SBI',  # alias only — resolve to SBIN, never treat bare SBI as NSE symbol token
})

# Tickers that must never be "guessed" from SBI/company text via fuzzy noise.
NEVER_CROSS_MAP_FROM_SBI = frozenset({'IOC', 'KEC', 'NFL', 'ONGC', 'BPCL', 'HPCL'})

GROUP_ENTITY_TICKERS = frozenset({'ADANI_GROUP'})

TICKER_TOKEN_RE = re.compile(r'\b([A-Z]{2,15})\b')


def _lower(text: str) -> str:
    return str(text or '').lower()


def map_entities_from_text(text: str) -> dict[str, Any]:
    """Return ticker/entity overrides from hard phrase rules."""
    blob = _lower(text)
    entities: list[str] = []
    tickers: list[str] = []
    ticker_confidence = 'low'

    for pattern, ticker, entity in COMPANY_ALIAS_RULES:
        if re.search(pattern, blob, flags=re.I):
            if entity not in entities:
                entities.append(entity)
            if ticker not in tickers:
                tickers.append(ticker)
            if ticker in ('ADANIPORTS', 'SBIN', 'HDFCBANK', 'ICICIBANK', 'RELIANCE', 'TCS', 'INFY'):
                ticker_confidence = 'high'
            elif ticker == 'ADANIENT':
                ticker_confidence = 'medium' if ticker_confidence != 'high' else 'high'

    for pattern, entity in ENTITY_ONLY_PATTERNS:
        if re.search(pattern, blob, flags=re.I) and entity not in entities:
            entities.append(entity)

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
        ticker_confidence = 'high'

    if tickers and 'SBIN' in tickers:
        # Hard lock: SBI context never includes IOC/KEC/NFL noise.
        tickers = ['SBIN']
        entities = [e for e in entities if 'State Bank' in e] or ['State Bank of India']
        ticker_confidence = 'high'

    return {
        'tickers': tickers[:4],
        'ticker': tickers[0] if tickers else '',
        'entities': entities[:6],
        'entity': entities[0] if entities else (tickers[0] if tickers else ''),
        'company': entities[0] if entities else '',
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


def _explicit_known_tickers(text: str) -> list[str]:
    """All-caps known NSE tokens literally present in text (not aliases like SBI)."""
    try:
        from backend.my_feed.text_extractor import EXTRA_KNOWN_TICKERS, REJECT_TICKER_WORDS, _known_stock_tickers

        known = set(_known_stock_tickers()) | set(EXTRA_KNOWN_TICKERS)
    except Exception:
        known = set()
        REJECT_TICKER_WORDS = frozenset()

    found: list[str] = []
    for token in TICKER_TOKEN_RE.findall(str(text or '').upper()):
        if token in ALWAYS_BLOCK_AS_TICKERS or token in REJECT_TICKER_WORDS:
            continue
        if token == 'SBI':
            continue
        if token in known and token not in found:
            found.append(token)
    return found


def resolve_company_ticker(text: str, *, candidates: list[str] | None = None) -> dict[str, Any]:
    """
    Deterministic resolver used by /feed before fuzzy extraction.

    Returns tickers, company, confidence, resolver_source.
    """
    blob = str(text or '').strip()
    mapped = map_entities_from_text(blob)
    strong = list(mapped.get('tickers') or [])
    confidence = str(mapped.get('ticker_confidence') or 'low')

    if strong and confidence == 'high':
        return {
            'tickers': strong[:1],
            'ticker': strong[0],
            'company': str(mapped.get('company') or mapped.get('entity') or ''),
            'entity': str(mapped.get('entity') or mapped.get('company') or strong[0]),
            'entities': list(mapped.get('entities') or []),
            'ticker_confidence': 'high',
            'resolver_source': 'exact_company_alias',
            'feed_type_hint': 'company_news',
        }

    explicit = _explicit_known_tickers(blob)
    if explicit:
        # Prefer aliases if present even at medium, then explicit ticker.
        if strong:
            ticker = strong[0]
            company = str(mapped.get('company') or mapped.get('entity') or '')
            return {
                'tickers': [ticker],
                'ticker': ticker,
                'company': company,
                'entity': company or ticker,
                'entities': list(mapped.get('entities') or []),
                'ticker_confidence': 'high',
                'resolver_source': 'known_symbol_map',
                'feed_type_hint': 'company_news',
            }
        return {
            'tickers': explicit[:1],
            'ticker': explicit[0],
            'company': str(mapped.get('company') or mapped.get('entity') or ''),
            'entity': str(mapped.get('entity') or explicit[0]),
            'entities': list(mapped.get('entities') or []),
            'ticker_confidence': 'high',
            'resolver_source': 'explicit_ticker',
            'feed_type_hint': 'company_news',
        }

    if strong:
        return {
            'tickers': strong[:1],
            'ticker': strong[0],
            'company': str(mapped.get('company') or mapped.get('entity') or ''),
            'entity': str(mapped.get('entity') or strong[0]),
            'entities': list(mapped.get('entities') or []),
            'ticker_confidence': confidence if confidence != 'low' else 'medium',
            'resolver_source': 'known_symbol_map',
            'feed_type_hint': 'company_news',
        }

    # Fuzzy only when a single high-quality candidate survives filters.
    filtered = filter_claim_tickers(blob, candidates or [])
    if len(filtered) == 1 and ticker_allowed_in_text(filtered[0], blob):
        return {
            'tickers': filtered[:1],
            'ticker': filtered[0],
            'company': '',
            'entity': filtered[0],
            'entities': [],
            'ticker_confidence': 'medium',
            'resolver_source': 'high_confidence_fuzzy',
            'feed_type_hint': 'company_news',
        }

    return {
        'tickers': [],
        'ticker': '',
        'company': '',
        'entity': '',
        'entities': list(mapped.get('entities') or []),
        'ticker_confidence': 'low',
        'resolver_source': 'unknown',
        'feed_type_hint': '',
    }


def filter_claim_tickers(text: str, candidates: list[str] | None) -> list[str]:
    """Remove fuzzy false positives; prefer entity mapping."""
    mapped = map_entities_from_text(text)
    strong = list(mapped.get('tickers') or [])
    confidence = str(mapped.get('ticker_confidence') or 'low')
    blob = _lower(text)

    if strong and confidence == 'high':
        return strong[:1]
    if strong and (
        any(t.startswith('ADANI') for t in strong)
        or 'SBIN' in strong
        or re.search(r'\badani ports\b|\badani power\b|\badani green\b|\bsbi\b|\bstate bank', blob, flags=re.I)
    ):
        return strong[:1]

    out: list[str] = list(strong)
    sbi_context = bool(re.search(r'\bsbi\b|\bsbin\b|\bstate bank of india\b', blob, flags=re.I))
    for raw in candidates or []:
        sym = str(raw or '').strip().upper()
        if not sym or sym in out:
            continue
        if sym == 'SBI':
            sym = 'SBIN'
        if sbi_context and sym in NEVER_CROSS_MAP_FROM_SBI:
            continue
        if not ticker_allowed_in_text(sym, text):
            continue
        if sym in ALWAYS_BLOCK_AS_TICKERS:
            continue
        out.append(sym)
    if 'SBIN' in out:
        return ['SBIN']
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


MACRO_WIDE_PATTERNS = (
    r'\bnifty\b', r'\bsensex\b', r'\bgift nifty\b',
    r'\bcrude\b', r'\boil (surge|jump|spike|shock)\b', r'\bbrent\b', r'\bwti\b',
    r'\bwar\b', r'\bsanction', r'\bceasefire\b', r'\bgeopolitic', r'\biran\b',
    r'\bstrait of hormuz\b', r'\bhormuz\b',
    r'\brbi (rate|policy|mpc)\b', r'\bfed (rate|hike|cut)\b',
    r'\binflation\b', r'\bbond yield', r'\brisk-?off\b',
    r'\bcurrency (shock|crash)\b', r'\brupee (crash|plunge|fall)\b',
    r'\bbroad market\b', r'\bglobal selloff\b', r'\bmarket crash\b',
)


def looks_like_market_wide_macro(text: str) -> bool:
    blob = _lower(text)
    return any(re.search(p, blob, flags=re.I) for p in MACRO_WIDE_PATTERNS)
