#!/usr/bin/env python3
"""Stage 50V — /tradecard triggers lightweight prices+scanner refresh during market hours."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TRADECARD_FORCES_LIGHTWEIGHT_REFRESH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/trading/tradecard_refresh.py').read_text(encoding='utf-8')
    if 'LIGHTWEIGHT_SCOPES' not in src or "'prices'" not in src or "'scanner'" not in src:
        return _fail('tradecard_refresh must define lightweight prices+scanner scopes')

    runner_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    if 'refresh_tradecard_market_data' not in runner_src:
        return _fail('run_tradecard_only must call refresh_tradecard_market_data')

    scopes_called: list[str] = []

    def _fake_scoped(scope: str, *, dry_run: bool = False):
        scopes_called.append(scope)
        if scope == 'prices':
            return {'ok': True, 'scope': scope, 'prices': 'ok'}
        if scope == 'scanner':
            return {'ok': True, 'scope': scope, 'scanner': 'ok'}
        return {'ok': True, 'scope': scope}

    from backend.trading.tradecard_refresh import (
        FORBIDDEN_HEAVY_SCOPES,
        reset_tradecard_cooldown_state,
        refresh_tradecard_market_data,
    )

    reset_tradecard_cooldown_state()

    with patch('backend.trading.tradecard_refresh.is_live_market_hours_phase', return_value=True), \
         patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_fake_scoped), \
         patch('backend.trading.tradecard_refresh._rebuild_unified_and_card'), \
         patch('backend.trading.tradecard_refresh._file_age_seconds', return_value=5):
        meta = refresh_tradecard_market_data('test-chat-refresh', force=True)

    if 'prices' not in scopes_called or 'scanner' not in scopes_called:
        return _fail(f'expected prices+scanner scopes got {scopes_called!r}')
    heavy_hits = [s for s in scopes_called if s in FORBIDDEN_HEAVY_SCOPES]
    if heavy_hits:
        return _fail(f'heavy scopes must not run: {heavy_hits!r}')
    for forbidden in ('news', 'brokers', 'govt', 'all', 'runtime'):
        if forbidden in scopes_called:
            return _fail(f'must not call /refresh full scope {forbidden!r}')

    if meta.get('quote_refreshed_now') is not True or meta.get('scanner_refreshed_now') is not True:
        return _fail(f'expected refreshed_now flags got {meta!r}')
    if meta.get('refresh_failed'):
        return _fail('lightweight refresh should succeed in mock')

    from backend.telegram.lazy_command_runner import run_tradecard_only

    scopes_called.clear()
    reset_tradecard_cooldown_state()
    with patch('backend.trading.tradecard_refresh.is_live_market_hours_phase', return_value=True), \
         patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_fake_scoped), \
         patch('backend.trading.tradecard_refresh._rebuild_unified_and_card'), \
         patch('backend.trading.tradecard_refresh._file_age_seconds', return_value=3), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value={'ok': False, 'ticker': '', 'status': 'NO_TRADE'}), \
         patch('backend.trading.trade_card_engine.is_trade_card_stale', return_value=False), \
         patch('backend.telegram.response_format._tradecard_unified_today_top', return_value=('', '')), \
         patch('backend.telegram.response_format._tradecard_reviewed_fallback', return_value=('', '')):
        run_tradecard_only('', chat_id='test-runner')

    if 'prices' not in scopes_called or 'scanner' not in scopes_called:
        return _fail(f'run_tradecard_only must refresh prices+scanner got {scopes_called!r}')

    print('TRADECARD_FORCES_LIGHTWEIGHT_REFRESH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
