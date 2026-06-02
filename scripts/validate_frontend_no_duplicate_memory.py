#!/usr/bin/env python3
"""
Validate frontend has no duplicate Memory / Source Freshness layouts (Stage 18B).

Scans frontend files for:
  - top-level Memory route (memoryNavBtn, memoryMainPanel)
  - Memory active view hides AI Hub
  - SourceFreshness not mounted unconditionally in both layouts
  - "Canonical Market Memory" title marker
  - activeView=memory debug footer marker

Prints exactly FRONTEND_NO_DUPLICATE_MEMORY_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
INDEX = FRONTEND / 'index.html'
PANEL = FRONTEND / 'components' / 'MarketMemoryPanel.js'
FRESHNESS = FRONTEND / 'components' / 'SourceFreshnessCard.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_NO_DUPLICATE_MEMORY_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (INDEX, PANEL, FRESHNESS):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    panel_src = _read(PANEL)
    freshness_src = _read(FRESHNESS)

    if 'memoryNavBtn' not in index_src or '🧠 Memory' not in index_src:
        return _fail('index.html missing top nav Memory button (memoryNavBtn)')

    if 'memoryMainPanel' not in index_src or 'memoryMainContent' not in index_src:
        return _fail('index.html missing memoryMainPanel / memoryMainContent')

    if 'memory-view-active' not in index_src:
        return _fail('index.html missing memory-view-active layout class')

    hide_ai = re.search(
        r'\.main\.memory-view-active\s+\.ai-panel\s*\{[^}]*display\s*:\s*none',
        index_src,
        re.IGNORECASE | re.DOTALL,
    )
    if not hide_ai:
        return _fail('index.html must hide .ai-panel when memory-view-active')

    if 'Canonical Market Memory' not in panel_src:
        return _fail('MarketMemoryPanel.js missing Canonical Market Memory title')

    if 'activeView=memory' not in panel_src:
        return _fail('MarketMemoryPanel.js missing activeView=memory debug footer')

    if 'renderMemTabShortcut' not in panel_src:
        return _fail('MarketMemoryPanel.js must expose Mem tab shortcut instead of full dashboard')

    if 'Open full Memory Dashboard' not in panel_src:
        return _fail('MarketMemoryPanel.js missing Open full Memory Dashboard shortcut')

    if 'includeFreshness' not in panel_src or "targetKey === 'main'" not in panel_src:
        return _fail('MarketMemoryPanel.js must gate SourceFreshness to main memory view only')

    if 'setMemoryViewActive' not in panel_src:
        return _fail('MarketMemoryPanel.js must toggle memory-view-active layout')

    if 'SourceFreshnessCard.unmount' not in panel_src:
        return _fail('MarketMemoryPanel.js must unmount AI Hub freshness when Memory view opens')

    if 'function unmount' not in freshness_src and 'unmount(containerOrSelector)' not in freshness_src:
        return _fail('SourceFreshnessCard.js missing unmount helper')

    if 'SourceFreshnessCard.renderCardHtml' not in panel_src:
        return _fail('MarketMemoryPanel.js must render Source Freshness in Memory main view')

    if 'sourceFreshnessCardHost' in index_src:
        return _fail('index.html must not define AI Hub SourceFreshness host (Memory-only freshness)')

    if re.search(r'mountSourceFreshnessInAiHub|SourceFreshnessCard\.mount\s*\(', index_src):
        return _fail('index.html must not mount SourceFreshnessCard in AI Hub')

    tab_loads_dashboard = re.search(
        r"MarketMemoryPanel\.loadTab\(\)|loadInto\([^)]*tab-memory",
        index_src,
    )
    if tab_loads_dashboard and 'renderMemTabShortcut' not in index_src:
        return _fail('index.html Mem tab must not load full dashboard without shortcut guard')

    print('FRONTEND_NO_DUPLICATE_MEMORY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
