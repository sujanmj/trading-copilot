#!/usr/bin/env python3
"""Stage 50V — repeated /tradecard within cooldown reuses cache."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_REFRESH_COOLDOWN_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    os.environ['TRADECARD_REFRESH_COOLDOWN_SECONDS'] = '30'
    os.environ.pop('TRADECARD_FORCE_REFRESH', None)

    scopes_called: list[str] = []

    def _fake_scoped(scope: str, *, dry_run: bool = False):
        scopes_called.append(scope)
        return {'ok': True, 'scope': scope, scope: 'ok', 'prices': 'ok'}

    from backend.trading.tradecard_refresh import (
        format_freshness_line,
        reset_tradecard_cooldown_state,
        refresh_tradecard_market_data,
    )

    reset_tradecard_cooldown_state()
    chat = 'cooldown-chat-50v'

    with patch('backend.trading.tradecard_refresh.is_live_market_hours_phase', return_value=True), \
         patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_fake_scoped), \
         patch('backend.trading.tradecard_refresh._rebuild_unified_and_card'), \
         patch('backend.trading.tradecard_refresh._file_age_seconds', return_value=12):
        first = refresh_tradecard_market_data(chat, force=False)
        second = refresh_tradecard_market_data(chat, force=False)

    if not scopes_called:
        return _fail('first call must attempt refresh')
    first_call_count = len(scopes_called)
    scopes_called.clear()

    if second.get('cooldown_reused') is not True:
        return _fail(f'second call must reuse cooldown cache got {second!r}')
    if scopes_called:
        return _fail(f'second call must not hit APIs got scopes {scopes_called!r}')

    line = format_freshness_line(second)
    if 'reused' not in line or 'cooldown' not in line:
        return _fail(f'freshness line must mention cooldown reuse got {line!r}')

    from backend.telegram.lazy_command_runner import run_tradecard_only

    reset_tradecard_cooldown_state()
    scopes_called.clear()
    with patch('backend.trading.tradecard_refresh.is_live_market_hours_phase', return_value=True), \
         patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_fake_scoped), \
         patch('backend.trading.tradecard_refresh._rebuild_unified_and_card'), \
         patch('backend.trading.tradecard_refresh._file_age_seconds', return_value=8), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value={'ok': False, 'ticker': '', 'status': 'NO_TRADE'}), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.telegram.response_format._tradecard_reviewed_fallback', return_value=('', '')):
        run_tradecard_only('', chat_id=chat)
        result = run_tradecard_only('', chat_id=chat)

    text = result.get('text') or ''
    if 'reused' not in text or 'cooldown' not in text:
        return _fail(f'/tradecard output must show cooldown reuse got {text[:200]!r}')

    if first_call_count < 2:
        return _fail('first refresh should call at least prices and scanner')

    print('TRADECARD_REFRESH_COOLDOWN_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
