#!/usr/bin/env python3
"""
Validate Stage 19 full-screen workspace layout in frontend.

Checks:
  - activeWorkspace / data-workspace routing
  - AI Hub not permanently split beside every page
  - Memory workspace container
  - Full-width broker/news workspace + browser toolbar
  - Per-section refresh button labels in SourceFreshnessCard

Prints exactly FRONTEND_WORKSPACE_LAYOUT_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'
FRESHNESS = PROJECT_ROOT / 'frontend' / 'components' / 'SourceFreshnessCard.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_WORKSPACE_LAYOUT_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (INDEX, WORKSPACE, FRESHNESS):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = _read(INDEX)
    workspace_src = _read(WORKSPACE)
    freshness_src = _read(FRESHNESS)

    if 'activeWorkspace' not in workspace_src and 'activeWorkspace' not in index_src:
        return _fail('WorkspaceManager must expose activeWorkspace state')

    if 'data-workspace' not in index_src:
        return _fail('index.html main workspace must use data-workspace attribute')

    if 'aiHubNavBtn' not in index_src:
        return _fail('index.html missing AI Hub top nav button (aiHubNavBtn)')

    if 'WorkspaceManager' not in index_src:
        return _fail('index.html must load WorkspaceManager.js')

    split_ai = re.search(r'\.ai-panel\s*\{[^}]*flex:\s*0\s*0\s*40%', index_src, re.IGNORECASE)
    if split_ai:
        return _fail('AI Hub must not use permanent 40% split layout')

    if 'workspace-aihub' not in index_src or 'workspace-browser' not in index_src:
        return _fail('index.html missing workspace-aihub / workspace-browser panels')

    if 'memoryMainPanel' not in index_src or 'memoryMainContent' not in index_src:
        return _fail('index.html missing Memory workspace containers')

    if 'browser-toolbar' not in index_src or 'browserSourceLabel' not in index_src:
        return _fail('index.html missing full-width browser toolbar')

    if 'Open External' not in index_src:
        return _fail('index.html browser toolbar missing Open External action')

    for label in ('Refresh Runtime', 'Refresh News', 'Refresh Prices', 'Refresh Memory', 'Refresh All'):
        if label not in freshness_src:
            return _fail(f'SourceFreshnessCard.js missing button label: {label!r}')

    if 'scope' not in freshness_src or 'refresh-local-intelligence' not in freshness_src:
        return _fail('SourceFreshnessCard.js must POST scoped refresh-local-intelligence')

    unconditional_mount = re.findall(r'SourceFreshnessCard\.mount\s*\(', index_src)
    if len(unconditional_mount) > 1:
        return _fail('SourceFreshnessCard.mount must not be called unconditionally multiple times')

    print('FRONTEND_WORKSPACE_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
