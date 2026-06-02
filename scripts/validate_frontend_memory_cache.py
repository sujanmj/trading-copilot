#!/usr/bin/env python3
"""
Validate Stage 43B Memory tab dashboard cache.

Checks:
  - In-memory dashboard cache state with 5-minute TTL
  - Cached render on tab return without full loading reset
  - Manual Refresh Memory forces reload

Prints exactly FRONTEND_MEMORY_CACHE_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_MEMORY_CACHE_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (PANEL, WORKSPACE, INDEX):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    panel_src = _read(PANEL)
    workspace_src = _read(WORKSPACE)
    index_src = _read(INDEX)

    for token in ('dashboardCache', 'MEMORY_CACHE_TTL_MS', 'isMemoryCacheValid', 'paintDashboard'):
        if token not in panel_src:
            return _fail(f'MarketMemoryPanel.js missing cache marker: {token!r}')

    if not re.search(r'MEMORY_CACHE_TTL_MS\s*=\s*5\s*\*\s*60\s*\*\s*1000', panel_src):
        return _fail('MarketMemoryPanel must define 5-minute MEMORY_CACHE_TTL_MS')

    if 'cached ${ageMin} min ago' not in panel_src and 'cached ${' not in panel_src:
        return _fail('MarketMemoryPanel must show cached age label')

    if 'refreshing…' not in panel_src and 'refreshing' not in panel_src:
        return _fail('MarketMemoryPanel must show small refreshing indicator')

    if 'loadInto(el, targetKey, true)' not in panel_src and 'loadInto(container, targetKey, true)' not in panel_src:
        return _fail('Refresh Memory must force reload via loadInto(..., true)')

    if not re.search(
        r'if\s*\(\s*!force\s*&&\s*hasCache\s*&&\s*cacheValid\s*\)',
        panel_src,
    ):
        return _fail('loadInto must render cached dashboard when cache is still valid')

    if 'renderLoadingHtml()' not in panel_src:
        return _fail('MarketMemoryPanel must keep full loading HTML for first load')

    if 'MarketMemoryPanel.loadMain' not in workspace_src:
        return _fail('WorkspaceManager must call MarketMemoryPanel.loadMain for memory workspace')

    if 'mm-cache-label' not in index_src:
        return _fail('index.html missing mm-cache-label styling')

    print('FRONTEND_MEMORY_CACHE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
