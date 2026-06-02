#!/usr/bin/env python3
"""
Validate Market Router dedicated workspace wiring (Stage 43C fix).

Checks:
  - frontend package exists
  - top-level Router button exists
  - Router workspace/view exists
  - /api/debug/market-router is referenced
  - AI Hub does not repeat full Market Router block inside tab panels
  - Router styling is present

Prints exactly FRONTEND_ROUTER_WORKSPACE_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
PACKAGE = FRONTEND / 'package.json'
INDEX = FRONTEND / 'index.html'
WORKSPACE = FRONTEND / 'components' / 'WorkspaceManager.js'
ROUTER = FRONTEND / 'components' / 'MarketRouterCard.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_ROUTER_WORKSPACE_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def _ai_hub_tab_panels_block(index_src: str) -> str:
    match = re.search(
        r'<div class="ai-hub-scroll"[^>]*>([\s\S]*?)</div>\s*<div class="ask-bar">',
        index_src,
        re.DOTALL,
    )
    return match.group(1) if match else ''


def main() -> int:
    if not FRONTEND.is_dir():
        return _fail('frontend/ directory missing')

    if not PACKAGE.is_file():
        return _fail('frontend/package.json missing')

    for path in (INDEX, WORKSPACE, ROUTER):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    workspace_src = _read(WORKSPACE)
    router_src = _read(ROUTER)

    if 'routerNavBtn' not in index_src or '🌍 Router' not in index_src:
        return _fail('top-level Router nav button missing')

    if 'routerMainPanel' not in index_src or 'workspace-router' not in index_src:
        return _fail('Router workspace/view missing')

    if 'data-workspace="router"' not in index_src:
        return _fail('Router workspace CSS selector missing')

    if '/api/debug/market-router' not in router_src:
        return _fail('MarketRouterCard.js must reference /api/debug/market-router')

    router_panel = re.search(
        r'id="routerMainPanel"[\s\S]*?id="marketRouterCardHost"',
        index_src,
    )
    if not router_panel:
        return _fail('marketRouterCardHost must live inside routerMainPanel')

    hub_tabs = _ai_hub_tab_panels_block(index_src)
    if not hub_tabs:
        return _fail('could not locate AI Hub scroll/tab panel block')

    for token in ('marketRouterCardHost', 'market-router-card', 'mr-grid'):
        if token in hub_tabs:
            return _fail(
                f'AI Hub tab panels must not repeat full Market Router block ({token!r})'
            )

    if 'aiHubRouterStatusHost' not in index_src:
        return _fail('AI Hub compact router status host missing')

    if "'router'" not in workspace_src or 'routerNavBtn' not in workspace_src:
        return _fail('WorkspaceManager.js missing router workspace wiring')

    if "setActiveWorkspace('router'" not in workspace_src.replace('"', "'"):
        return _fail('WorkspaceManager.js must activate router workspace on nav click')

    style_tokens = (
        '.router-nav-btn',
        '.router-main-panel',
        '#marketRouterCardHost',
        '.market-router-card',
    )
    for token in style_tokens:
        if token not in index_src:
            return _fail(f'Router styling missing: {token!r}')

    print('FRONTEND_ROUTER_WORKSPACE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
