#!/usr/bin/env python3
"""
Dry-run tests for Stock Confluence Decision Engine (Stage 45B).

Prints STOCK_DECISION_ENGINE_TEST_OK on success.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'STOCK_DECISION_ENGINE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _assert_payload(payload: dict, *, mode: str) -> str | None:
    if payload.get('ok') is not True:
        return f'{mode} ok != true: {payload.get("error")}'
    if payload.get('mode') != mode:
        return f'{mode} mode mismatch'
    if not payload.get('telegram_message'):
        return f'{mode} missing telegram_message'
    decision = str(payload.get('decision') or '')
    top = payload.get('top_pick')
    if decision == 'NO_CLEAN_CANDIDATE':
        if top is not None and isinstance(top, dict) and top.get('action') == 'AVOID':
            pass
        elif top is None or not payload.get('telegram_message'):
            if 'No clean candidate' not in str(payload.get('telegram_message')):
                return f'{mode} NO_CLEAN_CANDIDATE message missing'
    elif not isinstance(top, dict) or not top.get('ticker'):
        return f'{mode} missing top_pick for decision={decision}'
    return None


def main() -> int:
    from backend.analytics import stock_decision_engine as engine
    from backend.analytics.stock_decision_engine import (
        STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE,
        build_stock_decision,
        lookup_ticker_in_decision,
    )
    from backend.telegram.response_format import format_stock_decision_telegram, format_why_ticker

    if not STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE:
        return _fail('stage marker constant must be True')

    today = build_stock_decision(mode='today')
    err = _assert_payload(today, mode='today')
    if err:
        return _fail(err)

    tomorrow = build_stock_decision(mode='tomorrow')
    err = _assert_payload(tomorrow, mode='tomorrow')
    if err:
        return _fail(err)

    ranked = today.get('ranked_candidates') or []
    if not ranked:
        return _fail('ranked_candidates empty')

    broker_only = engine._score_candidate(
        'BROKERONLY',
        {
            'fc_row': None,
            'wl_row': None,
            'scanner_rows': [],
            'broker_rows': [{'agreement': True, 'broker_stance': 'BUY', 'source': 'test'}],
            'external_rows': [],
            'global_sectors': set(),
            'memory_rows': [],
            'sources_seen': {'broker'},
        },
        engine._load_sources(),
        mode='today',
    )
    if broker_only.get('action') == 'BUY_CANDIDATE':
        return _fail('broker alone must not force BUY')

    avoid_row = next((r for r in ranked if r.get('action') == 'AVOID'), None)
    if avoid_row:
        if avoid_row.get('action') == 'BUY_CANDIDATE':
            return _fail('AVOID name became BUY')
        fc_decision = avoid_row.get('fc_decision') or ''
        if 'AVOID' in str(fc_decision).upper() and avoid_row.get('action') != 'AVOID':
            return _fail('fc AVOID must stay AVOID')

    for mode in ('today', 'tomorrow'):
        text = format_stock_decision_telegram(mode)
        if len(text.strip()) < 30:
            return _fail(f'format_stock_decision_telegram({mode}) too short')
        if 'Decision Engine is pending' in text:
            return _fail(f'{mode} telegram still uses pending wording')

    why = lookup_ticker_in_decision('TATA', mode='today')
    if why.get('ok') is not True:
        return _fail('/why lookup failed')
    if why.get('found'):
        why_text = format_why_ticker('TATA', mode='today')
        if len(why_text.strip()) < 20:
            return _fail('/why TATA text too short')
        if 'Why' not in why_text and 'why' not in why_text.lower():
            return _fail('/why TATA missing why section')

    bot_src = (PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_analysis_bot.py').read_text(encoding='utf-8')
    if 'format_stock_decision_telegram' not in bot_src and 'build_stock_decision' not in bot_src:
        return _fail('telegram bot must use stock decision engine')
    if "cmd == 'why'" not in bot_src and "cmd in ('why'" not in bot_src:
        return _fail('/why command handler missing')

    with patch.object(engine, 'build_stock_decision', wraps=build_stock_decision) as mocked:
        from backend.telegram.telegram_analysis_bot import handle_analysis_command

        handle_analysis_command('/today', 'test', dry_run=True)
        handle_analysis_command('/tomorrow', 'test', dry_run=True)
        modes = [call.kwargs.get('mode') or (call.args[0] if call.args else None) for call in mocked.call_args_list]
        if 'today' not in modes or 'tomorrow' not in modes:
            return _fail('/today and /tomorrow must call build_stock_decision')

    print('STOCK_DECISION_ENGINE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
