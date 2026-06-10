"""
My Feed cache invalidation for Telegram and AIHub (Stage 50C hotfix 2).
"""

from __future__ import annotations

from pathlib import Path

from backend.storage.data_paths import get_data_path
from backend.utils.config import DATA_DIR

_MYFEED_TELEGRAM_CACHE: list[dict] | None = None


def invalidate_myfeed_caches() -> dict[str, int]:
    """Bust in-memory and on-disk My Feed caches used by Telegram/AIHub formatters."""
    global _MYFEED_TELEGRAM_CACHE
    removed = 0
    _MYFEED_TELEGRAM_CACHE = None

    candidates = [
        get_data_path('telegram_myfeed_cache.json'),
        get_data_path('aihub_myfeed_section.json'),
        DATA_DIR / 'cache' / 'aihub_tabs' / 'myfeed.json',
    ]
    for path in candidates:
        try:
            if Path(path).is_file():
                Path(path).unlink()
                removed += 1
        except OSError:
            pass

    try:
        flag = DATA_DIR / '_runtime_cache_invalidate.flag'
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text('myfeed_reprocess', encoding='utf-8')
    except OSError:
        pass

    return {'removed_files': removed}


def cache_myfeed_items_for_telegram(items: list[dict]) -> None:
    global _MYFEED_TELEGRAM_CACHE
    _MYFEED_TELEGRAM_CACHE = list(items)


def get_cached_myfeed_items_for_telegram() -> list[dict] | None:
    return _MYFEED_TELEGRAM_CACHE


def load_myfeed_items_for_telegram(*, limit: int = 12, force_refresh: bool = False) -> list[dict]:
    if not force_refresh:
        cached = get_cached_myfeed_items_for_telegram()
        if cached is not None:
            return cached
    from backend.my_feed.feed_processor import list_feed_items, sanitize_item_for_api

    items = [sanitize_item_for_api(row) for row in list_feed_items(limit=limit)]
    cache_myfeed_items_for_telegram(items)
    return items
