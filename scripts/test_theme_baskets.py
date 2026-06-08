#!/usr/bin/env python3
"""Unit tests for theme baskets bootstrap (Stage 47A)."""

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
    print(f'THEME_BASKETS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.theme_baskets as tb

    with tempfile.TemporaryDirectory() as tmp:
        baskets_path = Path(tmp) / 'theme_baskets.json'
        log_path = Path(tmp) / 'theme_catalyst_log.jsonl'
        orig_baskets = tb.BASKETS_FILE
        orig_log = tb.CATALYST_LOG_FILE
        tb.BASKETS_FILE = baskets_path
        tb.CATALYST_LOG_FILE = log_path
        try:
            data = tb.bootstrap_theme_baskets(force=True)
            baskets = data.get('baskets') or []
            if len(baskets) < 40:
                return _fail(f'expected >=40 baskets, got {len(baskets)}')

            ids = {b.get('theme_id') for b in baskets}
            required = {
                'infrastructure',
                'roads_highways',
                'railways_metro',
                'defence_aerospace',
                'renewable_energy',
                'power_grid_transmission',
                'housing_real_estate',
                'cement_steel_paint',
                'ports_logistics',
                'agriculture_fertilizer',
                'semiconductors_electronics',
                'tourism_temple_culture',
                'banking_psu_nbfc',
                'it_digital_india',
                'oil_gas_energy',
                'metals_mining',
                'telecom_5g',
                'water_jal_jeevan',
                'aviation',
                'pharma',
                'hospitals',
            }
            missing = required - ids
            if missing:
                return _fail(f'missing theme ids: {sorted(missing)}')

            infra = tb.get_basket_by_id('infra')
            if not infra or infra.get('theme_id') != 'infrastructure':
                return _fail('infra alias should resolve to infrastructure basket')

            roads = tb.get_basket_by_id('roads')
            if not roads or roads.get('display_name') != 'Roads / Highways':
                return _fail('roads/highways basket missing')

            if not baskets_path.is_file():
                return _fail('theme_baskets.json not written')

            loaded = json.loads(baskets_path.read_text(encoding='utf-8'))
            sample = loaded['baskets'][0]
            for field in (
                'theme_id', 'display_name', 'category', 'aliases', 'keywords', 'trigger_keywords',
                'direct_beneficiary_sectors', 'indirect_beneficiary_sectors',
                'raw_material_beneficiaries', 'risk_sectors', 'stocks',
                'confirmation_rules', 'stale_after_hours',
            ):
                if field not in sample:
                    return _fail(f'missing basket field: {field}')
            stocks = sample.get('stocks') or {}
            for bucket in ('direct', 'indirect', 'raw_material', 'avoid_or_risk'):
                if bucket not in stocks:
                    return _fail(f'missing stocks bucket: {bucket}')
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log

    print('THEME_BASKETS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
