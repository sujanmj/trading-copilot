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
    from backend.telegram.response_format import format_status_text
    from backend.telegram.telegram_analysis_bot import _handle_health
    from scripts.test_build_helpers import (
        assert_canonical_build,
        expected_health_build_line,
    )

    err = assert_canonical_build(_fail)
    if err:
        return err

    status_text = format_status_text()
    if expected_health_build_line() not in status_text:
        return _fail(f'/status missing {expected_health_build_line()!r} build label')

    health_text = _handle_health()
    if expected_health_build_line() not in health_text:
        return _fail(f'/health missing {expected_health_build_line()!r} build label')

    print('TELEGRAM_BUILD_STAGE_48Q_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
