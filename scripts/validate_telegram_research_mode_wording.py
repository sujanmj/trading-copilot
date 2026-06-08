#!/usr/bin/env python3
"""Validate stale-report research mode wording (Stage 48K)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    if 'Market state: Research mode' not in src:
        print('TELEGRAM_RESEARCH_MODE_WORDING_FAIL: missing research mode pattern', file=sys.stderr)
        return 1
    if 'Action: watch only, refresh before live entry.' not in src:
        print('TELEGRAM_RESEARCH_MODE_WORDING_FAIL: missing action line', file=sys.stderr)
        return 1
    if os.system(f'{sys.executable} scripts/test_telegram_research_mode_wording.py') != 0:
        print('TELEGRAM_RESEARCH_MODE_WORDING_FAIL: test failed', file=sys.stderr)
        return 1
    print('TELEGRAM_RESEARCH_MODE_WORDING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
