#!/usr/bin/env python3
"""Unit tests for budget catalyst direction display (Stage 48H)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import (
    detect_catalyst_direction,
    detect_catalyst_stance,
    enrich_catalyst_row,
    get_budget_overview,
)


def _fail(msg: str) -> int:
    print(f'BUDGET_CATALYST_DIRECTION_DISPLAY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    delay = 'Tata Steel UK project delayed by regulatory review'
    highway = 'Govt announces ₹11,000 crore highway project in Bengaluru'
    broad = 'Power entering a 10-year supercycle?'

    if detect_catalyst_direction(delay) != 'Negative':
        return _fail('Tata Steel delay must be Negative')
    if detect_catalyst_direction(highway) != 'Positive':
        return _fail('Highway project must be Positive')
    if detect_catalyst_direction(broad) != 'Neutral':
        return _fail('Broad supercycle headline must be Neutral')
    if detect_catalyst_stance(broad, 'Neutral') != 'Research Only':
        return _fail('Broad commentary must be Research Only')

    row = enrich_catalyst_row({'headline': delay})
    if row.get('catalyst_direction') != 'Negative':
        return _fail('enrich_catalyst_row must set direction')

    overview = get_budget_overview(cache_only=True, lite=True)
    for cat in overview.get('top_catalysts') or []:
        direction = str(cat.get('catalyst_direction') or '').strip()
        if not direction or direction == '?':
            return _fail(f'overview catalyst missing direction: {cat!r}')

    print('BUDGET_CATALYST_DIRECTION_DISPLAY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
