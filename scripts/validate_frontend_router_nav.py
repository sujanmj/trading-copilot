#!/usr/bin/env python3
"""
Validate Stage 43B Market Router navigation split.

Checks:
  - 🌍 Router top nav button and router workspace
  - Full Market Router card host in router workspace (not AI Hub)
  - AI Hub compact router status pill only

Prints exactly FRONTEND_ROUTER_NAV_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'
ROUTER = PROJECT_ROOT / 'frontend' / 'components' / 'MarketRouterCard.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_ROUTER_NAV_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (INDEX, WORKSPACE, ROUTER):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    workspace_src = _read(WORKSPACE)
    router_src = _read(ROUTER)

    if 'routerNavBtn' not in index_src or '🌍 Router' not in index_src:
        return _fail('index.html missing 🌍 Router nav button (routerNavBtn)')

    if 'routerMainPanel' not in index_src or 'workspace-router' not in index_src:
        return _fail('index.html missing router workspace panel')

    if 'data-workspace="router"' not in index_src:
        return _fail('index.html missing router workspace CSS selector')

    hub_scroll = re.search(
        r'<div class="ai-hub-scroll"[^>]*>[\s\S]*?</div>\s*<div class="ask-bar">',
        index_src,
        re.DOTALL,
    )
    if not hub_scroll:
        return _fail('could not locate ai-hub-scroll block')
    if 'marketRouterCardHost' in hub_scroll.group(0):
        return _fail('AI Hub must not mount full marketRouterCardHost inside ai-hub-scroll')

    if 'aiHubRouterStatusHost' not in index_src:
        return _fail('index.html missing AI Hub compact status host (aiHubRouterStatusHost)')

    if 'market-router-card' in hub_scroll.group(0) or 'mr-grid' in hub_scroll.group(0):
        return _fail('AI Hub must not include full Market Router card markup')

    if index_src.find('marketRouterCardHost') == -1:
        return _fail('index.html must define marketRouterCardHost in router workspace')

    router_panel = re.search(
        r'id="routerMainPanel"[\s\S]*?marketRouterCardHost',
        index_src,
    )
    if not router_panel:
        return _fail('marketRouterCardHost must live inside routerMainPanel workspace')

    for token in ("'router'", 'routerNavBtn', 'mountCompact'):
        if token not in workspace_src:
            return _fail(f'WorkspaceManager.js missing marker: {token!r}')

    for token in ('renderCompactStatusHtml', 'mountCompact', 'mr-compact-status'):
        if token not in router_src:
            return _fail(f'MarketRouterCard.js missing marker: {token!r}')

    if 'mountCompact' not in index_src:
        return _fail('index.html must mount compact router status in AI Hub')

    print('FRONTEND_ROUTER_NAV_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
