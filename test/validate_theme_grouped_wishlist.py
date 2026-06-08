#!/usr/bin/env python3
"""Validate grouped Theme Wishlist list output (Stage 47C)."""

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
    print(f'THEME_GROUPED_WISHLIST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.theme_baskets as tb

    required_categories = list(tb.THEME_CATEGORIES.keys())
    new_baskets = {
        'aviation', 'ports_shipping', 'logistics_warehousing', 'auto_ev_batteries',
        'data_center_ai', 'psu_banks', 'private_banks', 'nbfc', 'insurance', 'amc_brokers',
        'chemicals', 'sugar_ethanol', 'fmcg', 'retail', 'textiles', 'media_entertainment',
        'pharma', 'hospitals', 'diagnostics', 'rbi_rates', 'currency_import_export',
        'crude_sensitive', 'war_geopolitics', 'pli_manufacturing',
    }

    with tempfile.TemporaryDirectory() as tmp:
        tb.BASKETS_FILE = Path(tmp) / 'theme_baskets.json'
        tb.CATALYST_LOG_FILE = Path(tmp) / 'theme_catalyst_log.jsonl'
        tb.bootstrap_theme_baskets(force=True)
        baskets = tb.load_theme_baskets().get('baskets') or []
        ids = {b.get('theme_id') for b in baskets if isinstance(b, dict)}
        if len(baskets) < 40:
            return _fail(f'expected >=40 baskets, got {len(baskets)}')
        missing = new_baskets - ids
        if missing:
            return _fail(f'missing new baskets: {sorted(missing)}')

        list_text = tb.format_theme_list_telegram()
        if tb.WISHLIST_TITLE not in list_text:
            return _fail('list missing Theme Wishlist title')
        if 'AstraEdge Theme Baskets' in list_text:
            return _fail('list still uses old Theme Baskets title')
        for category in required_categories:
            if category not in list_text:
                return _fail(f'list missing category: {category}')

        overview = tb.format_theme_overview_telegram()
        for cmd in ('list', 'search', 'category', 'news', 'scan', 'refresh'):
            if cmd not in overview.lower():
                return _fail(f'overview missing command hint: {cmd}')

    print('THEME_GROUPED_WISHLIST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
