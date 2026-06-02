"""
External evidence classifier (Stage 39C / 39D).

Separates broker prediction candidates from stock news, market context,
macro context, and unrelated content. No fake data or bullish conversion
of neutral news.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.utils.config import DATA_DIR

CLASSIFICATIONS = frozenset({
    'broker_prediction_candidate',
    'stock_news_evidence',
    'market_context',
    'macro_context',
    'reject',
})

ACCEPTED_CLASSIFICATIONS = frozenset({
    'broker_prediction_candidate',
    'stock_news_evidence',
    'market_context',
    'macro_context',
})

DIRECT_RECOMMENDATION_RE = re.compile(
    r'\b('
    r'top\s+picks?|preferred\s+pick|conviction\s+pick|stock\s+picks?|'
    r'intraday\s+picks?|swing\s+picks?|stock\s+recommendations?|shares?\s+to\s+buy|'
    r'buy\s+call|sell\s+call|must\s+buy|'
    r'upgrade(?:d|s)?(?:\s+to)?|downgrade(?:d|s)?(?:\s+to)?|cut\s+rating|'
    r'recommends?|accumulate|reduce|'
    r'overweight|underweight|outperform|underperform|'
    r'target\s+price|price\s+target|\bTP\b|upside|downside|'
    r'\bbuy\b|\bsell\b|\bhold\b|\bneutral\b|'
    r'add\s+to\s+portfolio'
    r')\b',
    re.IGNORECASE,
)

BROKER_COMPOUND_RE = re.compile(
    r'\b(?:broker(?:age)?s?|analysts?|firm)\b.{0,48}\b('
    r'recommend|rating|target|pick|upgrade|downgrade|buy|sell|hold|neutral'
    r')\b|'
    r'\b(recommend|rating|target|pick|upgrade|downgrade|buy|sell|hold|neutral)\b'
    r'.{0,48}\b(?:broker(?:age)?s?|analysts?|firm)\b',
    re.IGNORECASE,
)

PURE_PRICE_MOVEMENT_RE = re.compile(
    r'\b('
    r'shares?\s+(?:jump(?:ed|s)?|surge(?:d|s)?|rise(?:s|n)?|rally|rallied|soar(?:ed|s)?|'
    r'skyrocket(?:ed|s)?|fall(?:s|en)?|slump(?:ed|s)?|crash(?:ed|es|ing)?|plunge(?:d|s)?|'
    r'tumble(?:d|s)?|sink(?:s|ing)?|drop(?:ped|s)?)|'
    r'(?:jump|surge|rally|crash|slump|soar|skyrocket)\s+\d+\s*%|'
    r'52[\s-]?week\s+high|upper\s+circuit|lower\s+circuit|'
    r'hit\s+(?:fresh\s+)?(?:52[\s-]?week\s+)?high'
    r')\b',
    re.IGNORECASE,
)

WATCH_TEXT_RE = re.compile(
    r'\b(stocks?\s+to\s+watch|stock\s+watchlist|stocks?\s+in\s+focus|in\s+focus)\b',
    re.IGNORECASE,
)

EXPLICIT_BULLISH_RE = re.compile(
    r'\b(buy|top\s+picks?|preferred\s+pick|conviction\s+pick|accumulate|outperform|'
    r'overweight|upgrade\s+to\s+buy|must\s+buy|add\s+to\s+portfolio|go\s+long|long\s+position)\b',
    re.IGNORECASE,
)

TARGET_PRICE_RE = re.compile(
    r'\b(target\s+price|price\s+target|upside|downside|raised?\s+(?:the\s+)?(?:price\s+)?target)\b',
    re.IGNORECASE,
)

BUY_SELL_HOLD_RE = re.compile(r'\bbuy,\s*sell\s*or\s*hold\b', re.IGNORECASE)

NEGATIVE_OVERRIDE_RE = re.compile(
    r'\b('
    r'downgrade(?:d|s)?(?:\s+to)?|sell|reduce|underperform|underweight|'
    r'cut\s+rating|avoid|bearish'
    r')\b',
    re.IGNORECASE,
)

DOWNGRADE_NEUTRAL_RE = re.compile(
    r'\b(downgrade(?:d|s)?(?:\s+[\w&.-]+){0,10}\s+to\s+neutral|'
    r'neutral\s+(?:rating|call|stance)|downgrade.*?\bneutral\b)\b',
    re.IGNORECASE,
)

NEUTRAL_HOLD_RE = re.compile(r'\b(hold|neutral)\b', re.IGNORECASE)

EXPLICIT_BEARISH_RE = re.compile(
    r'\b(sell|avoid|underperform|downgrade|downside|reduce|short\b|bearish)\b',
    re.IGNORECASE,
)

POSITIVE_PRICE_RE = re.compile(
    r'\b(jump(?:ed|s)?|surge(?:d|s)?|rally|rallied|soar(?:ed|s)?|skyrocket(?:ed|s)?|'
    r'rise(?:s|n)?|gain(?:ed|s)?)\b',
    re.IGNORECASE,
)

NEGATIVE_PRICE_RE = re.compile(
    r'\b(crash(?:ed|es|ing)?|fall(?:s|en)?|slump(?:ed|s)?|plunge(?:d|s)?|'
    r'fine|penalty|probe|tumble(?:d|s)?|sink(?:s|ing)?|drop(?:ped|s)?)\b',
    re.IGNORECASE,
)

MARKET_CONTEXT_RE = re.compile(
    r'\b('
    r'nifty\s*50?|sensex|bank\s+nifty|banknifty|finnifty|'
    r'market\s+live|market\s+strategy|closing\s+bell|market\s+wrap|'
    r'market\s+today|indices?\s+(?:close|end|slide|surge)|'
    r'stock\s+market\s+(?:today|crash|slide|surge)|'
    r'why\s+(?:is\s+)?(?:the\s+)?market\s+(?:crashing|falling|rising)'
    r')\b',
    re.IGNORECASE,
)

MACRO_CONTEXT_RE = re.compile(
    r'\b('
    r'crude(?:\s+oil)?|brent|wti|fed(?:eral\s+reserve)?|fomc|'
    r'us\s+stocks?|wall\s+street|dow\s+jones|s\s*&\s*p|nasdaq|'
    r'iran|middle\s+east|rupee|gold\s+prices?|dollar|dxy|'
    r'inflation|interest\s+rates?|treasury|bond\s+yields?|'
    r'oil\s+prices?|commodit(?:y|ies)|forex|geopolit'
    r')\b',
    re.IGNORECASE,
)

REJECT_RE = re.compile(
    r'\b('
    r'ipl\s+20\d{2}|cricket|football|soccer|tennis|olympics|'
    r'qualifier\s+\d|vs\s+rr|vs\s+rcb|'
    r'bollywood|entertainment|movie|web\s+series|celebrity|'
    r'election\s+rally|campaign\s+rally|assembly\s+poll'
    r')\b',
    re.IGNORECASE,
)

USA_SOURCE_RE = re.compile(
    r'\b(yahoo\s+finance|wall\s+street|us\s+stocks?|nasdaq|dow|s\s*&\s*p)\b',
    re.IGNORECASE,
)

INDIA_SOURCE_RE = re.compile(
    r'\b(moneycontrol|economictimes|livemint|ndtv|business\s+standard|nse|bse|sebi)\b',
    re.IGNORECASE,
)

INDEX_ALIASES: dict[str, str] = {
    'NIFTY 50': 'NIFTY50',
    'NIFTY50': 'NIFTY50',
    'NIFTY': 'NIFTY50',
    'NIFTY BANK': 'BANKNIFTY',
    'BANK NIFTY': 'BANKNIFTY',
    'BANKNIFTY': 'BANKNIFTY',
    'SENSEX': 'SENSEX',
}

INDEX_SYMBOLS = frozenset({'NIFTY', 'NIFTY50', 'SENSEX', 'BANKNIFTY', 'FINNIFTY', 'NIFTY BANK'})

GENERIC_REJECT_TERMS = frozenset({
    'MARKET', 'INDIA', 'STOCK', 'STOCKS', 'SHARE', 'SHARES', 'EQUITY',
    'BUY', 'SELL', 'LIVE', 'TODAY',
})

# Aliases that are common English words — lowercase occurrences are not company names.
AMBIGUOUS_ALIASES = frozenset({
    'reliance',
    'itc',
    'lt',
    'sun',
    'sail',
    'idea',
    'ioc',
})

# Tickers that are common English words — never infer from full-text uppercasing.
AMBIGUOUS_TICKERS = frozenset({
    'RELIANCE',
    'ITC',
    'LT',
    'SUN',
    'SAIL',
    'IDEA',
    'IOC',
})

# Multi-word aliases are always matched case-insensitively with word boundaries.
MULTI_WORD_ALIAS_MIN_PARTS = 2

HEADLINE_SUBJECT_RE = re.compile(
    r'^([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+)?)\s+'
    r'(?:shares?|stocks?|stock)\b',
)

ALIAS_MAP_PATH = DATA_DIR / 'company_alias_map.json'

# Backward-compatible alias used by older audit helpers.
BROKER_PREDICTION_RE = DIRECT_RECOMMENDATION_RE


def _normalize_token(token: str) -> str:
    cleaned = re.sub(r'\s+', ' ', str(token or '').strip().upper())
    if cleaned in INDEX_ALIASES:
        return INDEX_ALIASES[cleaned]
    return cleaned.replace(' ', '')


def _matched_keywords(pattern: re.Pattern[str], text: str) -> list[str]:
    seen: set[str] = set()
    found: list[str] = []
    for match in pattern.finditer(text):
        token = match.group(0).lower().strip()
        if token and token not in seen:
            seen.add(token)
            found.append(token)
    return found


def has_explicit_recommendation_signal(text: str) -> tuple[bool, list[str]]:
    """Return whether text contains an explicit broker/recommendation signal."""
    matched = _matched_keywords(DIRECT_RECOMMENDATION_RE, text)
    matched.extend(_matched_keywords(BROKER_COMPOUND_RE, text))
    deduped: list[str] = []
    seen: set[str] = set()
    for token in matched:
        if token not in seen:
            seen.add(token)
            deduped.append(token)
    return bool(deduped), deduped


def load_universe() -> dict[str, Any]:
    """Build ticker universe + alias map for classification."""
    tickers: set[str] = set()
    aliases: dict[str, str] = {}

    universe_path = DATA_DIR / 'historical_ticker_universe.json'
    if universe_path.is_file():
        try:
            data = json.loads(universe_path.read_text(encoding='utf-8'))
            for row in data.get('tickers') or []:
                if isinstance(row, dict):
                    token = _normalize_token(str(row.get('ticker') or ''))
                else:
                    token = _normalize_token(str(row))
                if len(token) >= 3:
                    tickers.add(token)
        except (OSError, json.JSONDecodeError):
            pass

    for path in (
        DATA_DIR / 'latest_market_data_memory_enriched.json',
        DATA_DIR / 'latest_market_data.json',
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        prices = data.get('prices') or data.get('symbols') or {}
        if isinstance(prices, dict):
            for key in prices:
                token = _normalize_token(str(key))
                if len(token) >= 3:
                    tickers.add(token)

    if ALIAS_MAP_PATH.is_file():
        try:
            alias_data = json.loads(ALIAS_MAP_PATH.read_text(encoding='utf-8'))
            for alias, ticker in (alias_data.get('aliases') or {}).items():
                canon = _normalize_token(str(ticker))
                if canon:
                    aliases[str(alias).lower().strip()] = canon
                    if len(canon) >= 3:
                        tickers.add(canon)
        except (OSError, json.JSONDecodeError):
            pass

    return {'tickers': tickers, 'aliases': aliases}


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ''


def _alias_word_count(alias: str) -> int:
    return len(str(alias or '').split())


def _alias_matches_text(alias: str, text: str) -> bool:
    """Word-boundary alias match; ambiguous single-word aliases require proper case."""
    alias_clean = str(alias or '').strip()
    if not alias_clean:
        return False
    if _alias_word_count(alias_clean) >= MULTI_WORD_ALIAS_MIN_PARTS:
        return bool(re.search(rf'\b{re.escape(alias_clean)}\b', text, re.IGNORECASE))
    if alias_clean.lower() in AMBIGUOUS_ALIASES:
        proper = alias_clean.title()
        return bool(re.search(rf'\b{re.escape(proper)}\b', text))
    return bool(re.search(rf'\b{re.escape(alias_clean)}\b', text, re.IGNORECASE))


def _headline_subject_company(title: str) -> str | None:
    match = HEADLINE_SUBJECT_RE.search(str(title or '').strip())
    if not match:
        return None
    return match.group(1).strip()


def _headline_conflicts_with_ticker(title: str, ticker: str, matched_alias: str | None) -> bool:
    """Reject body-only alias hits when the headline names a different company."""
    subject = _headline_subject_company(title)
    if not subject:
        return False
    subject_lower = subject.lower()
    alias_lower = str(matched_alias or '').strip().lower()
    ticker_token = _normalize_token(ticker)
    if alias_lower and subject_lower == alias_lower:
        return False
    if ticker_token and subject_lower == ticker_token.lower():
        return False
    if alias_lower and alias_lower in subject_lower:
        return False
    if ticker_token and ticker_token.lower() in subject_lower:
        return False
    return True


def _ticker_token_in_text(token: str, text: str, upper: str) -> bool:
    """Token-boundary ticker match; ambiguous tickers avoid uppercasing false positives."""
    if token in AMBIGUOUS_TICKERS:
        return bool(
            re.search(rf'\b{re.escape(token)}\b', text)
            or re.search(rf'\b{token.title()}\b', text)
        )
    return bool(re.search(rf'\b{re.escape(token)}\b', upper))


def _scan_ticker_tokens(text: str, known: set[str]) -> list[tuple[str, str, str]]:
    """Return (ticker, matched_token, match_method) from token-boundary symbol scan."""
    working = text
    for alias, canonical in sorted(INDEX_ALIASES.items(), key=len, reverse=True):
        working = re.sub(rf'\b{re.escape(alias)}\b', canonical, working, flags=re.IGNORECASE)
    upper = re.sub(r'[^A-Z0-9&.\- ]+', ' ', working.upper())
    hits: list[tuple[str, str, str]] = []
    for symbol in sorted(known, key=len, reverse=True):
        token = _normalize_token(symbol)
        if len(token) < 3 or token in GENERIC_REJECT_TERMS:
            continue
        if _ticker_token_in_text(token, text, upper):
            hits.append((token, token, 'ticker_symbol'))
    return hits


def _scan_alias_matches(text: str, aliases: dict[str, str], known: set[str]) -> list[tuple[str, str, str]]:
    """Return (ticker, matched_alias, match_method) from strict alias scan."""
    hits: list[tuple[str, str, str]] = []
    for alias, ticker in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        mapped = _normalize_token(ticker)
        if mapped not in known or mapped in GENERIC_REJECT_TERMS:
            continue
        if _alias_matches_text(alias, text):
            hits.append((mapped, alias, 'alias_match'))
    return hits


def extract_company_or_ticker(text: str, universe: dict[str, Any]) -> dict[str, Any]:
    """Extract ticker from text using universe tickers and aliases."""
    body = str(text or '').strip()
    if not body:
        return {
            'ticker': None,
            'method': 'none',
            'candidates': [],
            'matched_ticker': None,
            'matched_alias': None,
            'match_method': 'none',
            'match_confidence': 'none',
        }

    known: set[str] = set(universe.get('tickers') or [])
    aliases: dict[str, str] = dict(universe.get('aliases') or {})

    title_line = body.split('\n', 1)[0]
    title_hits = _scan_ticker_tokens(title_line, known) + _scan_alias_matches(title_line, aliases, known)
    body_hits = _scan_ticker_tokens(body, known) + _scan_alias_matches(body, aliases, known)

    def _pick(hits: list[tuple[str, str, str]]) -> tuple[str, str, str] | None:
        ordered: list[str] = []
        seen: set[str] = set()
        first_detail: tuple[str, str, str] | None = None
        for ticker, matched, method in hits:
            token = _normalize_token(ticker)
            if token in seen:
                continue
            seen.add(token)
            ordered.append(token)
            if first_detail is None:
                first_detail = (token, matched, method)
        if not first_detail:
            return None
        return first_detail

    title_pick = _pick(title_hits)
    body_pick = _pick(body_hits)

    if title_pick:
        ticker, matched, method = title_pick
        confidence = 'high' if method == 'ticker_symbol' else 'medium'
        return {
            'ticker': ticker,
            'method': method,
            'candidates': [ticker],
            'matched_ticker': ticker,
            'matched_alias': matched if method == 'alias_match' else None,
            'match_method': method,
            'match_confidence': confidence,
        }

    if body_pick:
        ticker, matched, method = body_pick
        if _headline_conflicts_with_ticker(title_line, ticker, matched if method == 'alias_match' else None):
            return {
                'ticker': None,
                'method': 'none',
                'candidates': [],
                'matched_ticker': None,
                'matched_alias': None,
                'match_method': 'title_conflict',
                'match_confidence': 'none',
            }
        confidence = 'medium' if method == 'ticker_symbol' else 'low'
        if matched.lower() in AMBIGUOUS_ALIASES and _alias_word_count(matched) < MULTI_WORD_ALIAS_MIN_PARTS:
            confidence = 'none'
            return {
                'ticker': None,
                'method': 'accidental_substring',
                'candidates': [],
                'matched_ticker': None,
                'matched_alias': matched,
                'match_method': 'accidental_substring',
                'match_confidence': 'none',
            }
        return {
            'ticker': ticker,
            'method': method,
            'candidates': [ticker],
            'matched_ticker': ticker,
            'matched_alias': matched if method == 'alias_match' else None,
            'match_method': method,
            'match_confidence': confidence,
        }

    return {
        'ticker': None,
        'method': 'none',
        'candidates': [],
        'matched_ticker': None,
        'matched_alias': None,
        'match_method': 'none',
        'match_confidence': 'none',
    }


def resolve_ticker_for_item(
    raw: dict[str, Any],
    *,
    title: str,
    body: str,
    universe: dict[str, Any],
) -> dict[str, Any]:
    """Resolve ticker with explicit field priority and strict alias rules."""
    explicit = _first_text(raw, ('ticker', 'symbol'))
    explicit_token = _normalize_token(explicit) if explicit else None
    known: set[str] = set(universe.get('tickers') or [])

    if explicit_token and explicit_token not in GENERIC_REJECT_TERMS:
        if explicit_token in known or len(explicit_token) >= 3:
            return {
                'ticker': explicit_token,
                'matched_ticker': explicit_token,
                'matched_alias': None,
                'match_method': 'explicit_ticker',
                'match_confidence': 'high',
                'candidates': [explicit_token],
            }

    combined = f'{title} {body}'.strip()
    extraction = extract_company_or_ticker(combined, universe)
    ticker = extraction.get('ticker')
    if ticker and extraction.get('match_confidence') == 'none':
        ticker = None
    return {
        'ticker': ticker,
        'matched_ticker': extraction.get('matched_ticker'),
        'matched_alias': extraction.get('matched_alias'),
        'match_method': extraction.get('match_method') or 'none',
        'match_confidence': extraction.get('match_confidence') or 'none',
        'candidates': extraction.get('candidates') or [],
    }


def classify_direction(text: str) -> dict[str, Any]:
    """Classify direction from text without inflating watch/news to bullish."""
    body = str(text or '')
    matched_keywords: list[str] = []
    negative_override_applied = False

    if WATCH_TEXT_RE.search(body):
        matched_keywords.extend(_matched_keywords(WATCH_TEXT_RE, body))
        return {
            'direction': 'WATCH',
            'direction_confidence': 'watch_only',
            'direction_reason': 'stocks_to_watch',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }
    if BUY_SELL_HOLD_RE.search(body):
        matched_keywords.extend(_matched_keywords(BUY_SELL_HOLD_RE, body))
        return {
            'direction': 'WATCH',
            'direction_confidence': 'watch_only',
            'direction_reason': 'buy_sell_hold_roundup',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }

    downgrade_neutral = _matched_keywords(DOWNGRADE_NEUTRAL_RE, body)
    negative = _matched_keywords(NEGATIVE_OVERRIDE_RE, body)
    if downgrade_neutral or negative:
        negative_override_applied = True
        matched_keywords.extend(downgrade_neutral or negative)
        if downgrade_neutral:
            direction = 'WATCH'
            reason = 'downgrade_to_neutral'
        else:
            direction = 'BEARISH'
            reason = 'strong_bearish_recommendation'
        if TARGET_PRICE_RE.search(body):
            reason = f'{reason}_despite_target_change'
        return {
            'direction': direction,
            'direction_confidence': 'explicit',
            'direction_reason': reason,
            'matched_keywords': matched_keywords,
            'negative_override_applied': negative_override_applied,
        }

    bullish = _matched_keywords(EXPLICIT_BULLISH_RE, body)
    if bullish:
        matched_keywords.extend(bullish)
        return {
            'direction': 'BULLISH',
            'direction_confidence': 'explicit',
            'direction_reason': 'explicit_bullish_recommendation',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }

    if TARGET_PRICE_RE.search(body):
        matched_keywords.extend(_matched_keywords(TARGET_PRICE_RE, body))
        return {
            'direction': 'WATCH',
            'direction_confidence': 'inferred',
            'direction_reason': 'target_price_without_buy',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }

    if EXPLICIT_BEARISH_RE.search(body):
        matched_keywords.extend(_matched_keywords(EXPLICIT_BEARISH_RE, body))
        return {
            'direction': 'BEARISH',
            'direction_confidence': 'explicit',
            'direction_reason': 'explicit_bearish_recommendation',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }

    has_signal, signal_keywords = has_explicit_recommendation_signal(body)
    if has_signal:
        matched_keywords.extend(signal_keywords)
        return {
            'direction': 'WATCH',
            'direction_confidence': 'inferred',
            'direction_reason': 'broker_signal_inferred_watch',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }

    if NEGATIVE_PRICE_RE.search(body):
        matched_keywords.extend(_matched_keywords(NEGATIVE_PRICE_RE, body))
        direction = 'BEARISH' if EXPLICIT_BEARISH_RE.search(body) else 'WATCH'
        return {
            'direction': direction,
            'direction_confidence': 'context_only',
            'direction_reason': 'negative_price_or_regulatory_news',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }

    if POSITIVE_PRICE_RE.search(body):
        matched_keywords.extend(_matched_keywords(POSITIVE_PRICE_RE, body))
        return {
            'direction': 'WATCH',
            'direction_confidence': 'context_only',
            'direction_reason': 'positive_price_movement_news',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }

    return {
        'direction': 'NEUTRAL',
        'direction_confidence': 'context_only',
        'direction_reason': 'no_direction_signal',
        'matched_keywords': matched_keywords,
        'negative_override_applied': False,
    }


def classify_market_relevance(text: str) -> dict[str, Any]:
    """Score market relevance and detect market region."""
    body = str(text or '')
    if not body.strip():
        return {'relevance': 'none', 'market': 'GLOBAL', 'score': 0}

    if REJECT_RE.search(body):
        return {'relevance': 'reject', 'market': 'GLOBAL', 'score': 0}

    market = 'INDIA'
    if USA_SOURCE_RE.search(body):
        market = 'USA'
    elif MACRO_CONTEXT_RE.search(body) and not INDIA_SOURCE_RE.search(body):
        market = 'GLOBAL'

    has_signal, _ = has_explicit_recommendation_signal(body)
    if MARKET_CONTEXT_RE.search(body):
        return {'relevance': 'market_context', 'market': market, 'score': 3}
    if MACRO_CONTEXT_RE.search(body):
        return {'relevance': 'macro_context', 'market': market, 'score': 2}
    if has_signal or WATCH_TEXT_RE.search(body):
        return {'relevance': 'broker_or_watch', 'market': market, 'score': 4}
    if re.search(r'\b(stock|share|equity|company|earnings|results|sebi|rbi)\b', body, re.IGNORECASE):
        return {'relevance': 'stock_news', 'market': market, 'score': 2}
    return {'relevance': 'low', 'market': market, 'score': 1}


def _evidence_strength(
    classification: str,
    *,
    has_ticker: bool,
    direction_confidence: str,
) -> str:
    if classification == 'reject':
        return 'low'
    if classification == 'broker_prediction_candidate':
        if direction_confidence == 'explicit':
            return 'high'
        return 'medium'
    if classification == 'stock_news_evidence' and has_ticker:
        return 'medium'
    if classification in {'market_context', 'macro_context'}:
        return 'medium'
    return 'low'


def classify_external_item(raw: dict[str, Any], universe: dict[str, Any]) -> dict[str, Any]:
    """Classify one external evidence item."""
    empty_explanation = {
        'classification_reason': '',
        'direction_reason': 'no_direction_signal',
        'matched_keywords': [],
        'negative_override_applied': False,
    }
    if not isinstance(raw, dict):
        return {
            'accepted': False,
            'classification': 'reject',
            'ticker': None,
            'market': 'GLOBAL',
            'direction': 'NEUTRAL',
            'direction_confidence': 'context_only',
            'evidence_strength': 'low',
            'source': '',
            'title': '',
            'reason': 'unsupported_shape',
            'rejection_reason': 'unsupported_shape',
            'raw_payload': raw if isinstance(raw, dict) else {},
            **empty_explanation,
        }

    title = _first_text(raw, ('title', 'headline', 'name'))
    body = _first_text(raw, ('description', 'summary', 'text', 'notes', 'content'))
    source = _first_text(raw, ('source', 'source_name', 'channel', 'broker_source', 'feed_name'))
    combined = f'{title} {body}'.strip()

    match_info = resolve_ticker_for_item(raw, title=title, body=body, universe=universe)
    ticker = match_info.get('ticker')
    matched_ticker = match_info.get('matched_ticker')
    matched_alias = match_info.get('matched_alias')
    match_method = str(match_info.get('match_method') or 'none')
    match_confidence = str(match_info.get('match_confidence') or 'none')
    if ticker and ticker in GENERIC_REJECT_TERMS:
        ticker = None
        matched_ticker = None
        match_method = 'none'
        match_confidence = 'none'

    relevance = classify_market_relevance(combined)
    direction_info = classify_direction(combined)
    market = relevance.get('market') or 'INDIA'

    has_broker_signal, broker_keywords = has_explicit_recommendation_signal(combined)
    pure_price_movement = bool(PURE_PRICE_MOVEMENT_RE.search(combined) and not has_broker_signal)
    matched_keywords = list(direction_info.get('matched_keywords') or [])
    for token in broker_keywords:
        if token not in matched_keywords:
            matched_keywords.append(token)

    classification = 'reject'
    reason = ''
    classification_reason = ''
    rejection_reason: str | None = None
    accepted = False

    if REJECT_RE.search(combined):
        classification = 'reject'
        reason = 'unrelated_content'
        classification_reason = 'unrelated_content'
        rejection_reason = 'unrelated_content'
    elif has_broker_signal and ticker and not pure_price_movement:
        classification = 'broker_prediction_candidate'
        reason = 'explicit_recommendation_with_ticker'
        classification_reason = 'explicit_recommendation_with_ticker'
        accepted = True
    elif has_broker_signal and not ticker:
        classification = 'reject'
        reason = 'broker_terms_without_ticker'
        classification_reason = 'broker_terms_without_ticker'
        rejection_reason = 'no_ticker'
    elif MARKET_CONTEXT_RE.search(combined) and (
        not ticker or str(ticker).upper() in INDEX_SYMBOLS
    ):
        classification = 'market_context'
        reason = 'index_or_market_headline'
        classification_reason = 'index_or_market_headline'
        accepted = True
        direction_info = {
            'direction': 'NEUTRAL',
            'direction_confidence': 'context_only',
            'direction_reason': 'market_context',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }
        ticker = None
    elif MACRO_CONTEXT_RE.search(combined) and not ticker:
        classification = 'macro_context'
        reason = 'macro_headline'
        classification_reason = 'macro_headline'
        accepted = True
        direction_info = {
            'direction': 'NEUTRAL',
            'direction_confidence': 'context_only',
            'direction_reason': 'macro_context',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }
        ticker = None
    elif ticker and match_confidence != 'none':
        classification = 'stock_news_evidence'
        reason = 'pure_price_movement_news' if pure_price_movement else 'company_specific_news'
        classification_reason = reason
        accepted = True
        if direction_info['direction'] == 'NEUTRAL' and WATCH_TEXT_RE.search(combined):
            direction_info = {
                **direction_info,
                'direction': 'WATCH',
                'direction_confidence': 'watch_only',
                'direction_reason': 'stocks_to_watch',
            }
    elif MARKET_CONTEXT_RE.search(combined):
        classification = 'market_context'
        reason = 'index_or_market_headline'
        classification_reason = 'index_or_market_headline'
        accepted = True
        direction_info = {
            'direction': 'NEUTRAL',
            'direction_confidence': 'context_only',
            'direction_reason': 'market_context',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }
        ticker = None
    elif MACRO_CONTEXT_RE.search(combined):
        classification = 'macro_context'
        reason = 'macro_headline'
        classification_reason = 'macro_headline'
        accepted = True
        direction_info = {
            'direction': 'NEUTRAL',
            'direction_confidence': 'context_only',
            'direction_reason': 'macro_context',
            'matched_keywords': matched_keywords,
            'negative_override_applied': False,
        }
        ticker = None
    elif relevance.get('relevance') == 'reject':
        classification = 'reject'
        reason = 'unrelated_content'
        classification_reason = 'unrelated_content'
        rejection_reason = 'unrelated_content'
    elif relevance.get('score', 0) <= 1 and not ticker:
        classification = 'reject'
        reason = 'low_market_relevance'
        classification_reason = 'low_market_relevance'
        rejection_reason = 'low_market_relevance'
    else:
        classification = 'reject'
        reason = 'low_market_relevance'
        classification_reason = 'low_market_relevance'
        rejection_reason = 'low_market_relevance'

    if classification == 'stock_news_evidence':
        if direction_info['direction'] == 'BULLISH' and not EXPLICIT_BULLISH_RE.search(combined):
            direction_info = {
                **direction_info,
                'direction': 'WATCH',
                'direction_confidence': 'watch_only',
                'direction_reason': 'stock_news_without_explicit_buy',
            }

    strength = _evidence_strength(
        classification,
        has_ticker=bool(ticker),
        direction_confidence=str(direction_info.get('direction_confidence') or ''),
    )

    if classification == 'stock_news_evidence' and ticker:
        matched_ticker = ticker
    elif classification != 'stock_news_evidence':
        matched_ticker = None
        matched_alias = None
        if classification in {'market_context', 'macro_context'}:
            match_method = 'context'
            match_confidence = 'context_only'

    return {
        'accepted': accepted,
        'classification': classification,
        'ticker': ticker,
        'market': market,
        'direction': direction_info.get('direction') or 'NEUTRAL',
        'direction_confidence': direction_info.get('direction_confidence') or 'context_only',
        'evidence_strength': strength,
        'source': source,
        'title': title,
        'reason': reason,
        'rejection_reason': rejection_reason,
        'classification_reason': classification_reason,
        'direction_reason': direction_info.get('direction_reason') or 'no_direction_signal',
        'matched_keywords': matched_keywords,
        'negative_override_applied': bool(direction_info.get('negative_override_applied')),
        'matched_ticker': matched_ticker,
        'matched_alias': matched_alias,
        'match_method': match_method,
        'match_confidence': match_confidence,
        'raw_payload': raw,
    }
