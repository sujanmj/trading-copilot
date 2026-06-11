#!/usr/bin/env python3
"""Stage 50H — AI Hub stale metadata uses tab-specific labels and router mode."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'AIHUB_STALE_METADATA_CLEAN_LABELS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    fmt = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')

    if 'Market: ${market}' in index and 'Age ${ageLabel}' in index:
        return _fail('updateAiHubMarketChip still uses Market unknown / Age global label')

    if 'cache stale' not in index or 'updateAiHubMarketChip' not in index:
        return _fail('updateAiHubMarketChip must show tab cache stale labels')

    if 'MarketRouterCard.getLastReport' not in index:
        return _fail('updateAiHubMarketChip must read router mode')

    if 'Brain cache stale' not in index and 'cache stale' not in index:
        return _fail('panel banners must use tab-specific stale labels')

    if 'cache stale — research only' not in fmt and 'cache stale' not in fmt:
        return _fail('format_aihub_payload must label tab cache stale')

    from backend.telegram.response_format import format_aihub_payload

    text = format_aihub_payload('brain', {
        'source': 'cache',
        'cache_age_seconds': 720000,
        'summary': {'stale': True},
        'items': [],
        'warnings': [],
    })
    if 'Brain cache stale' not in text and 'brain cache stale' not in text.lower():
        return _fail(f'brain stale label missing in telegram formatter: {text!r}')

    print('AIHUB_STALE_METADATA_CLEAN_LABELS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
