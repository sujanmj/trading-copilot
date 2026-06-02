#!/usr/bin/env python3
"""
Validate Stage 43 AI Hub / Broker scroll layout in frontend.

Checks:
  - scrollable AI Hub container (ai-hub-scroll)
  - scrollable Broker workspace panel
  - bottom padding so chat bar does not hide content
  - main scroll areas use overflow-y:auto (not overflow:hidden traps)

Prints exactly FRONTEND_SCROLL_LAYOUT_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_SCROLL_LAYOUT_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def _block(css: str, selector: str) -> str | None:
    pattern = re.escape(selector) + r'\s*\{([^}]*)\}'
    match = re.search(pattern, css, re.DOTALL)
    return match.group(1) if match else None


def main() -> int:
    if not INDEX.is_file():
        return _fail(f'missing {INDEX.relative_to(PROJECT_ROOT)}')

    src = _read(INDEX)

    if 'ai-hub-scroll' not in src or 'id="aiHubScroll"' not in src:
        return _fail('index.html missing ai-hub-scroll container (#aiHubScroll)')

    hub_block = _block(src, '.ai-hub-scroll')
    if not hub_block:
        return _fail('.ai-hub-scroll CSS block missing')
    if 'overflow-y' not in hub_block or 'auto' not in hub_block:
        return _fail('.ai-hub-scroll must use overflow-y: auto')
    if hub_block.count('overflow:hidden') or hub_block.count('overflow: hidden'):
        return _fail('.ai-hub-scroll must not use overflow:hidden')

    if not re.search(r'padding-bottom\s*:\s*var\(--ai-chat-pad', hub_block):
        if not re.search(r'padding-bottom\s*:\s*\d+px', hub_block):
            return _fail('.ai-hub-scroll needs bottom padding for chat bar clearance')

    if '--ai-chat-pad' not in src and 'padding-bottom' not in hub_block:
        return _fail('missing chat overlap padding marker (--ai-chat-pad or padding-bottom)')

    broker_block = _block(src, '.brokers-main-panel')
    if not broker_block:
        return _fail('.brokers-main-panel CSS block missing')
    if 'overflow-y' not in broker_block or 'auto' not in broker_block:
        return _fail('.brokers-main-panel must scroll vertically (overflow-y: auto)')

    if 'workspace-brokers' not in src or 'brokersMainPanel' not in src:
        return _fail('index.html missing broker workspace containers')

    hub_scroll_html = re.search(
        r'<div class="ai-hub-scroll"[^>]*>.*?</div>\s*<div class="ask-bar">',
        src,
        re.DOTALL,
    )
    if not hub_scroll_html:
        return _fail('ask-bar must follow ai-hub-scroll (chat bar outside scroll trap)')

    if 'aiHubRouterStatusHost' not in src:
        return _fail('aiHubRouterStatusHost missing from AI Hub layout')

    inside_scroll = re.search(
        r'<div class="ai-hub-scroll"[^>]*>[\s\S]*aiHubRouterStatusHost',
        src,
    )
    if not inside_scroll:
        return _fail('aiHubRouterStatusHost should live inside ai-hub-scroll for unified scrolling')

    nested_scroll = _block(src, '.ai-hub-scroll .tab-content')
    if nested_scroll and re.search(r'overflow-y\s*:\s*auto', nested_scroll):
        return _fail('.ai-hub-scroll .tab-content must not nest a second scroll trap')

    print('FRONTEND_SCROLL_LAYOUT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
