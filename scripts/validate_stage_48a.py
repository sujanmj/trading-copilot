#!/usr/bin/env python3
"""Run all Stage 48A validators (includes 47F regression pack)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

VALIDATORS_48A = [
    'validate_budget_impact_engine.py',
    'validate_budget_api_routes.py',
    'validate_budget_frontend_tab.py',
    'validate_budget_news_analyzer.py',
    'validate_budget_safety_language.py',
]

VALIDATORS_47F = [
    'validate_theme_runtime_migration.py',
    'validate_live_watch_consistency.py',
    'validate_status_freshness_cleanup.py',
    'validate_macro_stale_dedupe.py',
    'validate_frontend_api_json_guard.py',
]

VALIDATORS_47E = [
    'validate_theme_dedupe_categories.py',
    'validate_market_hours_premarket_routing.py',
    'validate_status_freshness_details.py',
]

VALIDATORS_47D = [
    'validate_premarket_hard_stale_lock.py',
    'validate_scanner_session_date_guard.py',
    'validate_riskoff_macro_override.py',
]

VALIDATORS_47C = [
    'validate_theme_grouped_wishlist.py',
    'validate_theme_alias_search.py',
    'validate_weekend_scheduler_quiet.py',
]

VALIDATORS_47B = [
    'validate_theme_relevance_filter.py',
    'validate_railway_smoke_stage_compare.py',
]

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


def _check_build_stage() -> list[str]:
    failed = []
    for rel, needle in (
        ('backend/config/local_safe_mode.py', 'AstraEdge 48A'),
        ('backend/telegram/telegram_analysis_bot.py', 'AstraEdge 48A'),
        ('backend/telegram/response_format.py', 'AstraEdge 48A'),
        ('backend/api/api_server.py', "'stage': '48A'"),
        ('backend/analytics/budget_impact.py', "STAGE = '48A'"),
        ('backend/analytics/premarket_conviction.py', "'stage': '48A'"),
    ):
        path = PROJECT_ROOT / rel
        if not path.is_file():
            failed.append(f'missing {rel}')
            continue
        if needle not in path.read_text(encoding='utf-8'):
            failed.append(f'{rel} missing {needle}')
    return failed


def main() -> int:
    failed = []
    failed.extend(_check_build_stage())

    all_validators = (
        VALIDATORS_48A
        + VALIDATORS_47F
        + VALIDATORS_47E
        + VALIDATORS_47D
        + VALIDATORS_47C
        + VALIDATORS_47B
        + VALIDATORS_47A
        + VALIDATORS_46J
        + VALIDATORS_46I
        + VALIDATORS_46H
    )
    for name in all_validators:
        path = PROJECT_ROOT / 'scripts' / name
        if not path.is_file():
            failed.append(f'missing {name}')
            continue
        print(f'--- {path.name} ---')
        if os.system(f'{sys.executable} "{path}"') != 0:
            failed.append(path.name)

    if failed:
        print(f'STAGE_48A_FAIL: {", ".join(failed)}', file=sys.stderr)
        return 1
    print('STAGE_48A_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
