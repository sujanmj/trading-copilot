#!/usr/bin/env python3
"""
Validate Stage 45B6 Telegram /aihub market summary clarity wiring.

Prints TELEGRAM_MARKET_SUMMARY_CLARITY_OK on success.
Marker: TELEGRAM_STAGE_45B6_MARKET_SUMMARY_CLARITY
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

MARKER = 'TELEGRAM_STAGE_45B6_MARKET_SUMMARY_CLARITY'


def _fail(msg: str) -> int:
    print(f'TELEGRAM_MARKET_SUMMARY_CLARITY_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    fmt_path = PROJECT_ROOT / 'backend/telegram/response_format.py'
    fmt_src = fmt_path.read_text(encoding='utf-8')

    if MARKER not in fmt_src:
        return _fail(f'missing stage marker {MARKER} in response_format.py')

    required_helpers = (
        'format_aihub_market_section',
        '_load_market_fallback_context',
        '_market_has_stale_warnings',
        'filter_empty_bullets',
    )
    for name in required_helpers:
        if f'def {name}' not in fmt_src:
            return _fail(f'response_format missing {name}')

    if 'format_aihub_market_section(payload)' not in fmt_src:
        return _fail('format_aihub_payload must delegate market tab to format_aihub_market_section')

    test_path = PROJECT_ROOT / 'scripts/test_telegram_market_summary_clarity.py'
    if not test_path.is_file():
        return _fail('missing scripts/test_telegram_market_summary_clarity.py')

    from backend.telegram.response_format import (
        MARKET_SUMMARY_CLARITY_STAGE_MARKER,
        format_aihub_market_section,
        strip_stage_markers,
    )

    if MARKET_SUMMARY_CLARITY_STAGE_MARKER != MARKER:
        return _fail('MARKET_SUMMARY_CLARITY_STAGE_MARKER mismatch')

    stale_lines = format_aihub_market_section({
        'market_mode': 'INDIA_MODE',
        'summary': {},
        'items': [],
        'warnings': ['market_data_stale', 'underlying_market_data_stale'],
    })
    stale_text = strip_stage_markers('\n'.join(stale_lines))
    for token in ("{'", '"bucket":', MARKER):
        if token in stale_text:
            return _fail(f'stale market section leaked forbidden token: {token}')
    if re.search(r'Mode:.*·\s*fresh|·\s*fresh\b', stale_text, re.IGNORECASE):
        return _fail('stale market section must not include fresh mode label')
    for required in (
        'Mode: INDIA_MODE',
        'Status: stale market snapshot',
        'Reason: underlying market data is old',
        'Refresh: /news or scheduled market refresh',
    ):
        if required not in stale_text:
            return _fail(f'stale market section missing: {required}')

    print(MARKER)
    print('TELEGRAM_MARKET_SUMMARY_CLARITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
