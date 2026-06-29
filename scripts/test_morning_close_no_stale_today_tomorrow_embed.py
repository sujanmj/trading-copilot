#!/usr/bin/env python3
"""Stage 50Q — /morning and /close must not embed stale /today or /tomorrow blocks."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FRESH_META = {
    'scanner_fresh': True,
    'report_stale': True,
    'lines': {'report': 'Report: stale', 'scanner': 'Scanner: fresh', 'news': 'News: fresh'},
}
SCANNER_SIGNALS = [
    {'ticker': 'SONATSOFTW', 'change_percent': 4.2, 'volume_ratio': 1.6, 'strength': 'ULTRA', 'direction': 'BULLISH', 'price': 800},
    {'ticker': 'WABAG', 'change_percent': 3.1, 'volume_ratio': 1.4, 'strength': 'STRONG', 'direction': 'BULLISH', 'price': 1500},
]
STALE_PAYLOAD = {
    'ok': True,
    'mode': 'today',
    'decision': 'BUY_CANDIDATE',
    'top_pick': {'ticker': 'AVANTIFEED', 'action': 'BUY_CANDIDATE', 'score': 92, 'confidence': 'HIGH', 'why': ['stale report']},
    'ranked_candidates': [{'ticker': 'AVANTIFEED', 'action': 'BUY_CANDIDATE', 'score': 92, 'supports': ['final_confidence']}],
    'avoid': [],
    'telegram_message': '<b>AstraEdge — Today</b>\n\n<b>Top candidate:</b>\nAVANTIFEED — BUY CANDIDATE',
}


def _fail(msg: str) -> int:
    print(f'MORNING_CLOSE_NO_STALE_TODAY_TOMORROW_EMBED_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _common_patches():
    fake_fc = {'ok': True, 'top_candidates': [{'ticker': 'AVANTIFEED', 'score': 92}]}
    return (
        patch('backend.analytics.railway_decision_bootstrap.load_cached_stock_decision', return_value=STALE_PAYLOAD),
        patch('backend.analytics.railway_decision_bootstrap.repair_decision_for_telegram', return_value=(None, False, False)),
        patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=FRESH_META),
        patch('backend.analytics.unified_decision_engine.apply_live_guard_to_payload', side_effect=lambda p: p),
        patch('backend.analytics.unified_decision_engine.note_snapshot_pick'),
        patch('backend.telegram.lazy_command_runner.run_global_only', return_value={'text': 'Global: neutral'}),
        patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': 'Market: open soon'}),
        patch('backend.telegram.lazy_command_runner.run_daily_pack_only', return_value={'text': 'Pack: ready'}),
        patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'Memory: ok'}),
        patch('backend.telegram.telegram_brief_scheduler._load_json_file', return_value={
            'ok': True,
            'generated_at': '2026-05-01T15:30:00+05:30',
        }),
        patch('backend.telegram.telegram_brief_scheduler._run_safe_postmarket_pack_catchup_once', return_value={
            'ok': False,
            'reason': 'test stale pack',
        }),
        patch('backend.trading.unified_live_priority_engine._freshness_meta', return_value=FRESH_META),
        patch('backend.trading.unified_live_priority_engine._load_json', side_effect=lambda p: fake_fc if 'final_confidence' in str(p) else {}),
        patch('backend.trading.unified_live_priority_engine._live_registry', return_value={}),
        patch('backend.trading.unified_live_priority_engine._scanner_signals', return_value=SCANNER_SIGNALS),
        patch('backend.trading.unified_live_priority_engine._catalyst_priority_map', return_value={}),
        patch('backend.trading.trade_card_engine.detect_entry_missed', return_value=(True, [])),
        patch('backend.trading.trade_card_engine._compute_plan', side_effect=lambda row: {
            'price': float(row.get('price') or 100),
            'change_pct': float(row.get('change_percent') or 0),
            'volume_ratio': float(row.get('volume_ratio') or 1),
            'risk_reward': 2.0,
            'sl_pct': 0.8,
            'day_high': None,
            'vwap': None,
            'open_price': None,
        }),
    )


def main() -> int:
    from contextlib import ExitStack

    from backend.telegram.telegram_brief_scheduler import build_close_brief_text, build_morning_brief_text

    patches = _common_patches()
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        morning = build_morning_brief_text()
        close = build_close_brief_text()

    for label, text in ('morning', morning), ('close', close):
        if 'AVANTIFEED' in text:
            return _fail(f'{label} brief must not embed stale AVANTIFEED')
        if (
            'SONATSOFTW' not in text
            and 'NO VALID ENTRY NOW' not in text
            and 'No clean candidate' not in text
            and 'No clean active watch' not in text
        ):
            return _fail(f'{label} brief missing live scanner context')

    print('MORNING_CLOSE_NO_STALE_TODAY_TOMORROW_EMBED_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
