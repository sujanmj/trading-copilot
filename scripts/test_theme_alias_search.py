#!/usr/bin/env python3
"""Unit tests for Theme Wishlist aliases, search, and category commands (Stage 47C)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'THEME_ALIAS_SEARCH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.theme_baskets as tb

    alias_checks = {
        'infra': 'infrastructure',
        'infrastructure': 'infrastructure',
        'road': 'roads_highways',
        'roads': 'roads_highways',
        'railway': 'railways_metro',
        'railways': 'railways_metro',
        'defence': 'defence_aerospace',
        'defense': 'defence_aerospace',
        'telecom': 'telecom_5g',
        '5g': 'telecom_5g',
    }

    with tempfile.TemporaryDirectory() as tmp:
        tb.BASKETS_FILE = Path(tmp) / 'theme_baskets.json'
        tb.CATALYST_LOG_FILE = Path(tmp) / 'theme_catalyst_log.jsonl'
        tb.bootstrap_theme_baskets(force=True)

        for alias, expected in alias_checks.items():
            resolved = tb.resolve_theme_id(alias)
            if resolved != expected:
                return _fail(f'alias {alias!r} -> {resolved!r}, expected {expected!r}')

        transport = tb.resolve_theme_id('transport')
        if not str(transport).startswith('__category__:'):
            return _fail('transport should resolve to transport/logistics category')
        transport_text = tb.handle_theme_command('transport')
        if 'Transport/Logistics' not in transport_text:
            return _fail('/theme transport should show Transport/Logistics category')

        for keyword in ('telecom', 'transport', 'bank', 'hospital'):
            rows = tb.search_theme_baskets(keyword)
            if not rows:
                return _fail(f'search {keyword!r} returned no baskets')
            search_text = tb.handle_theme_command(f'search {keyword}')
            if keyword.lower() not in search_text.lower() and 'Search' not in search_text:
                return _fail(f'search command failed for {keyword!r}')

        for cat in ('transport', 'finance', 'healthcare'):
            cat_text = tb.handle_theme_command(f'category {cat}')
            if 'Unknown category' in cat_text:
                return _fail(f'category {cat!r} not recognized')

    print('THEME_ALIAS_SEARCH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
