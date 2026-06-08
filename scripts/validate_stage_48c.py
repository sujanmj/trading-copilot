#!/usr/bin/env python3
"""Run all Stage 48C validators (includes 48B regression pack)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

VALIDATORS_48C = [
    'validate_header_control_row_layout.py',
    'validate_runtime_snapshot_lite.py',
    'validate_aihub_cache_first_tabs.py',
    'validate_budget_cache_first_load.py',
    'validate_frontend_boot_no_heavy_refresh.py',
]

VALIDATORS_48B = [
    'validate_header_ai_nav_layout.py',
    'validate_budget_fetch_abort_handling.py',
    'validate_budget_impact_engine.py',
    'validate_budget_api_routes.py',
    'validate_budget_frontend_tab.py',
    'validate_budget_news_analyzer.py',
    'validate_budget_safety_language.py',
    'validate_frontend_api_json_guard.py',
]


def _check_build_stage() -> list[str]:
    failed = []
    for rel, needle in (
        ('backend/config/local_safe_mode.py', 'AstraEdge 48C'),
        ('backend/telegram/telegram_analysis_bot.py', 'AstraEdge 48C'),
        ('backend/telegram/response_format.py', 'AstraEdge 48C'),
        ('backend/api/api_server.py', "'stage': '48C'"),
        ('backend/analytics/budget_impact.py', "STAGE = '48C'"),
        ('backend/analytics/premarket_conviction.py', "'stage': '48C'"),
    ):
        path = PROJECT_ROOT / rel
        if needle not in path.read_text(encoding='utf-8'):
            failed.append(f'{rel} missing {needle}')
    return failed


def main() -> int:
    build_fail = _check_build_stage()
    if build_fail:
        for item in build_fail:
            print(f'STAGE_48C_FAIL: {item}', file=sys.stderr)
        return 1

    failed = []
    for name in VALIDATORS_48C + VALIDATORS_48B:
        print(f'--- {name} ---')
        if os.system(f'{sys.executable} scripts/{name}') != 0:
            failed.append(name)

    if failed:
        print(f'STAGE_48C_FAIL: {", ".join(failed)}', file=sys.stderr)
        return 1
    print('STAGE_48C_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
