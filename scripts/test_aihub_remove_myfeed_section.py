#!/usr/bin/env python3
"""Stage 50H — My Feed removed from AI Hub (standalone tab kept)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'AIHUB_REMOVE_MYFEED_SECTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    lazy = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    fmt = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')

    hub = index[index.find('AI Intelligence Hub'):index.find('ask-bar')]
    if re.search(r'data-tab=["\']myfeed["\']', hub):
        return _fail('AI Hub tabs must not include myfeed')
    if 'id="tab-myfeed"' in hub:
        return _fail('AI Hub must not include tab-myfeed panel')

    if 'myFeedMainPanel' not in index or 'myFeedNavBtn' not in index:
        return _fail('standalone My Feed workspace must remain')

    if "payloads['myfeed']" in lazy:
        return _fail('lazy_command_runner must not load myfeed into aihub full payloads')

    if '<b>🗞 My Feed</b>' in fmt:
        return _fail('format_aihub_full must not include My Feed section')

    from backend.telegram.response_format import AIHUB_FULL_TABS

    if 'myfeed' in AIHUB_FULL_TABS:
        return _fail('AIHUB_FULL_TABS must not include myfeed')

    print('AIHUB_REMOVE_MYFEED_SECTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
