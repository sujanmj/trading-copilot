#!/usr/bin/env python3
"""
Validate Stage 44G in-app source viewer behavior (browser + Electron).

Prints exactly FRONTEND_SOURCE_VIEWER_BEHAVIOR_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'
VIEWER = PROJECT_ROOT / 'frontend' / 'components' / 'SourceFeedViewer.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_SOURCE_VIEWER_BEHAVIOR_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (INDEX, WORKSPACE, VIEWER):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    viewer_src = VIEWER.read_text(encoding='utf-8')

    load_site_match = re.search(r'function loadSite\([\s\S]*?\n  \}', index_src)
    if not load_site_match:
        return _fail('loadSite function missing in index.html')
    load_site_src = load_site_match.group(0)

    if re.search(
        r'if \(GUI_RUNTIME\.isBrowser\)[\s\S]*?window\.open\([\s\S]*?return;',
        load_site_src,
    ):
        return _fail('loadSite must not immediately window.open in browser mode')

    if 'WorkspaceManager.openBrowser' not in load_site_src:
        return _fail('loadSite must delegate to WorkspaceManager.openBrowser')

    open_browser_match = re.search(r'function openBrowser\([\s\S]*?\n  \}', workspace_src)
    if not open_browser_match:
        return _fail('openBrowser function missing')
    open_browser_src = open_browser_match.group(0)

    if re.search(
        r'if \(isBrowserGui\(\)\) \{[\s\S]*?window\.open\([\s\S]*?return;',
        open_browser_src,
    ):
        return _fail('openBrowser must not immediately window.open in browser mode')

    if "setActiveWorkspace('browser'" not in open_browser_src:
        return _fail('openBrowser must switch to browser workspace')

    if re.search(r'if \(isBrowserGui\(\)\) \{[\s\S]*?iframe', open_browser_src):
        return _fail('browser mode must use Source Feed Viewer, not iframe embed')

    if 'SourceFeedViewer' not in open_browser_src and 'showSourceFeedViewer' not in open_browser_src:
        return _fail('browser mode must open internal Source Feed Viewer')

    if 'No cached items for this source yet' not in viewer_src:
        return _fail('Source Feed Viewer empty state message missing')

    if 'Open External' not in index_src and 'Open External' not in viewer_src:
        return _fail('Open External action missing')

    if 'browserExternal' not in workspace_src:
        return _fail('toolbar Open External wiring missing')

    if 'data-workspace="placeholder"' not in index_src:
        return _fail('default workspace must be placeholder dashboard')

    if "setActiveWorkspace('placeholder'" not in workspace_src:
        return _fail('WorkspaceManager init must default to placeholder view')

    if 'clearPersistedSourceViewState' not in workspace_src:
        return _fail('WorkspaceManager must clear persisted external source view state')

    if "toolbar.style.display = (next === 'browser')" not in workspace_src:
        return _fail('browser toolbar must show in browser workspace')

    if 'webview' not in open_browser_src:
        return _fail('Electron mode must retain webview in-app behavior')

    if 'did-fail-load' not in open_browser_src:
        return _fail('Electron webview failure must fall back to Source Feed Viewer')

    print('FRONTEND_SOURCE_VIEWER_BEHAVIOR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
