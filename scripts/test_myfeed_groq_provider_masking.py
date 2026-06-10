#!/usr/bin/env python3
"""Stage 50F — provider names must not appear in Telegram/GUI My Feed output."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_GROQ_PROVIDER_MASKING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.feed_processor import format_needs_text_reply, format_saved_reply

    banned = ('groq', 'openai', 'anthropic', 'gemini', 'llama-4', 'meta-llama')
    saved = format_saved_reply({
        'tickers': ['CHAMBLFERT'],
        'impact_score': 72,
        'suggested_action': 'WATCH FOR CONFIRMATION',
    }, items_found=2, all_entities=['IRAN', 'CHAMBLFERT'], ticker_list=['CHAMBLFERT'])
    needs = format_needs_text_reply()
    for text in (saved, needs):
        lower = text.lower()
        for token in banned:
            if token in lower:
                return _fail(f'provider token {token!r} leaked into user-facing reply')

    groq_src = (PROJECT_ROOT / 'backend/my_feed/groq_vision_fallback.py').read_text(encoding='utf-8').lower()
    if 'my_feed_saved' in groq_src or 'my_feed_needs_text' in groq_src:
        return _fail('groq module must not embed telegram reply strings with provider names')

    print('MYFEED_GROQ_PROVIDER_MASKING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
