#!/usr/bin/env python3
"""Unit tests for broker GUI cache-first load (Stage 48L)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend/components/BrokerIntelligencePanel.js'


def _fail(msg: str) -> int:
    print(f'BROKER_GUI_CACHE_FIRST_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel = PANEL.read_text(encoding='utf-8')

    for needle in (
        'cache_only=1&lite=1',
        'Broker cache unavailable',
        'loadCacheOverview',
        'renderFreshnessSection',
        'Top Positive',
        'Top Negative',
        'Ticker Drilldown',
        'External Evidence',
        'Impact on Today / Tomorrow',
        'loadTickerDrilldown',
        '/api/brokers/ticker',
    ):
        if needle not in panel:
            return _fail(f'BrokerIntelligencePanel.js missing {needle!r}')

    if '/api/brokers/refresh' not in panel:
        return _fail('refresh endpoint missing')

    forbidden = ('Promise.all', '/api/debug/broker-intelligence')
    load_block = panel.split('async function loadMain')[1].split('function init')[0]
    for needle in forbidden:
        if needle in load_block:
            return _fail(f'mount path must not use {needle!r}')

    print('BROKER_GUI_CACHE_FIRST_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
