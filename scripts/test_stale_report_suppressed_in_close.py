#!/usr/bin/env python3
"""Stage 50Z — stale report >24h suppressed in /close."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'STALE_REPORT_SUPPRESSED_IN_CLOSE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text

    stale_pack = '<b>📦 Daily report pack</b>\nGenerated: 2026-05-01T15:30:00\nFinal confidence — watch: 3'
    meta = {
        'report_age_min': 3000,
        'scanner_age_min': 10,
        'scanner_fresh': True,
        'report_stale': True,
        'report_suppressed': True,
        'lines': {
            'report': 'Report: 50h old',
            'scanner': 'Scanner: 10m old',
            'news': 'News: 20m old',
        },
    }

    with patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=False), \
         patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=False), \
         patch('backend.telegram.lazy_command_runner.run_daily_pack_only', return_value={'text': stale_pack}), \
         patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'memory'}), \
         patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': 'market'}), \
         patch('backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text', return_value='tomorrow'), \
         patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=meta), \
         patch('backend.analytics.unified_decision_engine.is_report_display_suppressed', return_value=True), \
         patch('backend.trading.tradecard_journal.sample_and_resolve_pending_tradecards', return_value={'sampled': 0}), \
         patch('backend.trading.tradecard_journal.format_tradecard_review_section', return_value='<b>Tradecards:</b>'):
        text = build_close_brief_text()

    if 'Report cache stale' not in text:
        return _fail('must show stale report suppression line')
    if 'Live scanner is fresh' not in text:
        return _fail('must note live scanner override')
    if '2026-05-01' in text or 'Final confidence — watch: 3' in text:
        return _fail('must not show stale daily report pack body')

    print('STALE_REPORT_SUPPRESSED_IN_CLOSE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
