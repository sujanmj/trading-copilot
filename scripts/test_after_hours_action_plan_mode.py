#!/usr/bin/env python3
"""Unit tests — action plan shows INDIA_AFTER_HOURS mode (Stage 48S)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

AFTER_HOURS_MODE = {
    'market_mode': 'INDIA_AFTER_HOURS',
    'mode_code': 'INDIA_AFTER_HOURS_MODE',
}


def _fail(msg: str) -> int:
    print(f'AFTER_HOURS_ACTION_PLAN_MODE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_action_plan_telegram, strip_stage_markers

    with patch('backend.analytics.market_calendar_router.get_india_telegram_mode', return_value=AFTER_HOURS_MODE), patch(
        'backend.analytics.railway_decision_bootstrap.repair_decision_for_telegram',
        return_value=(None, False, False),
    ), patch(
        'backend.analytics.railway_decision_bootstrap.load_cached_stock_decision',
        return_value={'ok': False},
    ), patch(
        'backend.analytics.stock_decision_engine.build_stock_decision',
        return_value={'ok': False},
    ), patch(
        'backend.analytics.aihub_tab_payloads.build_brain_payload',
        return_value={'summary': {}},
    ), patch(
        'backend.analytics.aihub_tab_payloads.build_market_payload',
        return_value={'market_mode': 'INDIA_AFTER_HOURS', 'summary': {'market_mode': 'INDIA_AFTER_HOURS'}},
    ), patch(
        'backend.analytics.aihub_tab_payloads.build_global_payload',
        return_value={'summary': {}},
    ), patch(
        'backend.telegram.lazy_command_runner._load_json',
        return_value={'market_mode': 'INDIA_AFTER_HOURS'},
    ), patch(
        'backend.telegram.freshness_consistency.compute_feed_age_minutes',
        return_value=(30, 'now'),
    ):
        action_text = strip_stage_markers(format_action_plan_telegram())

    if 'INDIA_MODE' in action_text and 'INDIA_AFTER_HOURS' not in action_text:
        return _fail('action plan must not collapse to INDIA_MODE during after-hours')
    if 'INDIA_AFTER_HOURS' not in action_text:
        return _fail('action plan missing INDIA_AFTER_HOURS mode label')

    print('AFTER_HOURS_ACTION_PLAN_MODE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
