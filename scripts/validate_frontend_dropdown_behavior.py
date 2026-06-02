#!/usr/bin/env python3
"""
Validate Stage 44J BROKERS + NEWS dropdown behavior.

Prints exactly FRONTEND_DROPDOWN_BEHAVIOR_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'
DROPDOWN = PROJECT_ROOT / 'frontend' / 'components' / 'DropdownMenu.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_DROPDOWN_BEHAVIOR_FAIL: {msg}', file=sys.stderr)
    return 1


def _panel_css_block(src: str) -> str:
    match = re.search(
        r'\.brokers-menu-panel,\s*\.news-menu-panel\s*\{([^}]+)\}',
        src,
        re.DOTALL,
    )
    return match.group(1) if match else ''


def main() -> int:
    for path in (INDEX, WORKSPACE, DROPDOWN):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    dropdown_src = DROPDOWN.read_text(encoding='utf-8')

    if '<details class="brokers-menu"' not in index_src:
        return _fail('BROKERS dropdown missing')
    if '<details class="news-menu"' not in index_src:
        return _fail('NEWS dropdown missing')

    panel_css = _panel_css_block(index_src)
    if not panel_css:
        return _fail('brokers-menu-panel / news-menu-panel CSS block missing')
    if 'position:absolute' not in panel_css.replace(' ', ''):
        return _fail('dropdown panel must use position:absolute (floating below trigger)')

    base_panel_css = panel_css.split('@media', 1)[0]
    if re.search(r'overflow-y\s*:\s*auto', base_panel_css):
        return _fail('dropdown panel must not force overflow-y:auto on desktop')
    for decl in re.findall(r'max-height\s*:\s*([^;]+)', base_panel_css):
        val = decl.strip().lower()
        if val and val != 'none':
            return _fail('dropdown panel must not trap height with max-height on desktop')

    if 'DropdownMenu.js' not in index_src:
        return _fail('index.html must load DropdownMenu.js')

    if 'Escape' not in dropdown_src or 'keydown' not in dropdown_src:
        return _fail('DropdownMenu must close on Escape')
    if 'document.addEventListener(\'click\'' not in dropdown_src and 'document.addEventListener("click"' not in dropdown_src:
        return _fail('DropdownMenu must close on click outside')
    if 'closeAll' not in dropdown_src:
        return _fail('DropdownMenu must expose closeAll')

    if 'function openSourceFeed' not in workspace_src:
        return _fail('WorkspaceManager must define openSourceFeed')
    if 'openSourceFeed(' not in workspace_src:
        return _fail('dropdown item clicks must call openSourceFeed')
    if 'DropdownMenu.closeAll' not in workspace_src and 'menu.open = false' not in workspace_src:
        return _fail('item click must close dropdown')
    if 'stopPropagation' not in workspace_src:
        return _fail('dropdown item clicks must stop propagation')

    wire_match = re.search(r'function wireNavButtons\([\s\S]*?\n  \}', workspace_src)
    if not wire_match:
        return _fail('wireNavButtons missing')
    wire_src = wire_match.group(0)
    if 'openBrowser(' in wire_src and 'openSourceFeed(' not in wire_src:
        return _fail('wireNavButtons must use openSourceFeed for dropdown items')

    if 'DropdownMenu.init' not in workspace_src:
        return _fail('WorkspaceManager.init must wire DropdownMenu')

    print('FRONTEND_DROPDOWN_BEHAVIOR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
