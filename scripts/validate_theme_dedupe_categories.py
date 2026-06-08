#!/usr/bin/env python3
"""Validate theme dedupe and category output (Stage 47E)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'THEME_DEDUPE_CATEGORIES_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/theme_baskets.py').read_text(encoding='utf-8')
    for needle in (
        "STAGE = '47E'",
        'HIDDEN_WHEN_SPLIT',
        "'defence_aerospace'",
        "'ports_shipping'",
        "'logistics_warehousing'",
        "category='Government/Budget'",
        "'ports': 'ports_shipping'",
        "'logistics': 'logistics_warehousing'",
    ):
        if needle not in src:
            return _fail(f'theme_baskets.py missing {needle!r}')

    if os.system(f'{sys.executable} scripts/test_theme_dedupe_categories.py') != 0:
        return _fail('test_theme_dedupe_categories.py failed')
    print('THEME_DEDUPE_CATEGORIES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
