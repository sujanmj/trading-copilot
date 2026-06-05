#!/usr/bin/env python3
"""Run all Stage 47A validators (includes 46J regression pack)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

VALIDATORS_47A = [
    'validate_theme_baskets.py',
    'validate_theme_catalyst_matching.py',
    'validate_theme_telegram_commands.py',
    'validate_theme_api_routes.py',
]

VALIDATORS_46J = [
    'validate_weekend_research_mode.py',
    'validate_memory_outcome_clarity.py',
]

VALIDATORS_46I = [
    'validate_india_market_mode.py',
    'validate_premarket_freshness_quality.py',
    'validate_eod_alert_event_tracking.py',
    'validate_emergency_macro_severity.py',
]

VALIDATORS_46H = [
    'validate_ai_provider_fallback.py',
    'validate_alert_freshness_gate.py',
    'validate_watchdog_throttle.py',
    'validate_alert_quality_filters.py',
    'validate_premarket_alerts.py',
    'validate_eod_outcome_scoring.py',
    'validate_telegram_refresh_commands.py',
]


def main() -> int:
    failed = []
    for name in VALIDATORS_47A + VALIDATORS_46J + VALIDATORS_46I + VALIDATORS_46H:
        path = PROJECT_ROOT / 'scripts' / name
        if not path.is_file():
            failed.append(f'missing {name}')
            continue
        print(f'--- {name} ---')
        if os.system(f'{sys.executable} scripts/{name}') != 0:
            failed.append(name)
    if failed:
        print(f'STAGE_47A_FAIL: {", ".join(failed)}', file=sys.stderr)
        return 1
    print('STAGE_47A_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
