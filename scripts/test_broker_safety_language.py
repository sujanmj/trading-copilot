#!/usr/bin/env python3
"""Unit tests for broker safety language (Stage 48L)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_SAFETY_LANGUAGE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


FORBIDDEN = ('buy now', 'guaranteed', 'sure shot', 'sell now', 'invest now')
ALLOWED = (
    'Watch for Confirmation',
    'Research Only',
    'Avoid-Risk',
    'Wait',
)


def main() -> int:
    from backend.analytics.broker_intelligence import (
        ALLOWED_SUGGESTED_ACTIONS,
        FORBIDDEN_WORDS,
        format_broker_overview_telegram,
        format_broker_ticker_telegram,
        handle_broker_command,
        suggested_action_from_label,
    )

    if set(ALLOWED_SUGGESTED_ACTIONS) != set(ALLOWED):
        return _fail('allowed suggested actions mismatch')

    for word in FORBIDDEN:
        if word not in FORBIDDEN_WORDS:
            return _fail(f'missing forbidden word {word!r}')

    for label in ('Strong Positive', 'Positive', 'Neutral', 'Mixed', 'Negative', 'Avoid-Risk', 'Unknown'):
        action = suggested_action_from_label(label, 50)
        if action not in ALLOWED:
            return _fail(f'invalid suggested action {action!r}')
        if 'buy' in action.lower() and 'confirmation' not in action.lower():
            return _fail(f'action looks like buy signal: {action}')

    for fn in (format_broker_overview_telegram, lambda: format_broker_ticker_telegram('RELIANCE'), lambda: handle_broker_command('')):
        text = fn().lower()
        for bad in FORBIDDEN:
            if bad in text:
                return _fail(f'forbidden phrase {bad!r} in telegram output')

    bi_src = (PROJECT_ROOT / 'backend/analytics/broker_intelligence.py').read_text(encoding='utf-8')
    panel_src = (PROJECT_ROOT / 'frontend/components/BrokerIntelligencePanel.js').read_text(encoding='utf-8')
    if 'not our final prediction' not in bi_src.lower():
        return _fail('disclaimer missing in broker_intelligence')
    if 'not a trade signal' not in panel_src.lower() and 'not our final prediction' not in panel_src.lower():
        return _fail('GUI safety wording missing')

    print('BROKER_SAFETY_LANGUAGE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
