#!/usr/bin/env python3
"""Stage 50Z — /close blocked during premarket with no stale close pack."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CLOSE_BLOCKED_DURING_PREMARKET_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text

    stale_pack = '<b>📦 Daily report pack</b>\nGenerated: 2026-05-20T15:30:00'

    with patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=True), \
         patch('backend.telegram.india_mode_lock.resolve_telegram_market_phase', return_value='INDIA_PREMARKET_MODE'), \
         patch('backend.telegram.lazy_command_runner.run_daily_pack_only', return_value={'text': stale_pack}), \
         patch('backend.trading.tradecard_journal.summarize_today_outcomes', return_value={'counts': {'generated': 2}}):
        text = build_close_brief_text()

    if 'Close summary not available yet' not in text:
        return _fail('premarket /close must say close summary not available')
    if 'INDIA_PREMARKET_MODE' not in text:
        return _fail('must show premarket mode')
    if 'market has not completed today' not in text:
        return _fail('must explain market not completed')
    if 'Tradecards today: 2' not in text:
        return _fail('must show tradecard count')
    if 'No final EOD resolution yet' not in text:
        return _fail('must note no final EOD resolution')
    if 'Daily report pack' in text or '2026-05-20' in text:
        return _fail('must not show stale daily report pack during premarket /close')
    if 'Market close summary' in text:
        return _fail('must not show market close summary header during premarket')

    print('CLOSE_BLOCKED_DURING_PREMARKET_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
