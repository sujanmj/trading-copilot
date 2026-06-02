"""
Canonical feed registry — single source for feed keys, files, and source counts.

All status/GUI/Telegram surfaces must derive feed totals from here so displayed
counts never exceed available feeds.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

# Core export feeds surfaced in /status and intelligence header (8 feeds)
CANONICAL_FEEDS: Dict[str, Dict[str, str]] = {
    'scanner': {'filename': 'scanner_data.json', 'label': 'Scanner'},
    'reddit': {'filename': 'reddit_data.json', 'label': 'Reddit'},
    'govt': {'filename': 'govt_intelligence.json', 'label': 'Govt'},
    'news': {'filename': 'news_feed.json', 'label': 'News'},
    'global': {'filename': 'global_markets.json', 'label': 'Global'},
    'india': {'filename': 'latest_market_data.json', 'label': 'India'},
    'stats': {'filename': 'stats_data.json', 'label': 'Stats export'},
    'history': {'filename': 'history_data.json', 'label': 'History export'},
}

STATUS_FEED_ORDER: Tuple[str, ...] = tuple(CANONICAL_FEEDS.keys())

# master_analyzer gather_all_data keys → canonical feed key (8 primary inputs)
ANALYZER_SOURCE_MAP: Dict[str, str] = {
    'global_markets': 'global',
    'india_markets': 'india',
    'news': 'news',
    'govt': 'govt',
    'reddit': 'reddit',
    'scanner': 'scanner',
    'youtube': 'news',
    'inshorts': 'news',
}

# Extended health checks (includes optional exports not in header count)
HEALTH_FEED_FILES: Dict[str, str] = {
    **{k: v['filename'] for k, v in CANONICAL_FEEDS.items()},
    'intelligence': 'unified_intelligence.json',
    'youtube': 'tv_intelligence.json',
    'inshorts': 'inshorts_feed.json',
}


def feed_count_total() -> int:
    return len(STATUS_FEED_ORDER)


def feed_files() -> Dict[str, str]:
    return {k: CANONICAL_FEEDS[k]['filename'] for k in STATUS_FEED_ORDER}


def status_feed_labels() -> List[Tuple[str, str]]:
    return [(key, CANONICAL_FEEDS[key]['label']) for key in STATUS_FEED_ORDER]


def count_analyzer_sources_loaded(all_data: Optional[Dict[str, Any]]) -> Tuple[int, int]:
    """Return (loaded, total) capped so loaded never exceeds total."""
    data = all_data if isinstance(all_data, dict) else {}
    unique_keys = sorted(set(ANALYZER_SOURCE_MAP.values()))
    loaded = 0
    for feed_key in unique_keys:
        gather_keys = [k for k, v in ANALYZER_SOURCE_MAP.items() if v == feed_key]
        if any(data.get(k) for k in gather_keys):
            loaded += 1
    total = len(unique_keys)
    return min(loaded, total), total


def format_sources_display(loaded: Optional[int], *, total: Optional[int] = None) -> str:
    total_n = int(total if total is not None else feed_count_total())
    if loaded is None:
        return f'—/{total_n}'
    loaded_n = min(max(0, int(loaded)), total_n)
    return f'{loaded_n}/{total_n}'


def count_fresh_sources(source_freshness: Optional[Dict[str, Any]]) -> Tuple[int, int]:
    """Count non-missing feeds from runtime source_freshness rows."""
    rows = source_freshness if isinstance(source_freshness, dict) else {}
    loaded = 0
    for key in STATUS_FEED_ORDER:
        row = rows.get(key) or {}
        if row.get('status') not in ('missing', None) and row.get('age_seconds') is not None:
            loaded += 1
        elif row.get('status') == 'ok':
            loaded += 1
    total = feed_count_total()
    return min(loaded, total), total
