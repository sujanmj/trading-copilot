#!/usr/bin/env python3
"""Stage 50Z hotfix - RESEARCH_MODE /close suppresses stale daily pack."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_journal, isolated_tradecard_latest


def _fail(msg: str) -> int:
    print(f'RESEARCH_MODE_CLOSE_SUPPRESSES_STALE_PACK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _must_not_run(*_args, **_kwargs):
    raise AssertionError('stale pack path must not run in research mode close')


def main() -> int:
    from backend.telegram.response_format import user_text_has_naked_buy_sell
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text
    from backend.trading.tradecard_latest import save_latest_tradecard

    meta = {
        'report_age_min': 3000,
        'scanner_age_min': 12,
        'news_age_min': 20,
        'report_stale': True,
        'report_suppressed': True,
        'scanner_fresh': True,
        'lines': {
            'report': 'Report: stale · 50h',
            'scanner': 'Scanner: fresh · 12m',
            'news': 'Latest news cache: fresh · 20m',
        },
    }
    card = {
        'ticker': 'SCHAEFFLER',
        'status': 'NO_ACTIVE_ENTRY',
        'entry_zone': 'NO ACTIVE ENTRY',
        'reason': 'research mode / market not open',
        'source_label': 'Source: scanner-confirmed',
    }

    with isolated_tradecard_latest(), isolated_tradecard_journal():
        save_latest_tradecard(
            'research-close',
            card,
            ticker='SCHAEFFLER',
            status='NO_ACTIVE_ENTRY',
            audit_only=True,
        )
        with patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=False), \
             patch('backend.telegram.india_mode_lock.resolve_telegram_market_phase', return_value='RESEARCH_MODE'), \
             patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=meta), \
             patch('backend.analytics.unified_decision_engine.is_report_display_suppressed', return_value=True), \
             patch('backend.telegram.lazy_command_runner.run_daily_pack_only', side_effect=_must_not_run), \
             patch('backend.telegram.lazy_command_runner.run_memory_only', side_effect=_must_not_run), \
             patch('backend.telegram.lazy_command_runner.run_market_only', side_effect=_must_not_run), \
             patch('backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text', side_effect=_must_not_run):
            text = build_close_brief_text()

    required = (
        'Research-mode summary',
        'Market mode: <code>RESEARCH_MODE</code>',
        'Report: stale',
        'Scanner: fresh',
        'Latest news cache: fresh',
        'No live intraday/EOD confirmation available in research mode.',
        'Report cache stale',
        'not using old daily pack as current',
        'Tradecards:',
        'Generated: 0',
        'Pending: 0',
        'Audit-only: 1',
        'SCHAEFFLER',
        'NEXT-SESSION WATCH ONLY',
        'Plan: confirm after 09:20 with fresh price + volume',
    )
    for needle in required:
        if needle not in text:
            return _fail(f'/close research summary missing {needle!r}')

    forbidden = (
        'Daily report pack',
        'Generated: 2026-05-01',
        'Final confidence',
        'AstraEdge — Tomorrow',
        'WATCH FOR ENTRY',
        'Top watch:',
    )
    upper = text.upper()
    for needle in forbidden:
        haystack = upper if needle.isupper() else text
        if needle in haystack:
            return _fail(f'/close research summary leaked stale/current wording {needle!r}')
    if user_text_has_naked_buy_sell(text):
        return _fail('/close research summary contains forbidden action wording')

    print('RESEARCH_MODE_CLOSE_SUPPRESSES_STALE_PACK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
