"""Remove duplicate items across intelligence sources."""

import hashlib
import re
from typing import Any, Callable, Dict, List


def _norm_title(title: str) -> str:
    t = re.sub(r'\s+', ' ', (title or '').strip().lower())
    t = re.sub(r'[^a-z0-9 ]', '', t)
    return t[:120]


def _item_hash(item: dict, keys: List[str]) -> str:
    blob = '|'.join(str(item.get(k, ''))[:200] for k in keys)
    return hashlib.sha256(blob.encode('utf-8', errors='replace')).hexdigest()[:16]


def dedupe_list(items: List[Any], key_fn: Callable[[Any], str]) -> List[Any]:
    seen = set()
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = key_fn(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def dedupe_news(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    articles = data.get('articles') or []
    if isinstance(articles, list):
        data = dict(data)
        data['articles'] = dedupe_list(articles, lambda a: _norm_title(a.get('title', '')))
    return data


def dedupe_reddit(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    data = dict(data)
    for field in ('hot_discussions', 'trending_tickers'):
        items = data.get(field)
        if isinstance(items, list):
            if field == 'hot_discussions':
                data[field] = dedupe_list(items, lambda x: _norm_title(x.get('title', '')))
            else:
                data[field] = dedupe_list(items, lambda x: str(x.get('ticker', '')).upper())
    return data


def dedupe_twitter(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    tweets = data.get('tweets') or []
    if isinstance(tweets, list):
        data = dict(data)
        data['tweets'] = dedupe_list(tweets, lambda t: _item_hash(t, ['text', 'account']))
    return data


def dedupe_govt(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    items = data.get('high_impact_items') or []
    if isinstance(items, list):
        data = dict(data)
        data['high_impact_items'] = dedupe_list(
            items,
            lambda i: _norm_title(i.get('english_headline', i.get('title', ''))),
        )
    return data


def dedupe_scanner(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    signals = data.get('top_signals') or []
    if isinstance(signals, list):
        data = dict(data)
        data['top_signals'] = dedupe_list(signals, lambda s: str(s.get('ticker', '')).upper())
    return data


def deduplicate_all(all_data: Dict[str, Any]) -> Dict[str, Any]:
    """Return copy of all_data with duplicates removed per source."""
    if not isinstance(all_data, dict):
        return all_data

    handlers = {
        'news': dedupe_news,
        'reddit': dedupe_reddit,
        'twitter': dedupe_twitter,
        'govt': dedupe_govt,
        'scanner': dedupe_scanner,
    }
    cleaned = dict(all_data)
    removed = 0
    for key, fn in handlers.items():
        raw = cleaned.get(key)
        if not raw:
            continue
        before = _count_items(raw)
        cleaned[key] = fn(raw)
        after = _count_items(cleaned[key])
        removed += max(0, before - after)
    if removed:
        print(f"[COMPRESSOR] Deduplicator removed {removed} duplicate items")
    return cleaned


def _count_items(data: dict) -> int:
    if not isinstance(data, dict):
        return 0
    for k in ('articles', 'top_signals', 'high_impact_items', 'hot_discussions', 'tweets'):
        v = data.get(k)
        if isinstance(v, list):
            return len(v)
    return 0
