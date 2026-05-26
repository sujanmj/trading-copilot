"""
Lightweight in-memory conversational cache — reduces duplicate AI calls.

Semantic-lite normalization only (no vector DB). Bounded size, short TTL.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

_MAX_ENTRIES = 80
_lock = threading.Lock()
_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

_STRATEGIC_USE_CASES = frozenset({
    'final_synthesis', 'manual_refresh', 'overnight_brief', 'premarket_brief',
    'postmortem', 'ask_deep', 'sonnet',
})

_TTL_BY_ROUTE = {
    'telegram_ask': 60,
    'ask_basic': 90,
    'ask_conversational': 90,
    'ops_assistant': 90,
    'lightweight_summary': 90,
    'ask_haiku': 90,
    'alert_analysis': 60,
    'midday_check': 120,
    'market_situation': 120,
}


def normalize_question(text: str) -> str:
    if not text:
        return ''
    t = text.lower().strip()
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t[:500]


def _cache_key(use_case: str, prompt: str) -> str:
    return f"{use_case}|{normalize_question(prompt)}"


def ttl_for_route(use_case: str) -> int:
    return int(_TTL_BY_ROUTE.get(use_case, 60))


def should_use_cache(use_case: str, tier: str) -> bool:
    if use_case in _STRATEGIC_USE_CASES or tier == 'strategic':
        return False
    if tier not in ('conversational', 'gemini'):
        return False
    return True


def _prune_locked(now: float) -> None:
    expired = [k for k, v in _cache.items() if float(v.get('expires', 0)) <= now]
    for k in expired:
        _cache.pop(k, None)
    while len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)


def get_cached(use_case: str, prompt: str) -> Optional[dict]:
    key = _cache_key(use_case, prompt)
    now = time.time()
    with _lock:
        _prune_locked(now)
        entry = _cache.get(key)
        if not entry:
            return None
        if float(entry.get('expires', 0)) <= now:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return dict(entry.get('result') or {})


def set_cached(use_case: str, prompt: str, result: dict) -> None:
    if not result or not result.get('success'):
        return
    key = _cache_key(use_case, prompt)
    ttl = ttl_for_route(use_case)
    now = time.time()
    with _lock:
        _prune_locked(now)
        _cache[key] = {
            'expires': now + ttl,
            'result': {
                'success': True,
                'text': result.get('text', ''),
                'model': result.get('model', ''),
                'provider': result.get('provider', ''),
                'estimated_cost': 0.0,
                'cache_hit': True,
                'cached': True,
            },
        }
        _cache.move_to_end(key)


def cache_stats() -> dict:
    now = time.time()
    with _lock:
        active = sum(1 for v in _cache.values() if float(v.get('expires', 0)) > now)
        return {'entries': len(_cache), 'active': active, 'max_entries': _MAX_ENTRIES}
