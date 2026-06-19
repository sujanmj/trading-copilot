"""
Lightweight external verification search for My Feed (Stage 50Y).

When internal news cache misses a claim, search trusted headline sources without full /refresh full.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from backend.utils.config import DATA_DIR

TRUSTED_SOURCE_NAMES = frozenset({
    'economic times', 'economictimes', 'et markets', 'moneycontrol', 'mint',
    'business standard', 'financial express', 'ndtv profit', 'ndtv', 'cnbc tv18', 'cnbc',
    'nse', 'bse', 'company filing', 'exchange filing',
})

TRUSTED_DOMAIN_FRAGMENTS = (
    'economictimes.indiatimes.com', 'moneycontrol.com', 'livemint.com',
    'business-standard.com', 'financialexpress.com', 'ndtvprofit.com', 'cnbctv18.com',
    'nseindia.com', 'bseindia.com',
)

SearchFn = Callable[[dict[str, Any]], list[dict[str, Any]]]

_EXTERNAL_SEARCH_FN: SearchFn | None = None


def set_external_search_fn(fn: SearchFn | None) -> None:
    global _EXTERNAL_SEARCH_FN
    _EXTERNAL_SEARCH_FN = fn


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _is_trusted_source(item: dict[str, Any]) -> bool:
    source = str(
        item.get('source')
        or item.get('source_name')
        or item.get('publisher')
        or ''
    ).lower()
    url = str(item.get('link') or item.get('url') or '').lower()
    if any(name in source for name in TRUSTED_SOURCE_NAMES):
        return True
    return any(dom in url for dom in TRUSTED_DOMAIN_FRAGMENTS)


def load_trusted_headline_cache(data_dir: Path | None = None) -> list[dict[str, Any]]:
    root = data_dir or DATA_DIR
    articles: list[dict[str, Any]] = []
    for fname in (
        'trusted_headlines_cache.json',
        'external_verification_index.json',
        'verified_headlines_cache.json',
    ):
        payload = _load_json(root / fname)
        items = payload.get('items') or payload.get('headlines') or payload.get('articles') or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    articles.append({**item, '_cache_bucket': fname})
    return articles


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r'[a-z0-9]{3,}', str(text or '').lower())}


def _search_by_company_event(claim: dict[str, Any], articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claim_tokens = _tokenize(claim.get('claim_summary') or '')
    claim_tokens |= _tokenize(' '.join(claim.get('entities') or []))
    claim_tokens |= _tokenize(claim.get('entity') or '')
    claim_tokens |= set(claim.get('keywords') or [])
    for key in ('adani', 'kenya', 'airport', 'china', 'ports', 'invest', 'capex', 'technology'):
        if key in str(claim.get('claim_summary') or '').lower():
            claim_tokens.add(key)

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in articles:
        if not _is_trusted_source(item):
            continue
        title = str(item.get('title') or item.get('headline') or '').strip()
        body = str(item.get('description') or item.get('summary') or '').strip()
        blob = f'{title} {body}'.lower()
        if len(blob) < 20:
            continue
        article_tokens = _tokenize(blob)
        if not claim_tokens:
            continue
        overlap = len(claim_tokens & article_tokens) / max(1, len(claim_tokens))
        if overlap < 0.25:
            continue
        bonus = 0.0
        if str(claim.get('entity') or '').lower() in blob:
            bonus += 0.15
        if 'adani' in str(claim.get('claim_summary') or '').lower() and 'adani' in blob:
            bonus += 0.1
        scored.append((overlap + bonus, item))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in scored[:12]]


def search_external_verification_articles(
    claim: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Lightweight trusted-source search — injectable for tests."""
    if _EXTERNAL_SEARCH_FN is not None:
        return _EXTERNAL_SEARCH_FN(claim)

    cached = load_trusted_headline_cache(data_dir=data_dir)
    if not cached:
        return []
    return _search_by_company_event(claim, cached)


def search_exact_headline(claim_text: str, articles: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match quoted/near-exact headline in trusted articles."""
    claim = str(claim_text or '').strip().lower()
    if len(claim) < 20:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for item in articles:
        if not _is_trusted_source(item):
            continue
        title = str(item.get('title') or item.get('headline') or '').strip()
        if not title:
            continue
        lower = title.lower()
        if claim in lower or lower in claim:
            return item
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, claim, lower).ratio()
        if ratio >= 0.72 and (best is None or ratio > best[0]):
            best = (ratio, item)
    return best[1] if best else None
