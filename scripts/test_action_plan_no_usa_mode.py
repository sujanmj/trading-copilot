#!/usr/bin/env python3
"""Unit tests — action plan must not show USA_MODE (Stage 48K)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'ACTION_PLAN_NO_USA_MODE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_action_plan_telegram, strip_stage_markers

    fake_market = {
        'market_mode': 'USA_MODE',
        'summary': {'market_mode': 'USA_MODE', 'stale': True},
    }
    fake_pack = {
        'market_mode': 'USA_MODE',
        'summary': {'market_mode': 'USA_MODE'},
        'final_confidence': {'active_mode': 'USA_MODE'},
    }

    with patch(
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
        return_value=fake_market,
    ), patch(
        'backend.analytics.aihub_tab_payloads.build_global_payload',
        return_value={'summary': {}},
    ), patch(
        'backend.telegram.lazy_command_runner._load_json',
        return_value=fake_pack,
    ), patch(
        'backend.telegram.freshness_consistency.compute_feed_age_minutes',
        return_value=(30, 'now'),
    ), patch(
        'backend.telegram.lazy_command_runner.DAILY_PACK_FILE',
        PROJECT_ROOT / 'data' / 'daily_report_pack_latest.json',
    ):
        text = strip_stage_markers(format_action_plan_telegram())

    if 'USA_MODE' in text:
        return _fail('action plan leaked USA_MODE')
    if 'INDIA_MODE' not in text and 'RESEARCH_MODE' not in text and 'Research mode' not in text:
        return _fail('action plan missing India/research mode wording')
    if 'AstraEdge Action Plan' not in text:
        return _fail('action plan header missing')

    print('ACTION_PLAN_NO_USA_MODE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
