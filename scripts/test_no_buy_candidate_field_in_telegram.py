#!/usr/bin/env python3
"""Stage 50U — Telegram must not expose buy_candidate field name."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'NO_BUY_CANDIDATE_FIELD_IN_TELEGRAM_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_daily_pack_only
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text

    pack = {
        'generated_at': '2026-06-16T16:00:00+05:30',
        'summary': {},
        'final_confidence': {'watch': 2, 'avoid': 3, 'buy_candidate': 0},
    }
    with patch('backend.telegram.lazy_command_runner._load_json', return_value=pack), \
         patch('backend.telegram.lazy_command_runner.DAILY_PACK_FILE', PROJECT_ROOT / 'data' / 'daily_report_pack.json'):
        daily = run_daily_pack_only().get('text') or ''

    with patch('backend.telegram.lazy_command_runner.run_daily_pack_only', return_value={'text': daily}), \
         patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'Memory ok'}), \
         patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': 'Market ok'}), \
         patch('backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text', return_value='Tomorrow block'), \
         patch('backend.telegram.india_mode_lock.resolve_telegram_market_phase', return_value='INDIA_AFTER_HOURS'), \
         patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value={'lines': {}, 'report_stale': False}):
        close = build_close_brief_text()

    for label, text in (('daily_pack', daily), ('close', close)):
        if 'buy_candidate' in text.lower():
            return _fail(f'{label} exposes buy_candidate field name')
        if 'entry_candidates' not in daily:
            return _fail('daily pack should expose entry_candidates label')

    print('NO_BUY_CANDIDATE_FIELD_IN_TELEGRAM_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
