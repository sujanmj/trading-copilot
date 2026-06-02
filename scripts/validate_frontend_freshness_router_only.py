#!/usr/bin/env python3
"""
Validate Stage 44O — Intelligence Freshness only in Router; AI Hub compact chip.

Prints exactly FRONTEND_FRESHNESS_ROUTER_ONLY_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'
FRESHNESS = PROJECT_ROOT / 'frontend' / 'components' / 'SourceFreshnessCard.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_FRESHNESS_ROUTER_ONLY_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (INDEX, WORKSPACE, FRESHNESS):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    freshness_src = FRESHNESS.read_text(encoding='utf-8')

    if 'id="routerFreshnessHost"' not in index_src:
        return _fail('routerFreshnessHost missing in Router workspace')

    if 'id="aiHubMarketChip"' not in index_src:
        return _fail('aiHubMarketChip missing in AI Hub')

    if 'ai-hub-market-chip' not in index_src:
        return _fail('AI Hub market chip styles missing')

    if '#aiHubFreshnessHost' not in index_src and 'workspace-aihub .source-freshness-card' not in index_src:
        return _fail('AI Hub freshness block must be hidden or removed')

    if 'patchFreshnessRouterOnly' not in index_src:
        return _fail('patchFreshnessRouterOnly guard missing')

    if 'Intelligence Freshness' not in freshness_src:
        return _fail('SourceFreshnessCard must render Intelligence Freshness')

    if 'Refresh Intelligence' not in freshness_src:
        return _fail('Refresh Intelligence button missing in SourceFreshnessCard')

    if "ws === 'aihub'" in workspace_src and "mount('#aiHubFreshnessHost')" in workspace_src:
        return _fail('WorkspaceManager must not mount freshness on AI Hub')

    if "ws === 'router'" not in workspace_src or "mount('#routerFreshnessHost')" not in workspace_src:
        return _fail('WorkspaceManager must mount freshness on Router')

    if 'Research Mode' not in index_src:
        return _fail('AI Hub chip must mention Research Mode')

    tab_ids = (
        'tab-brain', 'tab-govt', 'tab-scanner', 'tab-markets', 'tab-global',
        'tab-news', 'tab-tv', 'tab-reddit', 'tab-stats', 'tab-history',
    )
    for tab_id in tab_ids:
        start = index_src.find(f'id="{tab_id}"')
        if start < 0:
            continue
        end = index_src.find('</div>', start)
        chunk = index_src[start:end + 6]
        if 'Intelligence Freshness' in chunk or 'routerFreshnessHost' in chunk:
            return _fail(f'freshness block must not appear inside {tab_id}')

    print('FRONTEND_FRESHNESS_ROUTER_ONLY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
