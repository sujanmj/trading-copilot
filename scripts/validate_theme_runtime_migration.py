#!/usr/bin/env python3
"""Validate runtime theme schema migration (Stage 47F)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'THEME_RUNTIME_MIGRATION_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/theme_baskets.py').read_text(encoding='utf-8')
    for needle in (
        "STAGE = '47F'",
        'THEME_SCHEMA_VERSION',
        'THEME_SCHEMA_MIGRATION_APPLIED',
        'DEPRECATED_THEME_IDS',
        "'defence_aerospace'",
        "'ports_shipping'",
        "'logistics_warehousing'",
    ):
        if needle not in src:
            return _fail(f'theme_baskets.py missing {needle!r}')

    if os.system(f'{sys.executable} scripts/test_theme_runtime_migration.py') != 0:
        return _fail('test_theme_runtime_migration.py failed')
    print('THEME_RUNTIME_MIGRATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
