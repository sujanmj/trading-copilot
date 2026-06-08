#!/usr/bin/env python3
"""Validate /status freshness detail lines (Stage 47E)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'STATUS_FRESHNESS_DETAILS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    for needle in (
        'AstraEdge 48A',
        '_format_feed_freshness_line',
        'Latest scanner:',
        'Latest news:',
        'Latest theme cache:',
        'Market mode:',
    ):
        if needle not in src:
            return _fail(f'response_format.py missing {needle!r}')

    if os.system(f'{sys.executable} scripts/test_status_freshness_details.py') != 0:
        return _fail('test_status_freshness_details.py failed')
    print('STATUS_FRESHNESS_DETAILS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
