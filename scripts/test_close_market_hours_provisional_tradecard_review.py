#!/usr/bin/env python3
"""Stage 50Z hotfix — /close during market hours shows provisional tradecard review."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CLOSE_MARKET_HOURS_PROVISIONAL_TRADECARD_REVIEW_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text
    from backend.trading.tradecard_journal import format_tradecard_review_section

    section = format_tradecard_review_section(provisional=True)
    if 'provisional intraday review' not in section.lower():
        return _fail('provisional section must label intraday review')
    if 'Final EOD resolution will run after market close.' not in section:
        return _fail('provisional section must note final EOD resolution')

    with patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=True), \
         patch('backend.telegram.lazy_command_runner.run_daily_pack_only', return_value={'text': 'pack'}), \
         patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'memory'}), \
         patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': 'market'}), \
         patch('backend.trading.tradecard_journal.sample_and_resolve_pending_tradecards', return_value={'sampled': 0}), \
         patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value={'lines': {}, 'report_stale': False}):
        close_text = build_close_brief_text()

    if 'provisional intraday review' not in close_text.lower():
        return _fail('/close during market hours must show provisional tradecard review')

    print('CLOSE_MARKET_HOURS_PROVISIONAL_TRADECARD_REVIEW_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
