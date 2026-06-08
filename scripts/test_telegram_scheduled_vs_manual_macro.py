#!/usr/bin/env python3
"""Unit tests for scheduled vs manual stale macro behavior (Stage 48G)."""

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
    print(f'TELEGRAM_SCHEDULED_VS_MANUAL_MACRO_TEST_FAIL: {msg}', file=sys.stderr)
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

    engine._MACRO_STALE_RESEARCH_SENT.clear()

    with patch('backend.orchestration.alert_freshness_gate.is_headline_source_stale', return_value=True):
        with patch.object(engine, 'is_silenced', return_value=False):
            with patch.object(engine, '_load', side_effect=_fake_load):
                with patch.object(engine, '_send', return_value={'sent': True, 'ok': True}) as send_sched:
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        sent_s, skipped_s = engine.try_emergency_macro(scheduled=True)
                    out_s = buf.getvalue()

    if sent_s or send_sched.called:
        return _fail('scheduled=True must not send stale macro research')
    if 'TELEGRAM_MACRO_STALE_SUPPRESSED' not in out_s:
        return _fail('scheduled=True must log TELEGRAM_MACRO_STALE_SUPPRESSED')

    engine._MACRO_STALE_RESEARCH_SENT.clear()

    with patch('backend.orchestration.alert_freshness_gate.is_headline_source_stale', return_value=True):
        with patch.object(engine, 'is_silenced', return_value=False):
            with patch.object(engine, '_load', side_effect=_fake_load):
                with patch.object(engine, '_send', return_value={'sent': True, 'ok': True}) as send_manual:
                    sent_m, skipped_m = engine.try_emergency_macro(scheduled=False)

    if sent_m:
        return _fail('manual stale path must not send Emergency Macro alert')
    if not skipped_m:
        return _fail('manual stale path should count as skipped')
    if not send_manual.called:
        return _fail('manual stale path should send research-only warning')
    sent_text = send_manual.call_args[0][0]
    if 'Macro research only' not in sent_text:
        return _fail('manual stale path must use Macro research only label')
    if '<b>🚨 Emergency Macro</b>' in sent_text:
        return _fail('manual stale path must not use Emergency Macro label')

    print('TELEGRAM_SCHEDULED_VS_MANUAL_MACRO_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
