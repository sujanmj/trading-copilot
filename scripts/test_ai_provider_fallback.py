#!/usr/bin/env python3
"""Unit tests for AI provider fallback cascade (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'AI_PROVIDER_FALLBACK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.ai.ai_provider_fallback import (
        is_failover_error,
        log_provider_fallback,
        log_provider_fallback_final,
        synthesize_deterministic_rules,
    )

    if not is_failover_error('HTTP 429 rate limit exceeded'):
        return _fail('429 should be failover error')
    if is_failover_error('connection reset'):
        return _fail('non-quota should not be failover-only signal alone')

    det = synthesize_deterministic_rules('test prompt', use_case='final_synthesis')
    if not det.get('success'):
        return _fail('deterministic rules should succeed')
    if 'anthropic' in det.get('text', '').lower() and 'claude' in det.get('text', '').lower():
        return _fail('deterministic text must not name providers')

    fb_src = (PROJECT_ROOT / 'backend/ai/ai_provider_fallback.py').read_text(encoding='utf-8')
    for needle in ('_invoke_claude', '_invoke_gemini', '_invoke_groq', 'log_provider_fallback_final'):
        if needle not in fb_src:
            return _fail(f'fallback module missing {needle}')
    log_provider_fallback('claude', 'gemini', 'quota_rate_limit')

    router_src = (PROJECT_ROOT / 'backend/ai/ai_router.py').read_text(encoding='utf-8')
    if 'call_strategic_with_cascade' not in router_src:
        return _fail('ai_router not wired to cascade')
    if 'AI_PROVIDER_FALLBACK' not in (PROJECT_ROOT / 'backend/ai/ai_provider_fallback.py').read_text(encoding='utf-8'):
        return _fail('missing AI_PROVIDER_FALLBACK log tag')

    log_provider_fallback_final()
    print('AI_PROVIDER_FALLBACK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
