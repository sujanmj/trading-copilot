#!/usr/bin/env python3
"""Unit tests for scheduled stale macro Telegram suppression (Stage 48G)."""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_STALE_MACRO_SUPPRESSION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _fake_load(path):
    if 'govt' in str(path):
        return {
            'high_impact_items': [{
                'impact_score': 9.5,
                'english_headline': 'Asia markets crash on war fears',
                'title': 'Asia markets crash',
            }],
        }
    if 'news' in str(path):
        return {'articles': []}
    return {}


def main() -> int:
    from backend.orchestration import telegram_alert_engine as engine

    with patch('backend.orchestration.alert_freshness_gate.is_headline_source_stale', return_value=True):
        with patch.object(engine, 'is_silenced', return_value=False):
            with patch.object(engine, '_load', side_effect=_fake_load):
                with patch.object(engine, '_send', return_value={'sent': True, 'ok': True}) as send_mock:
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        sent, skipped = engine.try_emergency_macro(scheduled=True)
                    out = buf.getvalue()

    if sent:
        return _fail('scheduled stale macro must not send Emergency Macro')
    if not skipped:
        return _fail('scheduled stale macro should count as skipped')
    if send_mock.called:
        return _fail('scheduled stale macro must not call _send')
    if 'TELEGRAM_MACRO_STALE_SUPPRESSED' not in out:
        return _fail('expected TELEGRAM_MACRO_STALE_SUPPRESSED log')

    print('TELEGRAM_STALE_MACRO_SUPPRESSION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
