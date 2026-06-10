#!/usr/bin/env python3
"""Unit tests — GUI My Feed contract (Stage 50A hotfix)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_GUI_CONTRACT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    for needle in (
        '/api/myfeed?limit=40',
        "'/api/myfeed'",
        'source: \'gui_text\'',
        'No My Feed items yet. Add news from Telegram or GUI.',
        'cleaned_summary',
        'impact_score',
        'suggested_action',
        'detected_source_app',
    ):
        if needle not in html:
            return _fail(f'frontend/index.html missing {needle!r}')

    routes = (PROJECT_ROOT / 'backend/api/myfeed_routes.py').read_text(encoding='utf-8')
    if "'ok': True" not in routes or "'items':" not in routes:
        return _fail('backend must return ok/items JSON contract')

    print('MYFEED_GUI_CONTRACT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
