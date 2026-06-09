#!/usr/bin/env python3
"""Unit tests — /full snapshot surfaces share market phase (Stage 48S)."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = ZoneInfo('Asia/Kolkata')
EXPECTED_PHASE = 'INDIA_AFTER_HOURS'
AFTER_HOURS_MODE = {
    'market_mode': EXPECTED_PHASE,
    'mode_code': 'INDIA_AFTER_HOURS_MODE',
}


def _fail(msg: str) -> int:
    print(f'FULL_SNAPSHOT_MARKET_PHASE_CONSISTENCY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _assert_phase(name: str, text: str) -> int | None:
    if EXPECTED_PHASE not in text:
        return _fail(f'{name} missing {EXPECTED_PHASE}')
    if 'Mode: INDIA_MODE' in text or 'mode: INDIA_MODE' in text:
        return _fail(f'{name} collapsed to INDIA_MODE')
    return None


def main() -> int:
    from backend.analytics.premarket_conviction import format_premarket_telegram
    from backend.telegram.response_format import (
        format_action_plan_telegram,
        format_aihub_payload,
        format_status_text,
        strip_stage_markers,
    )
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text, build_morning_brief_text

    premarket_data = {
        'market_bias': 'Neutral',
        'top_setups': [{'ticker': 'RELIANCE', 'score': 70, 'reasons': ['test'], 'setup': 'watch'}],
        'avoid': [],
        'market_mode': AFTER_HOURS_MODE,
        'freshness_ok': True,
        'generated_at': datetime.now(IST).isoformat(),
    }
    market_payload = {
        'market_mode': EXPECTED_PHASE,
        'summary': {'market_mode': EXPECTED_PHASE},
        'cache_age_seconds': 60,
        'source': 'cache',
        'items': [],
    }

    patches = [
        patch('backend.analytics.market_calendar_router.get_india_telegram_mode', return_value=AFTER_HOURS_MODE),
        patch('backend.analytics.railway_decision_bootstrap.repair_decision_for_telegram', return_value=(None, False, False)),
        patch('backend.analytics.railway_decision_bootstrap.load_cached_stock_decision', return_value={'ok': False}),
        patch('backend.analytics.stock_decision_engine.build_stock_decision', return_value={'ok': False}),
        patch('backend.analytics.aihub_tab_payloads.build_brain_payload', return_value={'summary': {}}),
        patch('backend.analytics.aihub_tab_payloads.build_market_payload', return_value=market_payload),
        patch('backend.analytics.aihub_tab_payloads.build_global_payload', return_value={'summary': {}}),
        patch('backend.telegram.lazy_command_runner._load_json', return_value={'market_mode': EXPECTED_PHASE}),
        patch('backend.telegram.freshness_consistency.compute_feed_age_minutes', return_value=(30, 'now')),
        patch('backend.telegram.lazy_command_runner.run_global_only', return_value={'text': 'Global ok'}),
        patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': f'Mode: {EXPECTED_PHASE}'}),
        patch('backend.telegram.lazy_command_runner.run_daily_pack_only', return_value={'text': 'Pack ok'}),
        patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'Memory ok'}),
        patch('backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text', return_value='Today ok'),
    ]

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13]:
        surfaces = {
            'status': format_status_text(),
            'action_plan': strip_stage_markers(format_action_plan_telegram()),
            'premarket': format_premarket_telegram(full=False, report=premarket_data),
            'premarket_full': format_premarket_telegram(full=True, report=premarket_data),
            'aihub_market': format_aihub_payload('market', market_payload),
            'morning': build_morning_brief_text(),
            'close': build_close_brief_text(),
        }

    for name, text in surfaces.items():
        err = _assert_phase(name, text)
        if err:
            return err

    if 'Market open' in surfaces['premarket'] or 'Market open' in surfaces['premarket_full']:
        return _fail('premarket surfaces must not say Market open during after-hours')

    print('FULL_SNAPSHOT_MARKET_PHASE_CONSISTENCY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
