"""
LIVE NEWS TRACKER — unified provider registry (AstraEdge 52H).

Delegates to news_provider_registry for all enabled RSS/official sources.
Writes news_feed.json and live_news_feed.json.
"""

from __future__ import annotations

from datetime import datetime

from backend.collectors.news_provider_registry import run_unified_news_refresh


def run_live_news_tracker():
    print('=' * 60)
    print('LIVE NEWS TRACKER — Unified Provider Registry')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)

    result = run_unified_news_refresh(send_macro_alerts=False)
    print(f"Sources checked: {result.get('sources_checked')}")
    print(f"Items found: {result.get('items_found')}")
    print(f"New items: {result.get('new_items')}")
    print(f"Errors: {result.get('error_count')}")
    if result.get('errors'):
        for err in (result.get('errors') or [])[:5]:
            print(f'  [WARN] {err}')
    print('=' * 60)
    return result


if __name__ == '__main__':
    try:
        run_live_news_tracker()
    except Exception as e:
        print(f'[FATAL] live_news_tracker crashed: {e}')
        import traceback
        traceback.print_exc()
