#!/usr/bin/env python3
"""Unit tests for macro stale research dedupe/throttle (Stage 47F)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'MACRO_STALE_DEDUPE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.orchestration.telegram_alert_engine as engine

    engine._MACRO_STALE_RESEARCH_SENT.clear()
    headline = 'RBI probe into bank fraud sparks market selloff'

    if not engine._should_send_macro_stale_research(headline):
        return _fail('first stale macro research should be allowed')
    if engine._should_send_macro_stale_research(headline):
        return _fail('duplicate stale macro research should be suppressed within 90 minutes')

    print('MACRO_STALE_DEDUPE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
