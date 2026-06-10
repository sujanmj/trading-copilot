#!/usr/bin/env python3
"""Unit tests — Reddit removed from user-facing surfaces (Stage 50A)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'REDDIT_REMOVED_FULLY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.aihub_tab_payloads import VALID_TABS, _TAB_BUILDERS
    from backend.runtime.feed_registry import CANONICAL_FEEDS, feed_count_total
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_SEQUENCE

    if 'reddit' in VALID_TABS:
        return _fail('VALID_TABS must not include reddit')
    if 'reddit' in _TAB_BUILDERS:
        return _fail('_TAB_BUILDERS must not include reddit')
    if 'reddit' in CANONICAL_FEEDS:
        return _fail('CANONICAL_FEEDS must not include reddit')
    if feed_count_total() != 7:
        return _fail(f'expected 7 canonical feeds got {feed_count_total()}')
    if '/aihub reddit' in FULL_SNAPSHOT_SEQUENCE:
        return _fail('/full must not include /aihub reddit')

    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    if re.search(r'data-tab=["\']reddit["\']', index_html):
        return _fail('frontend AI Hub must not expose reddit tab')

    api_server = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if '/api/reddit' in api_server:
        return _fail('api_server must not expose /api/reddit')

    help_text = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if re.search(r'/aihub\s+reddit', help_text, re.I):
        return _fail('telegram help must not mention /aihub reddit')

    print('REDDIT_REMOVED_FULLY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
