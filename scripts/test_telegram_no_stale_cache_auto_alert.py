#!/usr/bin/env python3
"""Ensure scheduler never auto-sends stale-cache macro research text (Stage 48G)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_NO_STALE_CACHE_AUTO_ALERT_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _fake_load(path):
    if 'govt' in str(path):
        return {
            'high_impact_items': [{
                'impact_score': 9.5,
                'english_headline': 'RBI probe sparks banking sector selloff',
                'title': 'RBI probe',
                'cache_stale': True,
            }],
        }
    if 'news' in str(path):
        return {'articles': []}
    return {}


def main() -> int:
    from backend.orchestration import telegram_alert_engine as engine
    from backend.orchestration import alert_scheduler as sched

    stale_text = 'Macro research only — stale cache'

    with patch('backend.orchestration.alert_freshness_gate.is_headline_source_stale', return_value=False):
        with patch.object(engine, 'is_silenced', return_value=False):
            with patch.object(engine, '_load', side_effect=_fake_load):
                with patch.object(engine, '_send', return_value={'sent': True, 'ok': True}) as send_mock:
                    sent, skipped = engine.try_emergency_macro(scheduled=True)

    if send_mock.called:
        body = send_mock.call_args[0][0]
        if stale_text in body:
            return _fail('scheduler must not auto-send stale cache research text')

    if sent:
        return _fail('cache_stale scheduled macro must not send')
    if not skipped:
        return _fail('cache_stale scheduled macro should be skipped')

    sched_src = (PROJECT_ROOT / 'backend/orchestration/alert_scheduler.py').read_text(encoding='utf-8')
    if 'try_emergency_macro()' not in sched_src:
        return _fail('alert_scheduler should call try_emergency_macro() with scheduled default')

    print('TELEGRAM_NO_STALE_CACHE_AUTO_ALERT_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
