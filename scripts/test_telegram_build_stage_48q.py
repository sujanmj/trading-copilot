#!/usr/bin/env python3
"""Unit tests for Telegram build label Stage 48R."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_BUILD_STAGE_48Q_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.response_format import format_status_text
    from backend.telegram.telegram_analysis_bot import _handle_health

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 50B':
        return _fail(f'expected AstraEdge 50B got {ASTRAEDGE_TELEGRAM_BUILD!r}')

    status_text = format_status_text()
    if 'Telegram build: <code>AstraEdge 50B</code>' not in status_text:
        return _fail('/status missing AstraEdge 50B build label')

    health_text = _handle_health()
    if 'Telegram build: <code>AstraEdge 50B</code>' not in health_text:
        return _fail('/health missing AstraEdge 50B build label')

    print('TELEGRAM_BUILD_STAGE_48Q_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
