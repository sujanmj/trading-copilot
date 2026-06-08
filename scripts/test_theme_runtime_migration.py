#!/usr/bin/env python3
"""Unit tests for runtime theme schema migration (Stage 47F)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'THEME_RUNTIME_MIGRATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.theme_baskets as tb

    legacy_payload = {
        'stage': '47A',
        'theme_schema_version': '47A',
        'generated_at': '2026-06-01T08:00:00+05:30',
        'baskets': [
            {
                'theme_id': 'ports_logistics',
                'display_name': 'Ports / Logistics',
                'category': 'Transport/Logistics',
                'stocks': {'direct': ['ADANIPORTS'], 'indirect': [], 'raw_material': []},
            },
            {
                'theme_id': 'banking_psu_nbfc',
                'display_name': 'Banking / PSU / NBFC',
                'category': 'Finance',
                'stocks': {'direct': ['SBIN'], 'indirect': [], 'raw_material': []},
            },
            {
                'theme_id': 'defence',
                'display_name': 'Defence',
                'category': 'Market Risk',
                'stocks': {'direct': ['HAL'], 'indirect': [], 'raw_material': []},
            },
            {
                'theme_id': 'defence_aerospace',
                'display_name': 'Defence / Aerospace',
                'category': 'Market Risk',
                'stocks': {'direct': ['BEL'], 'indirect': [], 'raw_material': []},
            },
        ],
        'catalyst_cache': {'ports_logistics': [{'headline': 'old port news', 'catalyst_score': 40}]},
    }

    with tempfile.TemporaryDirectory() as tmp:
        tb.BASKETS_FILE = Path(tmp) / 'theme_baskets.json'
        tb.CATALYST_LOG_FILE = Path(tmp) / 'theme_catalyst_log.jsonl'
        tb.BASKETS_FILE.write_text(json.dumps(legacy_payload), encoding='utf-8')

        data = tb.bootstrap_theme_baskets()
        if data.get('theme_schema_version') != '47F':
            return _fail(f'expected theme_schema_version 47F, got {data.get("theme_schema_version")!r}')

        ids = {str(b.get('theme_id')) for b in data.get('baskets') or [] if isinstance(b, dict)}
        if 'ports_logistics' in ids:
            return _fail('ports_logistics should be removed after migration')
        if 'banking_psu_nbfc' in ids:
            return _fail('banking_psu_nbfc should be removed after migration')
        if 'defence' in ids:
            return _fail('old defence duplicate should be removed after migration')
        if 'ports_shipping' not in ids or 'logistics_warehousing' not in ids:
            return _fail('canonical transport baskets missing after migration')

        defence = tb.get_basket_by_id('defence_aerospace')
        if not defence or defence.get('category') != 'Government/Budget':
            return _fail('defence_aerospace must be Government/Budget')
        war = tb.get_basket_by_id('war_geopolitics')
        if not war or war.get('category') != 'Market Risk':
            return _fail('war_geopolitics must remain Market Risk')

        list_text = tb.format_theme_list_telegram()
        if 'Ports / Logistics' in list_text:
            return _fail('/theme list still shows Ports / Logistics duplicate')
        if 'Defence / Aerospace' not in list_text:
            return _fail('/theme list missing Defence / Aerospace')

        transport_search = tb.format_theme_search_telegram('transport')
        if 'Ports / Logistics' in transport_search:
            return _fail('/theme search transport shows Ports / Logistics duplicate')

        refresh = tb.refresh_theme_catalyst_cache(persist=True)
        if not refresh.get('ok'):
            return _fail('theme refresh failed')
        reloaded = json.loads(tb.BASKETS_FILE.read_text(encoding='utf-8'))
        if reloaded.get('theme_schema_version') != '47F':
            return _fail('refresh did not persist theme_schema_version 47F')

    print('THEME_RUNTIME_MIGRATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
