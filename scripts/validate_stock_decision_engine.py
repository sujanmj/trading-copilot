#!/usr/bin/env python3
"""
Validate Stock Confluence Decision Engine wiring (Stage 45B).

Prints STOCK_DECISION_ENGINE_OK on success.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

MARKER = 'STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE'
REQUIRED_FILES = (
    'backend/analytics/stock_decision_engine.py',
    'scripts/generate_stock_decision.py',
    'scripts/test_stock_decision_engine.py',
    'scripts/validate_stock_decision_engine.py',
)


def _fail(msg: str) -> int:
    print(f'STOCK_DECISION_ENGINE_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in REQUIRED_FILES:
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing file: {rel}')

    engine_src = (PROJECT_ROOT / 'backend/analytics/stock_decision_engine.py').read_text(encoding='utf-8')
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    fmt_src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')

    if MARKER not in engine_src:
        return _fail(f'engine missing marker {MARKER}')
    if 'def build_stock_decision(' not in engine_src:
        return _fail('build_stock_decision missing')
    if 'BUY_INDEPENDENT_SUPPORTS' not in engine_src:
        return _fail('broker confluence logic missing')
    if 'Never force BUY' not in engine_src and 'broker alone' not in engine_src.lower():
        if '_broker_agrees' not in engine_src:
            return _fail('broker confluence helpers missing')

    if '/api/debug/stock-decision' not in api_src:
        return _fail('API route /api/debug/stock-decision missing')
    if 'build_stock_decision' not in api_src:
        return _fail('API must call build_stock_decision')

    if 'build_stock_decision' not in fmt_src:
        return _fail('response_format must use build_stock_decision')
    if 'format_why_ticker' not in fmt_src:
        return _fail('format_why_ticker missing')
    if 'Stock Decision Engine is pending' in fmt_src:
        return _fail('pending wording must be removed from response_format')

    if 'format_stock_decision_telegram' not in bot_src and 'build_stock_decision' not in bot_src:
        return _fail('telegram bot must call stock decision engine')
    if "cmd == 'why'" not in bot_src and "cmd in ('why'" not in bot_src:
        return _fail('/why command missing in bot')
    if 'place_order' in bot_src and 'BLOCKED_TRADE' not in bot_src:
        return _fail('order execution must remain blocked')

    from backend.analytics.stock_decision_engine import (
        STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE,
        build_stock_decision,
    )

    if not STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE:
        return _fail('STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE must be True')

    payload = build_stock_decision(mode='today')
    if payload.get('ok') is not True:
        return _fail(f'build_stock_decision today failed: {payload.get("error")}')
    if not payload.get('telegram_message'):
        return _fail('telegram_message missing from payload')

    print(MARKER)
    print('STOCK_DECISION_ENGINE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
