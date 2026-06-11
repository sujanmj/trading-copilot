#!/usr/bin/env python3
"""Stage 50H — why/wait bullets must not split strings char-by-char."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TELEGRAM_REASON_FORMAT_NOT_CHAR_BULLETS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import format_action_plan_telegram, format_why_ticker, normalize_bullet_items

    items = normalize_bullet_items('memory advisor learning_score=41 overall=caution')
    if items != ['memory advisor learning_score=41 overall=caution']:
        return _fail(f'string must become one bullet, got {items!r}')

    semi = normalize_bullet_items('Price confirmation; volume confirmation')
    if len(semi) != 2:
        return _fail(f'semicolon split expected 2 bullets, got {semi!r}')

    fake_row = {
        'ticker': 'RELIANCE',
        'action': 'WATCH_FOR_ENTRY',
        'score': 55,
        'confidence': 'MEDIUM',
        'why': 'memory advisor learning_score=41 overall=caution',
        'confirmation_needed': 'Price/volume confirmation required before entry.',
        'risk': [],
        'supports': ['memory'],
    }
    fake_payload = {
        'ok': True,
        'mode': 'today',
        'decision': 'NO_CLEAN_CANDIDATE',
        'ranked_candidates': [fake_row],
        'top_pick': fake_row,
        'telegram_message': '',
        'snapshot_warnings': [],
    }

    with patch('backend.analytics.stock_decision_engine.lookup_ticker_in_decision', return_value={
        'ok': True,
        'found': True,
        'breakdown': fake_row,
        'mode': 'today',
    }):
        why_text = format_why_ticker('RELIANCE', mode='today')

    if '• m' in why_text and '• e' in why_text:
        return _fail('format_why_ticker char-split bullets detected')
    if 'memory advisor learning_score=41 overall=caution' not in why_text:
        return _fail('format_why_ticker missing full why line')
    if 'Price/volume confirmation required before entry.' not in why_text:
        return _fail('format_why_ticker missing wait line')

    with patch('backend.analytics.railway_decision_bootstrap.repair_decision_for_telegram', return_value=(fake_payload, False, False)), \
         patch('backend.analytics.railway_decision_bootstrap.load_cached_stock_decision', return_value=None), \
         patch('backend.analytics.aihub_tab_payloads.build_brain_payload', return_value={'summary': {}}), \
         patch('backend.analytics.aihub_tab_payloads.build_market_payload', return_value={'summary': {}}), \
         patch('backend.analytics.aihub_tab_payloads.build_global_payload', return_value={'summary': {}}), \
         patch('backend.analytics.stock_decision_engine.build_stock_decision', return_value=fake_payload), \
         patch('backend.analytics.unified_decision_engine.apply_live_guard_to_payload', side_effect=lambda p: p), \
         patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value={'lines': {}}), \
         patch('backend.analytics.unified_decision_engine.note_snapshot_pick', return_value=None), \
         patch('backend.telegram.lazy_command_runner._load_json', return_value={}), \
         patch('backend.telegram.response_format.resolve_global_risk_text', return_value='neutral'):
        action_text = format_action_plan_telegram()

    if '• m' in action_text and '• e' in action_text:
        return _fail('action plan char-split bullets detected')
    if 'memory advisor learning_score=41 overall=caution' not in action_text:
        return _fail('action plan missing full why line')

    print('TELEGRAM_REASON_FORMAT_NOT_CHAR_BULLETS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
