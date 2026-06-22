#!/usr/bin/env python3
"""Stage 50Z — /close during market hours uses intraday provisional, not Tomorrow."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CLOSE_MARKET_HOURS_INTRADAY_NOT_TOMORROW_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text
    from backend.trading.unified_live_priority_engine import format_intraday_provisional_unified

    intraday = format_intraday_provisional_unified({
        'ok': True,
        'decision': 'NO_CLEAN_CANDIDATE',
        'top_pick': None,
        'missed_candidates': [{'ticker': 'NOCIL', 'entry_missed': True, 'entry_status': 'ENTRY_MISSED'}],
        'ranked_candidates': [],
    })
    if 'Intraday provisional view' not in intraday:
        return _fail('intraday formatter must use provisional title')
    if 'Tomorrow' in intraday:
        return _fail('intraday formatter must not use Tomorrow title')

    with patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=False), \
         patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=True), \
         patch('backend.telegram.lazy_command_runner.run_daily_pack_only', return_value={'text': ''}), \
         patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'memory'}), \
         patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': 'market'}), \
         patch('backend.trading.unified_live_priority_engine.format_intraday_provisional_unified', return_value=intraday), \
         patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value={'lines': {}, 'report_stale': False}), \
         patch('backend.analytics.unified_decision_engine.is_report_display_suppressed', return_value=False), \
         patch('backend.trading.tradecard_journal.sample_and_resolve_pending_tradecards', return_value={'sampled': 0}), \
         patch('backend.trading.tradecard_journal.format_tradecard_review_section', return_value='<b>Tradecards:</b>\nGenerated: 0'):
        close_text = build_close_brief_text()

    if 'Intraday provisional view' not in close_text:
        return _fail('/close during market hours must include intraday provisional section')
    if 'AstraEdge — Tomorrow' in close_text:
        return _fail('/close during market hours must not show Tomorrow header')

    print('CLOSE_MARKET_HOURS_INTRADAY_NOT_TOMORROW_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
