#!/usr/bin/env python3
"""Stage 50Z hotfix - no-active latest audit is not rendered as normal watch."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_latest


def _fail(msg: str) -> int:
    print(f'NO_ACTIVE_ENTRY_NOT_WATCH_FOR_ENTRY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _assert_watch_only(label: str, text: str) -> int | None:
    if 'SCHAEFFLER' not in text:
        return _fail(f'{label} must mention SCHAEFFLER')
    if 'NEXT-SESSION WATCH ONLY' not in text:
        return _fail(f'{label} must render next-session watch-only wording')
    if 'Reason: no active entry in current mode' not in text:
        return _fail(f'{label} missing no-active reason')
    if 'Plan: confirm after 09:20 with fresh price + volume' not in text:
        return _fail(f'{label} missing confirmation plan')
    if 'WATCH FOR ENTRY' in text.upper():
        return _fail(f'{label} must not render normal watch-for-entry wording')
    if 'Top watch:' in text:
        return _fail(f'{label} must not render normal top-watch header')
    return None


def main() -> int:
    from backend.telegram.response_format import format_stock_decision_payload, user_text_has_naked_buy_sell
    from backend.trading.tradecard_latest import save_latest_tradecard
    from backend.trading.unified_live_priority_engine import format_tomorrow_unified

    payload = {
        'ok': True,
        'mode': 'tomorrow',
        'decision': 'WATCH_FOR_ENTRY',
        'top_pick': {
            'ticker': 'SCHAEFFLER',
            'action': 'WATCH_FOR_ENTRY',
            'unified_score': 82,
            'score': 82,
            'confidence': 'HIGH',
            'why': ['scanner-confirmed'],
            'risk': [],
        },
        'ranked_candidates': [],
        'missed_candidates': [],
        'telegram_message': (
            '<b>AstraEdge — Tomorrow</b>\n\n'
            '<b>Top watch:</b>\n'
            'SCHAEFFLER — WATCH FOR ENTRY\n'
        ),
    }

    with isolated_tradecard_latest():
        save_latest_tradecard(
            'no-active-watch',
            {
                'ticker': 'SCHAEFFLER',
                'status': 'NO_ACTIVE_ENTRY',
                'entry_zone': 'NO ACTIVE ENTRY',
                'reason': 'research mode / market not open',
            },
            ticker='SCHAEFFLER',
            status='NO_ACTIVE_ENTRY',
            audit_only=True,
        )

        unified = format_tomorrow_unified(payload)
        err = _assert_watch_only('unified tomorrow', unified)
        if err:
            return err

        stock = format_stock_decision_payload(payload, 'tomorrow')
        err = _assert_watch_only('stock decision tomorrow', stock)
        if err:
            return err

        no_clean = format_tomorrow_unified({
            'ok': True,
            'mode': 'tomorrow',
            'decision': 'NO_CLEAN_CANDIDATE',
            'top_pick': None,
            'ranked_candidates': [],
            'missed_candidates': [],
        })

    if 'No clean active watch yet.' not in no_clean:
        return _fail('no-clean path must say no clean active watch yet')
    if 'Research-only watch: SCHAEFFLER' not in no_clean:
        return _fail('no-clean path must show research-only latest audit ticker')
    for label, text in (('unified', unified), ('stock', stock), ('no_clean', no_clean)):
        if user_text_has_naked_buy_sell(text):
            return _fail(f'{label} contains forbidden action wording')

    print('NO_ACTIVE_ENTRY_NOT_WATCH_FOR_ENTRY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
