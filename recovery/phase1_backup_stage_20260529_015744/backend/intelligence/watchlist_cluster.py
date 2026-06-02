"""
Watchlist clustering — compress repetitive watchlist descriptions.

Max 3 names per cluster, max 2 clusters.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

MAX_NAMES_PER_CLUSTER = 3
MAX_CLUSTERS = 2


def _symbol(item: dict) -> str:
    return str(item.get('symbol') or item.get('ticker') or '').upper().strip()


def _logic_key(item: dict) -> str:
    logic = str(item.get('logic') or item.get('signal_type') or item.get('watch_note') or '')
    logic = re.sub(r'\s+', ' ', logic.lower()).strip()
    logic = re.sub(r'[₹$]\s*\d+(\.\d+)?', '', logic)
    logic = re.sub(r'\b\d+(\.\d+)?x\b', ' vol ', logic)
    logic = re.sub(r'\b\d+(\.\d+)?%\b', ' pct ', logic)
    for token in ('scanner', 'high conviction', 'watch', 'monitor', 'breakout', 'volume'):
        logic = logic.replace(token, token)
    return logic[:80] or 'general setup'


def _cluster_label(logic_key: str) -> str:
    lk = logic_key.lower()
    if 'breakout' in lk or 'breakdown' in lk:
        return 'Breakout confirmation watch'
    if 'volume' in lk or 'vol' in lk:
        return 'High momentum participation'
    if 'sector' in lk or 'rotation' in lk:
        return 'Sector leadership extension'
    if 'bear' in lk or 'distribution' in lk or 'avoid' in lk:
        return 'Distribution risk monitor'
    if 'govt' in lk or 'macro' in lk or 'policy' in lk:
        return 'Macro headline sensitivity'
    return 'Technical setup monitor'


def cluster_watchlist(items: List[dict]) -> List[dict]:
    """
    Group watch items by compressed logic theme.
    Returns cluster dicts: {label, symbols, members, summary}.
    """
    buckets: Dict[str, List[dict]] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        sym = _symbol(item)
        if not sym:
            continue
        key = _logic_key(item)
        buckets.setdefault(key, []).append(item)

    ranked = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    clusters: List[dict] = []
    for logic_key, members in ranked[:MAX_CLUSTERS]:
        syms = []
        for m in members:
            s = _symbol(m)
            if s and s not in syms:
                syms.append(s)
            if len(syms) >= MAX_NAMES_PER_CLUSTER:
                break
        if not syms:
            continue
        label = _cluster_label(logic_key)
        clusters.append({
            'label': label,
            'symbols': syms,
            'members': members[:MAX_NAMES_PER_CLUSTER],
            'summary': f"{label}: {', '.join(syms)}",
        })
    return clusters


def compress_watchlist_for_display(items: List[dict]) -> Dict[str, Any]:
    """Produce compressed watchlist for Telegram/GUI."""
    clusters = cluster_watchlist(items)
    flat = []
    seen = set()
    for c in clusters:
        for s in c.get('symbols') or []:
            if s not in seen:
                flat.append(s)
                seen.add(s)
    lines = [c['summary'] for c in clusters]
    return {
        'clusters': clusters,
        'symbols': flat,
        'compressed_lines': lines,
        'compressed_text': '\n'.join(lines) if lines else '',
    }


def apply_cluster_to_tiers(tiers: dict) -> dict:
    """Attach cluster metadata to tiered opportunities without changing counts."""
    out = dict(tiers or {})
    watch = list(out.get('watch') or [])
    compressed = compress_watchlist_for_display(watch)
    out['watch'] = watch
    out['watch_clusters'] = compressed.get('clusters') or []
    out['watch_compressed'] = compressed.get('compressed_text') or ''
    return out
