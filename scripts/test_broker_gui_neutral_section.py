#!/usr/bin/env python3
"""Unit tests for broker GUI neutral section (Stage 48N)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fail(msg: str) -> int:
    print(f'BROKER_GUI_NEUTRAL_SECTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel = (PROJECT_ROOT / 'frontend/components/BrokerIntelligencePanel.js').read_text(encoding='utf-8')
    for needle in (
        'renderNeutralSection',
        'Neutral / Other Evidence',
        'renderTrackedTickerChips',
        'tracked_ticker_names',
        'bi-ticker-chip',
    ):
        if needle not in panel:
            return _fail(f'BrokerIntelligencePanel.js missing {needle!r}')

    backend = (PROJECT_ROOT / 'backend/analytics/broker_intelligence.py').read_text(encoding='utf-8')
    if 'top_neutral' not in backend:
        return _fail('backend must expose top_neutral bucket')

    print('BROKER_GUI_NEUTRAL_SECTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
