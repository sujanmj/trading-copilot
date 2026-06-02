#!/usr/bin/env python3
"""
Validate Stage 44O frontend Source Feed Viewer — flat nav, internal cached feed.

Prints exactly FRONTEND_SOURCE_FEED_VIEWER_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_SOURCE_FEED_VIEWER_FAIL: {msg}', file=sys.stderr)
    return 1


def _function_body(src: str, name: str) -> str:
    match = re.search(rf'function {re.escape(name)}\([^)]*\)\s*\{{', src)
    if not match:
        return ''
    start = match.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    return src[start:i - 1]


def main() -> int:
    for path in (INDEX, WORKSPACE):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    workspace_src = WORKSPACE.read_text(encoding='utf-8')

    if 'renderSourceFeed' not in index_src:
        return _fail('renderSourceFeed handler missing in index.html')

    if '/api/debug/source-feed' not in index_src:
        return _fail('index must fetch /api/debug/source-feed')

    if 'id="brokerSourceRow"' not in index_src or 'id="newsSourceRow"' not in index_src:
        return _fail('flat broker/news source rows required')

    if 'data-source="ET"' not in index_src or 'data-source="MC"' not in index_src:
        return _fail('news source buttons must include data-source keys')

    if 'data-source="Angel"' not in index_src or 'data-source="Portfolio"' not in index_src:
        return _fail('broker source buttons must include data-source keys')

    for token in ('Refresh Source', 'Back to Dashboard', 'Open External'):
        if token not in index_src:
            return _fail(f'missing UI token: {token}')

    if 'No cached items for this source yet. Use Refresh Source or Open External.' not in index_src:
        return _fail('empty state message missing')

    bind_body = _function_body(index_src, 'bindAstraSourceItemClick')
    open_body = _function_body(index_src, 'astraOpenSourceItem')
    if 'astraOpenSourceItem' not in bind_body and 'renderSourceFeed' not in bind_body:
        return _fail('source click handler must route to source viewer')

    if open_body:
        if 'ASTRA_IS_ELECTRON' not in open_body:
            return _fail('source routing must branch on ASTRA_IS_ELECTRON')
        if 'renderEmbeddedSourceBrowser' not in open_body or (
            'renderSourceFeed' not in open_body
            and 'astraOpenWebExternalSource' not in open_body
        ):
            return _fail('source routing must call renderEmbeddedSourceBrowser and web external handler')
    elif 'renderSourceFeed' not in bind_body:
        return _fail('source click handler must call renderSourceFeed in browser mode')

    feed_body = _function_body(index_src, 'renderSourceFeed')
    if feed_body and re.search(r'<iframe\b', feed_body, re.IGNORECASE):
        return _fail('browser mode renderSourceFeed must not embed iframe by default')

    if 'Web mode cannot embed some external sites' not in index_src:
        return _fail('browser mode web embed note missing')

    if '#browserToolbar { display: none !important; }' not in index_src:
        return _fail('browser toolbar must stay hidden')

    if 'astraFetchFeed' not in index_src and 'fetchWithTimeout' not in index_src:
        return _fail('source feed fetch must use authenticated fetch helper')

    if 'function openSourceFeed' not in workspace_src:
        return _fail('WorkspaceManager must define openSourceFeed')

    open_browser_match = re.search(r'function openBrowser\([\s\S]*?\n  \}', workspace_src)
    if open_browser_match:
        open_browser_src = open_browser_match.group(0)
        if re.search(
            r'if \(isBrowserGui\(\)\) \{[\s\S]*?iframe',
            open_browser_src,
        ):
            return _fail('browser mode must not embed iframe for external sites')

    if 'clearPersistedSourceLanding' not in index_src:
        return _fail('must clear persisted source landing on load')

    print('FRONTEND_SOURCE_FEED_VIEWER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
