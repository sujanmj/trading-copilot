#!/usr/bin/env python3
"""Validate Telegram output sanitizer removes replacement characters."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main() -> int:
    from backend.telegram.formatting.telegram_formatter import sanitize_telegram_text
    from backend.telegram.response_format import strip_stage_markers

    cases = {
        '�� <b>Bullish:</b>': '<b>Bullish:</b>',
        '��� <b>IOC</b> · ACTIVE · risk': '<b>IOC</b> · ACTIVE · risk',
        '�� <b>HDFCBANK</b>': '<b>HDFCBANK</b>',
        '18 �� resolved today 0': '18 · resolved today 0',
    }
    for raw, expected in cases.items():
        cleaned = sanitize_telegram_text(raw)
        if cleaned != expected:
            print(f'TELEGRAM_OUTPUT_SANITIZER_FAIL: {raw!r} -> {cleaned!r}', file=sys.stderr)
            return 1
        if '�' in strip_stage_markers(raw):
            print(f'TELEGRAM_OUTPUT_SANITIZER_FAIL: strip_stage_markers kept replacement char for {raw!r}', file=sys.stderr)
            return 1

    emoji_text = sanitize_telegram_text('🔴 Risk\n🟢 Fresh\n🛡️ Guard\n⚠️ Warning\n✅ Done\n👀 Watch\n📡 Status\n📊 Stats\n🧠 Brain\n🏛️ Govt')
    for emoji in ('🔴', '🟢', '🛡️', '⚠️', '✅', '👀', '📡', '📊', '🧠', '🏛️'):
        if emoji not in emoji_text:
            print(f'TELEGRAM_OUTPUT_SANITIZER_FAIL: emoji removed {emoji}', file=sys.stderr)
            return 1
    if '�' in emoji_text:
        print('TELEGRAM_OUTPUT_SANITIZER_FAIL: replacement char survived emoji case', file=sys.stderr)
        return 1

    from backend.telegram.telegram_analysis_bot import send_analysis_message

    dry = send_analysis_message('LIVE: active_book 26 · live_session_pending 18 �� resolved today 0', dry_run=True)
    final_text = dry.get('text') or ''
    if '�' in final_text or '��' in final_text:
        print(f'TELEGRAM_OUTPUT_SANITIZER_FAIL: final send kept replacement marker: {final_text!r}', file=sys.stderr)
        return 1
    if '18 · resolved today 0' not in final_text:
        print(f'TELEGRAM_OUTPUT_SANITIZER_FAIL: final send did not repair separator: {final_text!r}', file=sys.stderr)
        return 1

    print('TELEGRAM_OUTPUT_SANITIZER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
