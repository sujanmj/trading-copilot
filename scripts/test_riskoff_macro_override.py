#!/usr/bin/env python3
"""Unit tests for risk-off macro override with stale data (Stage 47D)."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = ZoneInfo('Asia/Kolkata')
PREOPEN = datetime(2026, 6, 8, 8, 15, tzinfo=IST)


def _fail(msg: str) -> int:
    print(f'RISKOFF_MACRO_OVERRIDE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_freshness_gate import (
        PREMARKET_RISKOFF_HEADER,
        apply_hard_stale_lock_to_setups,
        is_headline_source_stale,
        is_riskoff_macro_before_open,
        premarket_hard_stale_lock,
    )
    from backend.analytics.premarket_conviction import format_premarket_telegram
    from backend.orchestration import telegram_alert_engine as engine

    crash_global = {
        'sentiment': {
            'asia': {'mood': 'BEARISH', 'average_change': -2.1},
            'global': {'mood': 'BEARISH', 'average_change': -1.5},
        },
    }
    if not is_riskoff_macro_before_open(crash_global, now=PREOPEN):
        return _fail('Asia/global crash should trigger risk-off before open')
    if is_riskoff_macro_before_open(crash_global, now=datetime(2026, 6, 8, 10, 0, tzinfo=IST)):
        return _fail('risk-off check should not apply after 09:15')

    with patch('backend.orchestration.alert_freshness_gate.is_premarket_hard_stale_window', return_value=True):
        with patch('backend.orchestration.alert_freshness_gate._collect_premarket_stale_keys', return_value=['scanner']):
            with patch('backend.orchestration.alert_freshness_gate.is_riskoff_macro_before_open', return_value=True):
                locked, _header, _keys, riskoff = premarket_hard_stale_lock(now=PREOPEN)
    if not locked or not riskoff:
        return _fail('stale data + risk-off should lock premarket')

    setups = [{'ticker': 'BULL', 'setup': 'BULLISH scanner signal', 'score': 88, 'is_current_trading_session': True}]
    _live, prev = apply_hard_stale_lock_to_setups(setups, locked=True, riskoff=True)
    if any(int(r.get('score', 0)) > 50 for r in prev):
        return _fail('risk-off must cap bullish stale picks to <= 50')

    report = {
        'market_bias': 'Risk-off',
        'top_setups': [],
        'previous_session_movers': prev,
        'avoid': [],
        'market_mode': {'market_mode': 'INDIA_PREMARKET_MODE'},
        'freshness_ok': False,
        'freshness_header': '⚠️ DATA REFRESH INCOMPLETE — NO LIVE SETUPS',
        'hard_stale_lock': True,
        'riskoff_premarket': True,
        'sector_cues': {},
        'overnight_global': crash_global,
    }
    text = format_premarket_telegram(full=False, report=report)
    if PREMARKET_RISKOFF_HEADER not in text:
        return _fail('missing Risk-off premarket header')

    def _fake_load(path):
        if 'govt' in str(path):
            return {'high_impact_items': [{'impact_score': 9.5, 'english_headline': 'Asia markets crash on war fears', 'title': 'Asia markets crash'}]}
        if 'news' in str(path):
            return {'articles': []}
        return {}

    import io
    from contextlib import redirect_stdout

    engine._MACRO_STALE_RESEARCH_SENT.clear()

    with patch('backend.orchestration.alert_freshness_gate.is_headline_source_stale', return_value=True):
        with patch.object(engine, 'is_silenced', return_value=False):
            with patch.object(engine, '_load', side_effect=_fake_load):
                with patch.object(engine, '_send', return_value={'sent': True, 'ok': True}) as send_sched:
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        sent, skipped = engine.try_emergency_macro(scheduled=True)
                    sched_out = buf.getvalue()
    if sent:
        return _fail('scheduled stale headline must not send Emergency Macro alert')
    if not skipped:
        return _fail('scheduled stale headline should count as skipped')
    if send_sched.called:
        return _fail('scheduled stale path must not call _send')
    if 'TELEGRAM_MACRO_STALE_SUPPRESSED' not in sched_out:
        return _fail('scheduled stale path must log TELEGRAM_MACRO_STALE_SUPPRESSED')

    engine._MACRO_STALE_RESEARCH_SENT.clear()

    with patch('backend.orchestration.alert_freshness_gate.is_headline_source_stale', return_value=True):
        with patch.object(engine, 'is_silenced', return_value=False):
            with patch.object(engine, '_load', side_effect=_fake_load):
                with patch.object(engine, '_send', return_value={'sent': True, 'ok': True}) as send_manual:
                    sent_m, skipped_m = engine.try_emergency_macro(scheduled=False)
    if sent_m:
        return _fail('manual stale headline must not send Emergency Macro alert')
    if not skipped_m:
        return _fail('manual stale headline should count as skipped')
    sent_text = send_manual.call_args[0][0] if send_manual.called else ''
    if '<b>🚨 Emergency Macro</b>' in sent_text:
        return _fail('stale cache must not use Emergency Macro alert label')
    if 'Macro research only' not in sent_text:
        return _fail('manual stale cache must use Macro research only label')
    if 'not Emergency Macro' not in sent_text:
        return _fail('manual stale cache should clarify not Emergency Macro')

    print('RISKOFF_MACRO_OVERRIDE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
