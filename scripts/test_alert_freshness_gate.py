#!/usr/bin/env python3
"""Unit tests for alert freshness gate (Stage 46H)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'ALERT_FRESHNESS_GATE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_freshness_gate import (
        WATCH_ONLY_MESSAGE,
        article_too_old_for_fresh,
        gate_alert_dispatch,
    )

    if not article_too_old_for_fresh({'published_at': '2020-01-01T00:00:00+00:00'}):
        return _fail('2+ day old article should be too old')

    with patch('backend.orchestration.alert_freshness_gate.check_core_freshness', return_value=(False, WATCH_ONLY_MESSAGE, ['news'])):
        allow, msg = gate_alert_dispatch('INTRADAY_OPPORTUNITY')
    if allow:
        return _fail('stale should block dispatch')
    if WATCH_ONLY_MESSAGE not in msg:
        return _fail('missing watch-only message')

    engine = (PROJECT_ROOT / 'backend/orchestration/telegram_alert_engine.py').read_text(encoding='utf-8')
    if 'alert_freshness_gate' not in engine:
        return _fail('telegram_alert_engine missing freshness gate')

    print('ALERT_FRESHNESS_GATE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
