"""
Privacy-aware market text extraction for My Feed (Stage 50A).
"""

from __future__ import annotations

import re
from typing import Any

PRIVATE_PATTERNS = (
    r'\binstagram\b',
    r'\bsnapchat\b',
    r'\bfacebook\b',
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
)

MARKET_HINTS = (
    'nifty', 'sensex', 'bank nifty', 'stock', 'share', 'market', 'trading',
    'rbi', 'sebi', 'ipo', 'fii', 'dii', 'results', 'earnings', 'profit',
    'loss', 'target', 'upgrade', 'downgrade', 'sector', 'crude', 'gold',
    'inflation', 'gdp', 'budget', 'fed', 'rate cut', 'rate hike', 'index',
    'bse', 'nse', 'mutual fund', 'bond', 'yield', 'rupee', 'dollar',
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


def extract_tickers(text: str) -> list[str]:
    found: list[str] = []
    for match in TICKER_RE.findall(str(text or '').upper()):
        if match in {'THE', 'AND', 'FOR', 'WITH', 'FROM', 'NEWS', 'ONLY', 'WAIT', 'RISK'}:
            continue
        if match not in found:
            found.append(match)
    return found[:8]


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
