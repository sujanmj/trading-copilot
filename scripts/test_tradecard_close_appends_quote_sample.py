#!/usr/bin/env python3
"""Stage 50Z hotfix — /close appends quote path samples for active tradecards."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
from _tradecard_journal_test_helpers import isolated_tradecard_store, sample_valid_card


def _fail(msg: str) -> int:
    print(f'TRADECARD_CLOSE_APPENDS_QUOTE_SAMPLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.trading.tradecard_journal import (
        load_path_samples,
        persist_tradecard_generation,
        sample_and_resolve_pending_tradecards,
    )

    card = sample_valid_card(ticker='ROSSARI', current_price=554.25)
    market_data = {'prices': {'ROSSARI': {'price': 555.5, 'high': 556.0, 'low': 554.0}}}

    with isolated_tradecard_store(), \
         patch('backend.trading.tradecard_journal._today', return_value='2026-06-19'):
        row = persist_tradecard_generation(card)
        if not row:
            return _fail('active ROSSARI card must persist')
        with patch('backend.trading.tradecard_refresh._run_lightweight_refresh', return_value=(True, True, ['prices'])), \
             patch('backend.storage.market_memory_outcomes.load_latest_market_data', return_value=market_data):
            summary = sample_and_resolve_pending_tradecards(refresh=True)

        if int(summary.get('sampled') or 0) < 1:
            return _fail('/close-style resolve must append quote sample')
        samples = load_path_samples(str(row.get('id')))
        if not samples:
            return _fail('path samples file must contain ROSSARI sample after close resolve')

    print('TRADECARD_CLOSE_APPENDS_QUOTE_SAMPLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
