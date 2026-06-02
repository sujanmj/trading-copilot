#!/usr/bin/env python3
"""
Validate clean Telegram output wiring (Stage 45TG5).

Prints TELEGRAM_OUTPUT_CLEAN_OK on success.
Marker: TELEGRAM_STAGE_45TG5_OUTPUT_CLEAN_AIHUB_FULL
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

MARKER = 'TELEGRAM_STAGE_45TG5_OUTPUT_CLEAN_AIHUB_FULL'
BLOCKED_RESPONSE = (
    "I can't place orders. Try /today, /tomorrow, /aihub scan, or /ask ai <question>."
)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_OUTPUT_CLEAN_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    fmt_path = PROJECT_ROOT / 'backend' / 'telegram' / 'response_format.py'
    bot_path = PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_analysis_bot.py'
    lazy_path = PROJECT_ROOT / 'backend' / 'telegram' / 'lazy_command_runner.py'
    test_path = PROJECT_ROOT / 'scripts' / 'test_telegram_output_clean.py'

    for path in (fmt_path, bot_path, lazy_path, test_path):
        if not path.is_file():
            return _fail(f'missing file: {path.relative_to(PROJECT_ROOT)}')

    fmt_src = fmt_path.read_text(encoding='utf-8')
    bot_src = bot_path.read_text(encoding='utf-8')
    lazy_src = lazy_path.read_text(encoding='utf-8')

    if MARKER not in lazy_src:
        return _fail(f'lazy_command_runner missing marker {MARKER}')
    if 'def strip_stage_markers(' not in fmt_src:
        return _fail('response_format missing strip_stage_markers()')
    if BLOCKED_RESPONSE not in fmt_src:
        return _fail('missing clean blocked order response')
    if 'def format_aihub_full(' not in fmt_src:
        return _fail('missing format_aihub_full()')
    if 'def run_aihub_full_only(' not in lazy_src:
        return _fail('missing run_aihub_full_only()')

    if "tab in ('full', 'all')" not in bot_src:
        return _fail('/aihub full and /aihub all alias missing')
    if 'Order commands are not supported' in bot_src:
        return _fail('help must not list unsupported order commands')
    if RESEARCH_FOOTER := 'Research only. You decide and place trades manually.':
        if f'<i>{RESEARCH_FOOTER}</i>' in bot_src:
            return _fail('help must not append research footer')

    if 'build_stock_decision' not in fmt_src:
        return _fail('/today /tomorrow must use stock decision engine')
    if 'format_why_ticker' not in fmt_src:
        return _fail('/why formatter missing')
    if 'Stock Decision Engine is pending' in fmt_src:
        return _fail('pending wording must be removed')
    if 'Trading: <b>manual by user</b>' in fmt_src:
        return _fail('status must not show manual trading line')

    if 'with_shadow_disclaimer' in fmt_src:
        body = fmt_src.split('def with_shadow_disclaimer', 1)[1]
        if RESEARCH_FOOTER in body.split('def ', 2)[0] and 'return f' in body:
            return _fail('with_shadow_disclaimer must not auto-append footer')

    from backend.telegram.lazy_command_runner import STAGE_MARKER
    from backend.telegram.response_format import (
        BLOCKED_TRADE_RESPONSE,
        TRADE_EXECUTION_PERMANENTLY_DISABLED,
        strip_stage_markers,
    )

    if STAGE_MARKER != MARKER:
        return _fail('STAGE_MARKER mismatch')
    if BLOCKED_TRADE_RESPONSE != BLOCKED_RESPONSE:
        return _fail('BLOCKED_TRADE_RESPONSE mismatch')
    if not TRADE_EXECUTION_PERMANENTLY_DISABLED:
        return _fail('TRADE_EXECUTION_PERMANENTLY_DISABLED must be True')

    sample = strip_stage_markers(
        'Hello\n<i>Research only. You decide and place trades manually.</i>\n'
        f'<code>{MARKER}</code>'
    )
    if 'Research only' in sample or MARKER in sample:
        return _fail('strip_stage_markers did not sanitize sample text')

    print(MARKER)
    print('TELEGRAM_OUTPUT_CLEAN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
