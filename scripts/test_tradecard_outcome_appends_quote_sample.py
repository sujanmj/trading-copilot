#!/usr/bin/env python3
"""Stage 50Z hotfix — /tradecard outcome appends quote path samples."""

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
    print(f'TRADECARD_OUTCOME_APPENDS_QUOTE_SAMPLE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.trading.tradecard_journal import load_path_samples, persist_tradecard_generation

    card = sample_valid_card(
        ticker='ROSSARI',
        current_price=554.25,
        entry_zone='553.00–556.00',
        stop_loss=550.0,
        target_1=560.0,
        target_2=565.0,
    )
    market_data = {
        'prices': {
            'ROSSARI': {
                'price': 556.2,
                'high': 557.0,
                'low': 555.0,
                'volume': 120000,
            },
        },
    }

    with isolated_tradecard_store(), \
         patch('backend.trading.tradecard_journal._today', return_value='2026-06-19'):
        row = persist_tradecard_generation(card)
        if not row:
            return _fail('ROSSARI VALID_ENTRY must persist')
        with patch('backend.trading.tradecard_refresh._run_lightweight_refresh', return_value=(True, True, ['prices'])), \
             patch('backend.storage.market_memory_outcomes.load_latest_market_data', return_value=market_data):
            result = run_tradecard_only('outcome', chat_id='path-sample-outcome')

        samples = load_path_samples(str(row.get('id')))
        if not samples:
            return _fail('outcome check must append at least one path sample')
        if samples[0].get('source') != 'quote_refresh':
            return _fail('path sample must record quote_refresh source')

        text = str(result.get('text') or '')
        if 'ROSSARI' not in text:
            return _fail('outcome text must include ROSSARI')
        if 'no after-signal path' in text:
            return _fail('outcome must not say no after-signal path when sample exists')
        if 'Path:' not in text:
            return _fail('outcome must include Path line when sample exists')
        if '554.25' not in text or '556.2' in text or '556.20' in text:
            pass
        else:
            return _fail('Path line must reference signal and latest prices')

    print('TRADECARD_OUTCOME_APPENDS_QUOTE_SAMPLE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
