"""
Privacy-aware market text extraction for My Feed (Stage 50A / 50C).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.storage.data_paths import get_data_path

PRIVATE_PATTERNS = (
    r'\binstagram\b',
    r'\bsnapchat\b',
    r'\bfacebook\b',
    r'\bfriend suggestion\b',
    r'\breddit\b',
    r'\bwhatsapp\b',
    r'\btelegram\b(?!\s+news)',
    r'\bmessenger\b',
    r'\bpersonal chat\b',
    r'\bdirect message\b',
    r'\blocation\b',
    r'\bgps\b',
    r'\bmaps\b',
    r'\bpayment\b',
    r'\bupi\b',
    r'\bpaytm\b',
    r'\bphonepe\b',
    r'\bgpay\b',
    r'\bcredit card\b',
    r'\bdebit card\b',
    r'\bbank alert\b',
    r'\botp\b',
    r'\bunrelated ad\b',
    r'\bsponsored ad\b',
    r'\bbattery\b',
    r'\b\d{1,2}:\d{2}\s*(am|pm)?\b',
    r'\bhome screen\b',
)

MARKET_HINTS = (
    'nifty', 'sensex', 'bank nifty', 'stock', 'share', 'market', 'trading',
    'rbi', 'sebi', 'ipo', 'fii', 'dii', 'results', 'earnings', 'profit',
    'loss', 'target', 'upgrade', 'downgrade', 'sector', 'crude', 'gold',
    'silver', 'silverm', 'moil', 'commodity', 'geopolitical', 'wipro',
    'inflation', 'gdp', 'budget', 'fed', 'rate cut', 'rate hike', 'index',
    'bse', 'nse', 'mutual fund', 'bond', 'yield', 'rupee', 'dollar', 'jv',
    'surge', 'surges', 'rally', 'attack', 'attacks', 'iran', 'kuwait',
    'jordan', 'bahrain', 'oil', 'defence', 'airline', 'bases', 'war',
)

EXTRA_KNOWN_TICKERS = frozenset({
    'CHAMBLFERT', 'COROMANDEL', 'GNFC', 'RCF', 'NFL',
})

GEO_COUNTRY_HINTS: tuple[tuple[str, str], ...] = (
    ('iran', 'IRAN'),
    ('kuwait', 'KUWAIT'),
    ('jordan', 'JORDAN'),
    ('bahrain', 'BAHRAIN'),
    ('israel', 'ISRAEL'),
    ('ukraine', 'UKRAINE'),
    ('russia', 'RUSSIA'),
    ('china', 'CHINA'),
    ('united states', 'US'),
)

APP_NOTIFICATION_PREFIXES = (
    'inshorts:', 'moneycontrol:', 'et markets:', 'indmoney:', 'tickertape:',
    'tradingview:', 'zerodha:', 'groww:',
)

APP_HINTS = {
    'INDmoney': ('indmoney', 'ind money'),
    'Inshorts': ('inshorts',),
    'Moneycontrol': ('moneycontrol',),
    'ET Markets': ('et markets', 'economictimes'),
    'Tickertape': ('tickertape',),
    'TradingView': ('tradingview',),
    'Zerodha': ('zerodha', 'kite'),
    'Groww': ('groww',),
}

TICKER_RE = re.compile(r'\b([A-Z]{2,15})\b')

REJECT_TICKER_WORDS = frozenset({
    'FALLS', 'BELOW', 'ABOVE', 'RS', 'LAKH', 'CRORE', 'AMID', 'GLOBAL', 'SELL', 'BUY',
    'CHECK', 'CITY', 'TODAY', 'PRICE', 'PRICES', 'MARKET', 'NEWS', 'UPDATE', 'ALERT',
    'THE', 'AND', 'FOR', 'WITH', 'FROM', 'ONLY', 'WAIT', 'RISK', 'OFF', 'THIS', 'THAT',
    'WILL', 'HAVE', 'BEEN', 'WERE', 'WAS', 'ARE', 'NOT', 'OUT', 'INTO', 'OVER', 'UNDER',
    'HIGH', 'LOW', 'OPEN', 'CLOSE', 'YEAR', 'WEEK', 'MONTH', 'INDIA', 'INDIAN', 'STOCK',
    'SHARE', 'SHARES', 'INDEX', 'POINTS', 'PER', 'CENT', 'PERCENT',
})

ALLOWED_ENTITY_WORDS = frozenset({
    'GOLD', 'SILVER', 'CRUDE', 'OIL', 'NIFTY', 'BANKNIFTY', 'SENSEX', 'USDINR', 'INR', 'VIX',
    'SILVERM', 'MOIL', 'BANK', 'NIFTY50',
})

ENTITY_HINTS: tuple[tuple[str, str], ...] = (
    ('bank nifty', 'BANKNIFTY'),
    ('nifty 50', 'NIFTY'),
    ('nifty50', 'NIFTY'),
    ('nifty', 'NIFTY'),
    ('sensex', 'SENSEX'),
    ('gold', 'GOLD'),
    ('silver', 'SILVER'),
    ('silverm', 'SILVERM'),
    ('crude', 'CRUDE'),
    ('oil', 'OIL'),
    ('usd/inr', 'USDINR'),
    ('usdinr', 'USDINR'),
    ('vix', 'VIX'),
    ('moil', 'MOIL'),
)


def _is_private_line(line: str) -> bool:
    lower = line.lower().strip()
    if not lower:
        return True
    for pattern in PRIVATE_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def _is_market_line(line: str) -> bool:
    lower = line.lower().strip()
    if not lower or len(lower) < 8:
        return False
    if _is_private_line(line):
        return False
    return any(hint in lower for hint in MARKET_HINTS) or bool(TICKER_RE.search(line))


def detect_source_app(text: str) -> str:
    lower = str(text or '').lower()
    for app, hints in APP_HINTS.items():
        if any(h in lower for h in hints):
            return app
    return ''


@lru_cache(maxsize=1)
def _known_stock_tickers() -> frozenset[str]:
    symbols: set[str] = set()
    paths = (
        get_data_path('scanner_data.json'),
        get_data_path('tomorrow_watchlist_report.json'),
        get_data_path('intelligence.json'),
    )
    for path in paths:
        if not Path(path).is_file():
            continue
        try:
            payload = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in ('top_signals', 'watchlist_candidates', 'top_watchlist', 'raw_candidates'):
            for row in payload.get(key) or []:
                if isinstance(row, dict):
                    sym = str(row.get('symbol') or row.get('ticker') or '').strip().upper()
                    if sym and 2 <= len(sym) <= 15:
                        symbols.add(sym)
                elif isinstance(row, str):
                    sym = row.strip().upper()
                    if sym and 2 <= len(sym) <= 15:
                        symbols.add(sym)
        for row in (payload.get('risks_and_avoids') or []):
            if isinstance(row, dict):
                sym = str(row.get('symbol') or row.get('ticker') or '').strip().upper()
                if sym:
                    symbols.add(sym)
    return frozenset(symbols)


def _extract_entity_hints(text: str) -> list[str]:
    lower = str(text or '').lower()
    found: list[str] = []
    for hint, symbol in ENTITY_HINTS:
        if hint in lower and symbol not in found:
            found.append(symbol)
    padded = f' {lower} '
    for hint, symbol in GEO_COUNTRY_HINTS:
        if hint in padded and symbol not in found:
            found.append(symbol)
    if re.search(r'\bUS\b', str(text or '').upper()) and 'US' not in found:
        if any(w in lower for w in ('base', 'bases', 'attack', 'attacks', 'sanction', 'tariff', 'fed')):
            found.append('US')
    return found


def _split_notification_blocks(raw_text: str) -> list[str]:
    text = str(raw_text or '').strip()
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines()]
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                blocks.append('\n'.join(current).strip())
                current = []
            continue
        lower = line.lower()
        starts_new = any(lower.startswith(prefix) for prefix in APP_NOTIFICATION_PREFIXES)
        if starts_new and current:
            blocks.append('\n'.join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append('\n'.join(current).strip())
    if len(blocks) <= 1 and '\n\n' in text:
        blocks = [chunk.strip() for chunk in text.split('\n\n') if chunk.strip()]
    return blocks or [text]


def split_market_notifications(raw_text: str) -> dict[str, Any]:
    """Split OCR blob into separate market notifications; drop private lines."""
    blocks = _split_notification_blocks(raw_text)
    notifications: list[str] = []
    ignored_private_count = 0
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) == 1:
            extracted = filter_market_text(block)
            ignored_private_count += int(extracted.get('ignored_private_items') or 0)
            cleaned = str(extracted.get('cleaned_summary') or '').strip()
            if cleaned:
                notifications.append(cleaned)
            continue
        for line in lines:
            if _is_private_line(line):
                ignored_private_count += 1
                continue
            if _is_market_line(line):
                notifications.append(line)
            else:
                ignored_private_count += 1
    combined = '\n'.join(notifications).strip()
    return {
        'notifications': notifications,
        'ignored_private_count': ignored_private_count,
        'combined': combined,
    }


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def correct_fuzzy_tickers(candidates: list[str] | tuple[str, ...], text: str = '') -> list[str]:
    """Map near-miss OCR tokens to known NSE symbols (e.g. CHAMBLERT → CHAMBLFERT)."""
    known = set(_known_stock_tickers()) | set(EXTRA_KNOWN_TICKERS)
    found: list[str] = []
    pool = [str(c or '').strip().upper() for c in candidates if str(c or '').strip()]
    for token in TICKER_RE.findall(str(text or '').upper()):
        pool.append(token)
    for raw in pool:
        if not raw or raw in REJECT_TICKER_WORDS:
            continue
        if raw in known:
            if raw not in found:
                found.append(raw)
            continue
        if raw in ALLOWED_ENTITY_WORDS:
            continue
        best_sym = ''
        best_dist = 999
        for sym in known:
            if abs(len(sym) - len(raw)) > 2:
                continue
            dist = _levenshtein(raw, sym)
            if dist <= 2 and dist < best_dist:
                best_sym = sym
                best_dist = dist
        if best_sym and best_dist <= 2 and best_sym not in found:
            found.append(best_sym)
    return found[:8]


def split_entity_tokens(candidates: list[str] | tuple[str, ...], text: str = '') -> list[str]:
    entities: list[str] = []
    for token in candidates or []:
        up = str(token or '').strip().upper()
        if up and up not in entities:
            entities.append(up)
    for sym in _extract_entity_hints(text):
        if sym not in entities:
            entities.append(sym)
    return entities[:12]


def extract_tickers(text: str) -> list[str]:
    blob = str(text or '')
    upper_text = blob.upper()
    found: list[str] = []
    known = _known_stock_tickers()

    for symbol in _extract_entity_hints(blob):
        if symbol not in found:
            found.append(symbol)

    for match in TICKER_RE.findall(upper_text):
        if match in REJECT_TICKER_WORDS:
            continue
        if match in ALLOWED_ENTITY_WORDS:
            if match not in found:
                found.append(match)
            continue
        if match in known or match in EXTRA_KNOWN_TICKERS:
            if match not in found:
                found.append(match)
    return correct_fuzzy_tickers(found, blob)[:8]


def filter_market_text(raw_text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in str(raw_text or '').splitlines() if ln.strip()]
    kept: list[str] = []
    ignored = 0
    for line in lines:
        if _is_private_line(line):
            ignored += 1
            continue
        if _is_market_line(line):
            kept.append(line)
        else:
            ignored += 1
    cleaned = '\n'.join(kept).strip()
    return {
        'raw_market_text': '\n'.join(lines).strip(),
        'cleaned_summary': cleaned,
        'items_found': len(kept),
        'ignored_private_items': ignored,
        'detected_source_app': detect_source_app(raw_text),
        'tickers': extract_tickers(cleaned or raw_text),
    }
