#!/usr/bin/env python3
"""Unit tests for theme dedupe and category output (Stage 47E)."""

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
    print(f'THEME_DEDUPE_CATEGORIES_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.theme_baskets as tb

    finance_expected = [
        'PSU Banks', 'Private Banks', 'NBFC', 'Insurance', 'AMC / Brokers',
    ]
    transport_expected = [
        'Roads / Highways', 'Railways / Metro', 'Aviation', 'Ports / Shipping',
        'Logistics / Warehousing', 'Auto / EV / Batteries',
    ]

    with tempfile.TemporaryDirectory() as tmp:
        tb.BASKETS_FILE = Path(tmp) / 'theme_baskets.json'
        tb.CATALYST_LOG_FILE = Path(tmp) / 'theme_catalyst_log.jsonl'
        tb.bootstrap_theme_baskets(force=True)

        hidden = tb._hidden_from_display_ids()
        if 'ports_logistics' not in hidden:
            return _fail('ports_logistics should be hidden when split baskets exist')
        if 'banking_psu_nbfc' not in hidden:
            return _fail('banking_psu_nbfc should be hidden when finance split exists')

        list_text = tb.format_theme_list_telegram()
        if 'Ports / Logistics' in list_text:
            return _fail('grouped list still shows Ports / Logistics duplicate')
        if 'Banking / PSU / NBFC' in list_text:
            return _fail('grouped list still shows broad Banking / PSU / NBFC basket')
        if 'Ports / Shipping' not in list_text:
            return _fail('grouped list missing Ports / Shipping')
        if 'Logistics / Warehousing' not in list_text:
            return _fail('grouped list missing Logistics / Warehousing')

        defence = tb.get_basket_by_id('defence_aerospace')
        if not defence:
            return _fail('defence_aerospace basket missing')
        if defence.get('category') != 'Government/Budget':
            return _fail('defence_aerospace must be Government/Budget not Market Risk')

        war = tb.get_basket_by_id('war_geopolitics')
        if not war or war.get('category') != 'Market Risk':
            return _fail('war_geopolitics must stay Market Risk')

        if tb.resolve_theme_id('ports') != 'ports_shipping':
            return _fail('ports alias should resolve to ports_shipping')
        if tb.resolve_theme_id('logistics') != 'logistics_warehousing':
            return _fail('logistics alias should resolve to logistics_warehousing')
        if tb.resolve_theme_id('banking') != 'banking_psu_nbfc':
            return _fail('banking alias should still resolve to banking_psu_nbfc')
        if tb.resolve_theme_id('nbfc') != 'nbfc':
            return _fail('nbfc alias should resolve to nbfc basket')

        finance_text = tb.format_theme_category_telegram('finance')
        for name in finance_expected:
            if name not in finance_text:
                return _fail(f'finance category missing {name!r}')
        if 'Banking / PSU / NBFC' in finance_text:
            return _fail('finance category shows hidden broad basket')
        if finance_text.count('•') != len(finance_expected):
            return _fail(f'finance category should have exactly {len(finance_expected)} baskets')

        transport_text = tb.format_theme_category_telegram('transport')
        for name in transport_expected:
            if name not in transport_text:
                return _fail(f'transport category missing {name!r}')
        if 'Ports / Logistics' in transport_text:
            return _fail('transport category shows Ports / Logistics duplicate')
        if transport_text.count('•') != len(transport_expected):
            return _fail(f'transport category should have exactly {len(transport_expected)} baskets')

    print('THEME_DEDUPE_CATEGORIES_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
