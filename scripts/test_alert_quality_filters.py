#!/usr/bin/env python3
"""Unit tests for alert quality filters (Stage 46H)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'ALERT_QUALITY_FILTERS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.orchestration.alert_quality_filters import (
        EMERGENCY_STATE_FILE,
        adjust_open_setup_confidence,
        classify_emergency_theme,
        evaluate_emergency_macro,
        has_india_market_relevance,
        is_clickbait_headline,
        is_scheduled_rbi_mpc,
        normalize_headline,
        record_emergency_macro_sent,
    )
    from backend.orchestration.intraday_alert_state import (
        STATE_FILE as INTRADAY_STATE_FILE,
        classify_intraday_event,
        record_intraday_sent,
    )

    for path in (EMERGENCY_STATE_FILE, INTRADAY_STATE_FILE):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    signal = {
        'ticker': 'STLTECH',
        'change_percent': 5.0,
        'volume_ratio': 0.4,
        'strength': 'ULTRA',
        'direction': 'BULLISH',
        'sector': 'IT',
    }
    conf, label, watch_only, reason = adjust_open_setup_confidence(signal, 0.83, {}, {})
    if conf > 0.65:
        return _fail(f'participation 0.4x should cap confidence, got {conf}')
    if not watch_only:
        return _fail('participation <0.5 should be watch_only')
    if 'WATCH ONLY' not in label:
        return _fail('expected WATCH ONLY label')

    signal_strong = dict(signal)
    signal_strong['volume_ratio'] = 2.5
    signal_strong['signals'] = ['breakout', 'volume']
    conf2, _, watch2, _ = adjust_open_setup_confidence(signal_strong, 0.83, {'sector_rotation': {'bullish': ['IT']}}, {'disagreement_score': 0.1})
    if watch2:
        return _fail('strong participation should not be watch_only')
    if conf2 < 0.7:
        return _fail('strong participation should retain higher confidence')

    click = 'Do you own these IT stocks? What\'s behind the crash?'
    if not is_clickbait_headline(click):
        return _fail('clickbait not detected')
    ok, reason, theme = evaluate_emergency_macro(click, 0.8)
    if ok:
        return _fail('clickbait without impact should be skipped')

    headline = f'Nifty crashes 3% on FII outflow — broader market selloff {os.getpid()}'
    ok2, reason2, theme2 = evaluate_emergency_macro(headline, 0.82)
    if not ok2:
        return _fail(f'direct impact headline should pass: {reason2}')
    if theme2 != classify_emergency_theme(headline):
        return _fail('theme mismatch')

    record_emergency_macro_sent(headline, 0.82, theme2)
    ok3, reason3, _ = evaluate_emergency_macro(headline, 0.83)
    if ok3:
        return _fail('duplicate headline should dedupe within window')

    norm_a = normalize_headline('Market CRASH!!!  Sensex down')
    norm_b = normalize_headline('market crash sensex down')
    if norm_a != norm_b:
        return _fail('headline normalization failed')

    ev = {'ticker': 'BORORENEW', 'type': 'scanner_anomaly', 'detail': 'Anomaly BORORENEW +8.2%', 'signal': {'change_percent': 8.2, 'volume_ratio': 1.1}}
    cat1, _ = classify_intraday_event(ev)
    if cat1 != 'new':
        return _fail(f'first event should be new, got {cat1}')

    from backend.orchestration.intraday_alert_state import record_intraday_sent
    record_intraday_sent(ev)
    cat2, _ = classify_intraday_event(ev)
    if cat2 != 'suppressed':
        return _fail(f'repeated event should suppress, got {cat2}')

    ev_changed = dict(ev)
    ev_changed['signal'] = {'change_percent': 10.0, 'volume_ratio': 1.1}
    ev_changed['detail'] = 'Anomaly BORORENEW +10.0%'
    cat3, detail = classify_intraday_event(ev_changed)
    if cat3 != 'changed':
        return _fail(f'material price move should change, got {cat3}')

    rbi_cal = 'RBI MPC meeting on policy rates today — scheduled calendar'
    if not is_scheduled_rbi_mpc(rbi_cal):
        return _fail('scheduled RBI MPC should be detected')
    ok_rbi, reason_rbi, _ = evaluate_emergency_macro(rbi_cal, 0.9)
    if ok_rbi:
        return _fail('scheduled RBI MPC should not emergency alert')

    global_only = 'Wall Street closes higher as Dow Jones leads US rally'
    if has_india_market_relevance(global_only):
        return _fail('generic US headline should lack India relevance')
    ok_g, reason_g, _ = evaluate_emergency_macro(global_only, 0.85)
    if ok_g:
        return _fail('generic global should be skipped')

    engine_src = (PROJECT_ROOT / 'backend/orchestration/telegram_alert_engine.py').read_text(encoding='utf-8')
    if 'alert_quality_filters' not in engine_src:
        return _fail('telegram_alert_engine not wired to alert_quality_filters')
    if 'intraday_alert_state' not in engine_src:
        return _fail('telegram_alert_engine not wired to intraday_alert_state')
    if 'alert_freshness_gate' not in engine_src:
        return _fail('telegram_alert_engine not wired to alert_freshness_gate')

    print('ALERT_QUALITY_FILTERS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
