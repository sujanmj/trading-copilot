#!/usr/bin/env python3
"""Validate AI provider fallback pack (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'AI_PROVIDER_FALLBACK_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    mod = PROJECT_ROOT / 'backend/ai/ai_provider_fallback.py'
    if not mod.is_file():
        return _fail('missing ai_provider_fallback.py')
    src = mod.read_text(encoding='utf-8')
    for needle in ('AI_PROVIDER_FALLBACK', 'deterministic_rules', 'call_strategic_with_cascade'):
        if needle not in src:
            return _fail(f'missing {needle}')
    if os.system(f'{sys.executable} scripts/test_ai_provider_fallback.py') != 0:
        return _fail('test_ai_provider_fallback.py failed')
    print('AI_PROVIDER_FALLBACK_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
