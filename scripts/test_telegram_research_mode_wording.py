#!/usr/bin/env python3
"""Unit tests for stale-report research mode wording (Stage 48K)."""

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
    print(f'TELEGRAM_RESEARCH_MODE_WORDING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_action_plan_telegram, strip_stage_markers

    def _age_side_effect(path, **_k):
        name = Path(path).name
        if 'daily_report_pack' in name:
            return (120, 'stale-report')
        if 'scanner_data' in name:
            return (20, 'fresh-scan')
        if 'news_feed' in name:
            return (15, 'fresh-news')
        return (30, 'now')

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
        return_value={'market_mode': 'USA_MODE', 'summary': {'stale': False}},
    ), patch(
        'backend.analytics.aihub_tab_payloads.build_global_payload',
        return_value={'summary': {}},
    ), patch(
        'backend.telegram.lazy_command_runner._load_json',
        return_value={},
    ), patch(
        'backend.telegram.freshness_consistency.compute_feed_age_minutes',
        side_effect=_age_side_effect,
    ), patch(
        'backend.telegram.lazy_command_runner.DAILY_PACK_FILE',
        PROJECT_ROOT / 'data' / 'daily_report_pack_latest.json',
    ):
        text = strip_stage_markers(format_action_plan_telegram())

    required = (
        'Market state: Research mode',
        'Report: stale',
        'Scanner: fresh',
        'News: fresh',
        'Action: watch only, refresh before live entry.',
    )
    for line in required:
        if line not in text:
            return _fail(f'missing wording line: {line}')
    if 'Fresh/Stale: Fresh' in text:
        return _fail('must not claim fully fresh when report stale')
    if 'USA_MODE' in text:
        return _fail('wording test leaked USA_MODE')

    print('TELEGRAM_RESEARCH_MODE_WORDING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
