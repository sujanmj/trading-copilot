#!/usr/bin/env python3
"""Unit tests ensuring GUI boot avoids heavy refresh (Stage 48C)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fail(msg: str) -> int:
    print(f'FRONTEND_BOOT_NO_HEAVY_REFRESH_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    idx = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    rm = (PROJECT_ROOT / 'frontend/runtime/runtimeManager.js').read_text(encoding='utf-8')

    if '?refresh=1&_ts=' in idx and '/api/debug/aihub-tab/' in idx:
        return _fail('frontend must not auto GET aihub-tab refresh=1 on boot')
    if 'Runtime snapshot unavailable — using cached shell.' not in rm:
        return _fail('runtimeManager missing chunked/fetch failure message')
    if 'snapshotRetryDelay' not in rm:
        return _fail('runtimeManager missing exponential backoff helper')
    if 'loadAihubTabDataLegacyBatch' in idx.split('loadAihubTabData')[1][:2500]:
        return _fail('tab load still references legacy batch in hot path')

    broker_panel = (PROJECT_ROOT / 'frontend/components/BrokerIntelligencePanel.js').read_text(encoding='utf-8')
    if 'cache_only=1&lite=1' not in broker_panel:
        return _fail('BrokerIntelligencePanel must use cache-only lite overview on mount')
    if '/api/debug/broker-intelligence' in broker_panel.split('async function loadMain')[1].split('function init')[0]:
        return _fail('Broker tab mount must not call debug broker-intelligence endpoint')

    print('FRONTEND_BOOT_NO_HEAVY_REFRESH_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
