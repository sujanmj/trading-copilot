#!/usr/bin/env python3
"""Run Stage 48D validators."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)

VALIDATORS = [
    'validate_header_final_order.py',
    'validate_aihub_refresh_route_compat.py',
    'validate_budget_lite_cache_endpoint.py',
    'validate_budget_cache_first_load.py',
    'validate_frontend_boot_no_heavy_refresh.py',
    'validate_budget_fetch_abort_handling.py',
    'validate_frontend_api_json_guard.py',
]


def main() -> int:
    for rel, needle in (
        ('backend/config/local_safe_mode.py', 'AstraEdge 48D'),
        ('backend/api/api_server.py', "'stage': '48D'"),
        ('backend/analytics/budget_impact.py', "STAGE = '48D'"),
    ):
        if needle not in (PROJECT_ROOT / rel).read_text(encoding='utf-8'):
            print(f'STAGE_48D_FAIL: {rel} missing build', file=sys.stderr)
            return 1
    failed = []
    for name in VALIDATORS:
        print(f'--- {name} ---')
        if os.system(f'{sys.executable} scripts/{name}') != 0:
            failed.append(name)
    if failed:
        print(f'STAGE_48D_FAIL: {", ".join(failed)}', file=sys.stderr)
        return 1
    print('STAGE_48D_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
