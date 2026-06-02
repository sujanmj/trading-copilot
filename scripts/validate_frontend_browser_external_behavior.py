#!/usr/bin/env python3
"""
Validate Stage 44E browser external-source behavior.

Prints exactly FRONTEND_BROWSER_EXTERNAL_BEHAVIOR_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROWSER_EXTERNAL_BEHAVIOR_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (INDEX, WORKSPACE):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    workspace_src = WORKSPACE.read_text(encoding='utf-8')

    if 'GUI_RUNTIME.isBrowser' not in index_src or "window.open(url, '_blank'" not in index_src:
        return _fail('index.html loadSite must open external URLs in browser mode')

    if 'body.gui-browser-mode .browser-toolbar { display: none !important; }' not in index_src:
        return _fail('browser toolbar must be hidden in browser mode')

    if 'Open External' not in index_src:
        return _fail('Open External toolbar button must remain for Electron fallback')

    if 'data-workspace="placeholder"' not in index_src:
        return _fail('default workspace must be placeholder dashboard')

    if 'isBrowserGui()' not in workspace_src or "window.open(url, '_blank'" not in workspace_src:
        return _fail('WorkspaceManager must open external URLs in browser mode')

    open_browser_match = re.search(
        r'function openBrowser\([\s\S]*?\n  \}',
        workspace_src,
    )
    if not open_browser_match:
        return _fail('openBrowser function missing')
    open_browser_src = open_browser_match.group(0)

    browser_early_open = re.search(
        r'if \(isBrowserGui\(\)\) \{[\s\S]*?window\.open\([\s\S]*?return;',
        open_browser_src,
    )
    if not browser_early_open:
        return _fail('browser mode must window.open and return before embedding')

    if 'setActiveWorkspace(\'browser\'' in browser_early_open.group(0):
        return _fail('browser mode must not switch to browser workspace for external links')

    if 'Browser mode does not embed external sites here' in workspace_src:
        return _fail('browser mode must not show embedded external placeholder')

    if 'toolbar.style.display = (next === \'browser\' && !isBrowserGui())' not in workspace_src:
        return _fail('browser toolbar must stay hidden in browser GUI mode')

    if "setActiveWorkspace('placeholder'" not in workspace_src:
        return _fail('WorkspaceManager init must default to placeholder view')

    if 'Open External' not in workspace_src and 'browserExternal' not in workspace_src:
        return _fail('Electron Open External fallback wiring missing')

    print('FRONTEND_BROWSER_EXTERNAL_BEHAVIOR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
