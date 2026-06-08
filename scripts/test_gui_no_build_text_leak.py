#!/usr/bin/env python3
"""Unit tests ensuring GUI build strings are not visible in app UI (Stage 48I)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'GUI_NO_BUILD_TEXT_LEAK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _strip_html_comments(src: str) -> str:
    return re.sub(r'<!--[\s\S]*?-->', '', src)


def _strip_script_blocks(src: str) -> str:
    return re.sub(r'<script[\s\S]*?</script>', '', src, flags=re.I)


def main() -> int:
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')

    if 'display: none !important' not in index_html or '.gui-build-marker' not in index_html:
        return _fail('gui-build-marker must be hidden via CSS')

    marker_match = re.search(r'id="guiBuildMarker"[^>]*>([^<]*)</div>', index_html)
    if marker_match and marker_match.group(1).strip():
        return _fail('guiBuildMarker div must not contain visible build text')

    visible_html = _strip_script_blocks(_strip_html_comments(index_html))
    for token in ('GUI_BUILD_STAGE_', 'RESTORE_RICH_MEMORY_UI'):
        if token in visible_html:
            return _fail(f'visible index.html body must not contain {token!r} outside comments/scripts')

    if 'GUI_BUILD_STAGE' in panel_js or 'RESTORE_RICH_MEMORY_UI' in panel_js:
        return _fail('BudgetImpactPanel.js must not render internal build strings')

    budget_panel = visible_html.split('id="budgetMainPanel"')[1].split('id="brokersMainPanel"')[0]
    for token in ('GUI_BUILD_STAGE', 'RESTORE_RICH_MEMORY_UI', 'GUI_BUILD_STAGE_44'):
        if token in budget_panel:
            return _fail(f'budget workspace must not leak build text: {token!r}')

    print('GUI_NO_BUILD_TEXT_LEAK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
