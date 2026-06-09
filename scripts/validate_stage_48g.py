#!/usr/bin/env python3
"""Run Stage 48G validators."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)

VALIDATORS = [
    'validate_budget_theme_click_drilldown.py',
    'validate_budget_catalyst_drilldown.py',
    'validate_budget_theme_specific_scan.py',
    'validate_budget_cache_indexes.py',
    'validate_budget_frontend_interactions.py',
    'validate_budget_api_routes.py',
    'validate_budget_safety_language.py',
    'validate_budget_catalyst_direction.py',
    'validate_budget_named_company_extraction.py',
    'validate_budget_dedupe_catalysts.py',
    'validate_budget_stock_ranking_sections.py',
    'validate_budget_freshness_panel.py',
    'validate_budget_news_analyzer.py',
    'validate_header_exact_order.py',
    'validate_broker_cache_first_load.py',
    'validate_broker_api_lite_routes.py',
    'validate_broker_fetch_abort_handling.py',
    'validate_frontend_boot_no_heavy_refresh.py',
    'validate_frontend_api_json_guard.py',
    'validate_budget_lite_cache_endpoint.py',
    'validate_budget_cache_first_load.py',
    'validate_budget_fetch_abort_handling.py',
    'validate_aihub_refresh_route_compat.py',
]


def main() -> int:
    for rel, needle in (
        ('backend/config/local_safe_mode.py', 'AstraEdge 49C'),
        ('backend/api/api_server.py', "'stage': '49C'"),
        ('backend/analytics/budget_impact.py', "STAGE = '48U'"),
        ('backend/analytics/broker_intelligence.py', "STAGE = '48U'"),
    ):
        if needle not in (PROJECT_ROOT / rel).read_text(encoding='utf-8'):
            print(f'STAGE_48G_FAIL: {rel} missing build', file=sys.stderr)
            return 1
    failed = []
    for name in VALIDATORS:
        print(f'--- {name} ---')
        if os.system(f'{sys.executable} scripts/{name}') != 0:
            failed.append(name)
    if failed:
        print(f'STAGE_48G_FAIL: {", ".join(failed)}', file=sys.stderr)
        return 1
    print('STAGE_48G_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
