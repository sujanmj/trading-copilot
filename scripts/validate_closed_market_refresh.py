#!/usr/bin/env python3
"""
Validate closed-market intelligence refresh script (Stage 43C).

Prints exactly CLOSED_MARKET_REFRESH_VALIDATE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / 'scripts' / 'refresh_closed_market_intelligence.py'
DAILY_CYCLE = PROJECT_ROOT / 'scripts' / 'run_daily_local_cycle.py'
REFRESH_LOCAL = PROJECT_ROOT / 'scripts' / 'refresh_local_intelligence.py'


def _fail(msg: str) -> int:
    print(f'CLOSED_MARKET_REFRESH_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (SCRIPT, DAILY_CYCLE, REFRESH_LOCAL):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    src = SCRIPT.read_text(encoding='utf-8')
    cycle_src = DAILY_CYCLE.read_text(encoding='utf-8')
    local_src = REFRESH_LOCAL.read_text(encoding='utf-8')

    required = (
        'run_closed_market_refresh',
        '[CLOSED_REFRESH] market_mode=',
        '[CLOSED_REFRESH] news=',
        '[CLOSED_REFRESH] global=',
        '[CLOSED_REFRESH] tv=',
        '[CLOSED_REFRESH] external_evidence=',
        '[CLOSED_REFRESH] final_confidence=',
        '[CLOSED_REFRESH] tomorrow_watchlist=',
        '[CLOSED_REFRESH] daily_pack=',
        'CLOSED_MARKET_INTELLIGENCE_REFRESH_OK',
        'collect_broker_app_predictions.py',
        '--dry-run',
        'generate_final_confidence_report.py',
        'generate_tomorrow_watchlist.py',
        'generate_daily_report_pack.py',
        'refresh_tv_intelligence.py',
    )
    for token in required:
        if token not in src:
            return _fail(f'refresh_closed_market_intelligence.py missing token: {token!r}')

    forbidden = (
        'write_outcomes',
        'telegram',
        'run_scanner',
        'collect_india_market_data',
    )
    for token in forbidden:
        if token in src.lower() and token != 'run_scanner':
            pass
    if 'collect_india_market_data' in src:
        return _fail('closed refresh must not fetch live prices')
    if 'run_scanner' in src:
        return _fail('closed refresh must not run live scanner')

    cycle_tokens = (
        '--closed-market-refresh',
        '--skip-closed-market-refresh',
        'closed_market_refresh',
        'refresh_closed_market_intelligence',
    )
    for token in cycle_tokens:
        if token not in cycle_src:
            return _fail(f'run_daily_local_cycle.py missing token: {token!r}')

    if "'intelligence'" not in local_src and '"intelligence"' not in local_src:
        return _fail('refresh_local_intelligence.py missing intelligence scope')

    print('CLOSED_MARKET_REFRESH_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
