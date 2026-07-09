"""
User-controlled feed remove/restore — Phase 4B.18H / AstraEdge 52F.

Soft-removes bad feed rows from active memory without hard-deleting audit data.
"""

from __future__ import annotations

import re
from typing import Any

FEED_ID_PATTERN = re.compile(r'^[a-f0-9]{8,16}$')
REMOVED_FROM_VIEWS = 'myfeed,catalyst,macro_memory,radar_guard'

FEED_REMOVE_USAGE = (
    'FEED_REMOVE_USAGE\n'
    'Example: /feed remove c3d1d89b1874'
)


def is_valid_feed_id(feed_id: str) -> bool:
    return bool(FEED_ID_PATTERN.match(str(feed_id or '').strip().lower()))


def _is_macro_feed_item(item: dict[str, Any]) -> bool:
    if not item:
        return False
    if str(item.get('event_type') or '') == 'macro_shock':
        return True
    if str(item.get('source') or '') in ('macro_shock_sentinel', 'emergency_macro'):
        return True
    payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
    return str(payload.get('feed_type') or '') == 'macro_shock'


def remove_feed_item(feed_id: str) -> dict[str, Any]:
    from backend.my_feed.cache_invalidation import invalidate_myfeed_caches
    from backend.my_feed.my_feed_db import get_item, remove_item_by_user

    fid = str(feed_id or '').strip().lower()
    if not fid:
        return {'ok': False, 'code': 'FEED_REMOVE_USAGE', 'text': FEED_REMOVE_USAGE}
    if not is_valid_feed_id(fid):
        return {'ok': False, 'code': 'FEED_REMOVE_USAGE', 'text': FEED_REMOVE_USAGE}

    existing = get_item(fid)
    if not existing:
        return {
            'ok': False,
            'code': 'FEED_NOT_FOUND',
            'text': f'FEED_NOT_FOUND\nfeed_id={fid}',
        }

    result = remove_item_by_user(fid)
    if not result:
        return {
            'ok': False,
            'code': 'FEED_NOT_FOUND',
            'text': f'FEED_NOT_FOUND\nfeed_id={fid}',
        }
    if result.get('already_removed'):
        return {
            'ok': False,
            'code': 'FEED_ALREADY_REMOVED',
            'text': f'FEED_ALREADY_REMOVED\nfeed_id={fid}',
        }

    macro_cleanup: dict[str, Any] = {}
    if _is_macro_feed_item(existing):
        from backend.trading.macro_shock_sentinel import deactivate_macro_shock_for_feed

        macro_cleanup = deactivate_macro_shock_for_feed(fid)

    try:
        invalidate_myfeed_caches()
    except Exception:
        pass

    text = '\n'.join([
        'FEED_REMOVED',
        f'feed_id={fid}',
        f'old_status={result.get("old_status")}',
        f'new_status={result.get("new_status")}',
        'active=false',
        f'removed_from={REMOVED_FROM_VIEWS}',
    ])
    return {
        'ok': True,
        'code': 'FEED_REMOVED',
        'text': text,
        'feed_id': fid,
        'macro_cleanup': macro_cleanup,
        'item': result.get('item'),
    }


def restore_feed_item(feed_id: str) -> dict[str, Any]:
    from backend.my_feed.cache_invalidation import invalidate_myfeed_caches
    from backend.my_feed.my_feed_db import get_item, restore_item_by_user

    fid = str(feed_id or '').strip().lower()
    if not fid:
        return {'ok': False, 'code': 'FEED_REMOVE_USAGE', 'text': FEED_REMOVE_USAGE}
    if not is_valid_feed_id(fid):
        return {'ok': False, 'code': 'FEED_REMOVE_USAGE', 'text': FEED_REMOVE_USAGE}

    existing = get_item(fid)
    if not existing:
        return {
            'ok': False,
            'code': 'FEED_NOT_FOUND',
            'text': f'FEED_NOT_FOUND\nfeed_id={fid}',
        }

    result = restore_item_by_user(fid)
    if not result:
        return {
            'ok': False,
            'code': 'FEED_NOT_FOUND',
            'text': f'FEED_NOT_FOUND\nfeed_id={fid}',
        }
    if result.get('not_removed'):
        return {
            'ok': False,
            'code': 'FEED_NOT_REMOVED',
            'text': f'FEED_NOT_FOUND\nfeed_id={fid}\nreason=not_removed',
        }

    restored_item = result.get('item') or get_item(fid) or {}
    macro_restore: dict[str, Any] = {}
    if _is_macro_feed_item(restored_item):
        from backend.trading.macro_shock_sentinel import restore_macro_shock_for_feed

        macro_restore = restore_macro_shock_for_feed(fid, restored_item)

    try:
        invalidate_myfeed_caches()
    except Exception:
        pass

    status = str(result.get('status') or 'UNVERIFIED')
    text = '\n'.join([
        'FEED_RESTORED',
        f'feed_id={fid}',
        'active=true',
        f'status={status}',
    ])
    return {
        'ok': True,
        'code': 'FEED_RESTORED',
        'text': text,
        'feed_id': fid,
        'status': status,
        'macro_restore': macro_restore,
        'item': restored_item,
    }
