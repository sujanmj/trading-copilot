#!/usr/bin/env python3
"""
Validate Stage 20D AI Hub cleanup (final).

Checks:
  - No per-tab refresh icons in AI Hub
  - Single top-right Refresh button with "Refresh active tab"
  - No Mem tab in AI Hub
  - No duplicate hardcoded live-collectors banner in Brain render path

Prints exactly FRONTEND_AIHUB_CLEANUP_FINAL_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_AIHUB_CLEANUP_FINAL_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not INDEX.is_file():
        return _fail(f'missing {INDEX.relative_to(PROJECT_ROOT)}')

    src = INDEX.read_text(encoding='utf-8')

    if 'tab-refresh-btn' in src:
        return _fail('per-tab tab-refresh-btn must be removed from AI Hub')

    if 'id="refreshBtn"' not in src:
        return _fail('main refreshBtn missing')

    if 'title="Refresh active tab"' not in src:
        return _fail('refreshBtn must have title="Refresh active tab"')

    if 'getActiveTabPanelId' not in src or 'refreshTabByPanel' not in src:
        return _fail('active-tab refresh wiring missing')

    if re.search(r'data-tab=["\']memory["\']', src) or 'id="tab-memory"' in src:
        return _fail('AI Hub must not include Mem tab')

    brain_block = ''
    m = re.search(r'function loadBrain\(\)\s*\{', src)
    if m:
        start = m.start()
        end = src.find('function loadGovt()', start)
        if end < 0:
            end = start + 8000
        brain_block = src[start:end]

    if brain_block.count('${brainBanner}') > 0:
        return _fail('Brain tab must not embed brainBanner twice in body html')

    live_in_brain = brain_block.count('live collectors active')
    if live_in_brain >= 2:
        return _fail('Brain render must not hardcode duplicate live collectors banner')

    if 'dedupePanelBanners' not in src:
        return _fail('dedupePanelBanners helper missing')

    print('FRONTEND_AIHUB_CLEANUP_FINAL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
