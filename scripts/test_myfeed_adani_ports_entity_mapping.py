#!/usr/bin/env python3
"""Stage 50Y — Adani Ports capex maps to ADANIPORTS only."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'MYFEED_ADANI_PORTS_ENTITY_MAPPING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.my_feed.feed_verification import normalize_claim

    claim = normalize_claim(
        'Adani Ports to invest $850 million in AI, technology upgrades and cargo capacity expansion'
    )
    tickers = [str(t).upper() for t in (claim.get('tickers') or [])]
    if tickers != ['ADANIPORTS']:
        return _fail(f'expected [ADANIPORTS], got {tickers!r}')
    for bad in ('PARAS', 'PTC', 'IOB', 'KEI', 'IDEA', 'CHINA'):
        if bad in tickers:
            return _fail(f'must not map Adani Ports news to {bad}')
    if 'Adani Ports' not in str(claim.get('entity') or ''):
        return _fail('entity must reference Adani Ports')

    print('MYFEED_ADANI_PORTS_ENTITY_MAPPING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
