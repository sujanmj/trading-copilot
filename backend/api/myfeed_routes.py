"""
My Feed API routes — canonical user feed store (Stage 50A hotfix).

GUI and Telegram share the same text-only SQLite store at get_data_path('my_feed.db').
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Body, Depends, File, Query, UploadFile


def register_myfeed_routes(
    app,
    verify_api_key,
    sanitize_json_value: Callable[[Any], Any],
) -> None:
    auth = [Depends(verify_api_key)]

    def _base_payload() -> dict[str, str]:
        from backend.storage.data_paths import get_data_root

        return {
            'source': 'canonical_user_feed',
            'data_root': get_data_root().as_posix(),
        }

    @app.get('/api/myfeed', dependencies=auth)
    def api_myfeed_list(limit: int = Query(40, ge=1, le=200), today_only: bool = False):
        from backend.my_feed.feed_processor import list_feed_items, sanitize_item_for_api

        items = [sanitize_item_for_api(row) for row in list_feed_items(limit=limit, today_only=today_only)]
        return sanitize_json_value({
            'ok': True,
            'items': items,
            'count': len(items),
            **_base_payload(),
        })

    @app.get('/api/myfeed/today', dependencies=auth)
    def api_myfeed_today(limit: int = Query(40, ge=1, le=200)):
        from backend.my_feed.feed_processor import list_feed_items, sanitize_item_for_api

        items = [sanitize_item_for_api(row) for row in list_feed_items(limit=limit, today_only=True)]
        return sanitize_json_value({
            'ok': True,
            'items': items,
            'count': len(items),
            'today_only': True,
            **_base_payload(),
        })

    @app.get('/api/myfeed/scan', dependencies=auth)
    def api_myfeed_scan(today_only: bool = False):
        from backend.my_feed.feed_processor import sanitize_item_for_api, scan_feed_summary

        summary = scan_feed_summary(today_only=today_only)
        items = [sanitize_item_for_api(row) for row in (summary.get('items') or [])[:20]]
        return sanitize_json_value({
            'ok': True,
            'total': summary.get('total', 0),
            'high_impact': summary.get('high_impact', 0),
            'risk_alerts': summary.get('risk_alerts', 0),
            'watch_items': summary.get('watch_items', 0),
            'items': items,
            **_base_payload(),
        })

    def _ingest_text_payload(body: dict[str, Any]) -> dict[str, Any]:
        from backend.my_feed.feed_processor import ingest_text, sanitize_item_for_api

        text = str((body or {}).get('text') or '').strip()
        source = str((body or {}).get('source') or 'gui_text').strip() or 'gui_text'
        if source not in {'gui_text', 'telegram_text'}:
            source = 'gui_text'
        result = ingest_text(text, source=source)
        item = sanitize_item_for_api(result.get('record') or {})
        saved = bool(result.get('ok')) and bool(item)
        saved_count = int(result.get('saved_count') or (1 if saved else 0))
        return sanitize_json_value({
            'ok': bool(result.get('ok')),
            'saved': saved,
            'saved_count': saved_count,
            'message': str(result.get('message') or ('Saved 1 item' if saved else '')),
            'feed_id': item.get('feed_id') if item else None,
            'item': item if item else None,
            'reply': result.get('reply'),
            'duplicate': bool(result.get('duplicate')),
            **_base_payload(),
        })

    @app.post('/api/myfeed', dependencies=auth)
    def api_myfeed_post(body: dict = Body(...)):
        return _ingest_text_payload(body or {})

    @app.post('/api/myfeed/text', dependencies=auth)
    def api_myfeed_text(body: dict = Body(...)):
        return _ingest_text_payload(body or {})

    @app.post('/api/myfeed/archive/{feed_id}', dependencies=auth)
    def api_myfeed_archive(feed_id: str):
        from backend.my_feed.feed_processor import archive_feed_item

        archived = archive_feed_item(feed_id)
        return sanitize_json_value({
            'ok': archived,
            'archived': archived,
            'feed_id': feed_id,
            **_base_payload(),
        })

    @app.post('/api/myfeed/screenshot', dependencies=auth)
    async def api_myfeed_screenshot(file: UploadFile = File(...)):
        await file.read()
        return sanitize_json_value({
            'ok': False,
            'saved': False,
            'saved_count': 0,
            'message': 'My Feed is text-only. Paste news text and save.',
            'feed_id': None,
            'item': None,
            'reply': None,
            'duplicate': False,
            **_base_payload(),
        })
