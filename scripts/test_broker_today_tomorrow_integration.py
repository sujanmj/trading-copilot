#!/usr/bin/env python3
"""Unit tests for broker today/tomorrow integration (Stage 48L)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BROKER_TODAY_TOMORROW_INTEGRATION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import broker_decision_bullets
    from backend.analytics.stock_decision_engine import _build_telegram_message

    sample_cache = {
        'ok': True,
        'consensus_by_ticker': {
            'RELIANCE': {
                'consensus_label': 'Positive',
                'confidence_score': 70,
                'suggested_action': 'Watch for Confirmation',
                'latest_action': 'upgrade',
            },
            'MCX': {
                'consensus_label': 'Avoid-Risk',
                'confidence_score': 15,
                'suggested_action': 'Avoid-Risk',
                'latest_action': 'downgrade',
            },
        },
    }

    with patch('backend.analytics.broker_intelligence._load_cache', return_value=sample_cache):
        support = broker_decision_bullets('RELIANCE', mode='today')
        if not support or 'supports' not in support[0].lower():
            return _fail('expected support bullet for RELIANCE')
        if 'buy' in support[0].lower() and 'confirmation' not in support[0].lower():
            return _fail('support bullet must not be buy signal')

        risk = broker_decision_bullets('MCX', mode='tomorrow')
        if not risk or 'risk' not in risk[0].lower():
            return _fail('expected risk bullet for MCX')

        msg = _build_telegram_message(
            mode='today',
            decision='WATCH_FOR_ENTRY',
            top_pick={
                'ticker': 'RELIANCE',
                'action': 'WATCH_FOR_ENTRY',
                'score': 55,
                'why': ['test reason'],
                'confirmation_needed': ['volume'],
                'risk': [],
            },
            avoid=[{'ticker': 'MCX', 'risk': ['weak signal'], 'why': []}],
        )
        if 'Broker evidence supports' not in msg:
            return _fail('today message missing broker support bullet')
        if 'Broker conflict/risk' not in msg:
            return _fail('today message missing broker risk bullet')

    sde_src = (PROJECT_ROOT / 'backend/analytics/stock_decision_engine.py').read_text(encoding='utf-8')
    if 'broker_decision_bullets' not in sde_src:
        return _fail('stock_decision_engine missing broker integration')

    print('BROKER_TODAY_TOMORROW_INTEGRATION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
