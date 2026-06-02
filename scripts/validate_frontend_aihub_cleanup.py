#!/usr/bin/env python3
"""
Validate Stage 19B AI Hub cleanup + runtime hydration wiring.

Checks:
  - No Source Freshness mount/host in AI Hub workspace
  - Memory workspace includes Source Freshness
  - RuntimeManager live API first with _ts cache bust
  - Stale localStorage cache not preferred before live API
  - Refresh Runtime button present

Prints exactly FRONTEND_AIHUB_CLEANUP_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
INDEX = FRONTEND / 'index.html'
RUNTIME = FRONTEND / 'runtime' / 'runtimeManager.js'
WORKSPACE = FRONTEND / 'components' / 'WorkspaceManager.js'
MEMORY = FRONTEND / 'components' / 'MarketMemoryPanel.js'
FRESHNESS = FRONTEND / 'components' / 'SourceFreshnessCard.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_AIHUB_CLEANUP_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (INDEX, RUNTIME, WORKSPACE, MEMORY, FRESHNESS):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    runtime_src = _read(RUNTIME)
    workspace_src = _read(WORKSPACE)
    memory_src = _read(MEMORY)
    freshness_src = _read(FRESHNESS)

    if 'sourceFreshnessCardHost' in index_src:
        return _fail('index.html must not define sourceFreshnessCardHost in AI Hub')

    if re.search(r'mountSourceFreshnessInAiHub', index_src):
        return _fail('index.html must not mount Source Freshness in AI Hub')

    if re.search(r"ws\s*===\s*['\"]aihub['\"][\s\S]{0,200}SourceFreshnessCard\.mount", workspace_src):
        return _fail('WorkspaceManager must not mount SourceFreshness in aihub workspace')

    if 'includeFreshness: true' not in memory_src:
        return _fail('MarketMemoryPanel must include Source Freshness in Memory main view')

    if 'SourceFreshnessCard.renderCardHtml' not in memory_src:
        return _fail('MarketMemoryPanel must render SourceFreshnessCard in Memory')

    if 'Refresh Runtime' not in freshness_src:
        return _fail('SourceFreshnessCard missing Refresh Runtime button')

    if '/api/runtime/snapshot' not in runtime_src:
        return _fail('runtimeManager must use /api/runtime/snapshot endpoint')

    if '_ts=' not in runtime_src:
        return _fail('runtimeManager must cache-bust snapshot fetch with _ts')

    if re.search(r'loadSnapshotCache\(\)[\s\S]{0,400}refresh\(', runtime_src):
        return _fail('runtimeManager must not hydrate from stale cache before live API refresh')

    if 'boot hydrated from stale cache' in runtime_src:
        return _fail('runtimeManager must not boot from stale cache before API')

    if 'clearStaleCache' not in runtime_src:
        return _fail('runtimeManager must expose clearStaleCache for refresh flow')

    if 'clearStaleCache' not in freshness_src and 'trading_copilot_runtime_snapshot_v1' not in freshness_src:
        return _fail('SourceFreshnessCard must clear runtime stale cache on runtime refresh')

    if re.search(r'data-tab=["\']memory["\']', index_src) or 'id="tab-memory"' in index_src:
        return _fail('AI Hub must not include Mem tab')

    if 'tab-refresh-btn' not in index_src or 'refreshTabByPanel' not in index_src:
        return _fail('AI Hub must include per-tab refresh buttons')

    print('FRONTEND_AIHUB_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
