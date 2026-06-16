#!/usr/bin/env python3
"""Stage 50N — company name to NSE ticker mapping."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'STOCK_CATALYST_TICKER_MAPPING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence.stock_catalyst_radar import resolve_tickers_from_text

    cases = {
        'General Insurance Corporation of India plans OFS': 'GICRE',
        'Arvind SmartSpaces launches township project': 'ARVSMART',
        'GMR Airports traffic rises after rating upgrade': 'GMRAIRPORT',
        'HCL Technologies invests in AI venture': 'HCLTECH',
        'Suzlon Energy block deal on NSE': 'SUZLON',
        'Dr Lal Pathlabs expands network': 'LALPATHLAB',
        'MTAR Technologies wins defence order': 'MTARTECH',
    }
    for text, expected in cases.items():
        tickers = resolve_tickers_from_text(text, known=frozenset({expected, 'MARKET', 'NEWS'}))
        if expected not in tickers:
            return _fail(f'{expected} not resolved from {text!r} got {tickers}')

    false_pos = resolve_tickers_from_text('Market falls below key support today', known=frozenset({'MARKET'}))
    if 'BELOW' in false_pos or 'TODAY' in false_pos:
        return _fail(f'common words must not become tickers: {false_pos}')

    print('STOCK_CATALYST_TICKER_MAPPING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
