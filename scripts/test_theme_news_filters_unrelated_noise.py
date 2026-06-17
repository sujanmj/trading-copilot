#!/usr/bin/env python3
"""Stage 50U — infrastructure theme news filters unrelated headline noise."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

NOISE_HEADLINES = (
    'India may ban Telegram app over security concerns',
    'NEET exam row sparks political debate',
    'SpaceX launches new satellite constellation',
)


def _fail(msg: str) -> int:
    print(f'THEME_NEWS_FILTERS_UNRELATED_NOISE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.theme_baskets import (
        NO_CATALYST_MESSAGE,
        format_theme_news_telegram,
        is_theme_catalyst_relevant,
    )

    for headline in NOISE_HEADLINES:
        if is_theme_catalyst_relevant(headline, 'infrastructure'):
            return _fail(f'noise headline must not match infrastructure: {headline!r}')

    good = 'NHAI awards Rs 2,400 crore highway EPC contract for expressway expansion'
    if not is_theme_catalyst_relevant(good, 'infrastructure'):
        return _fail('valid infra headline should remain relevant')

    cache_rows = [
        {'theme_id': 'infrastructure', 'headline': NOISE_HEADLINES[0], 'impact_10': 4, 'catalyst_score': 40, 'action': 'watch only', 'why': 'noise', 'relevant': True},
        {'theme_id': 'infrastructure', 'headline': good, 'impact_10': 8, 'catalyst_score': 82, 'action': 'watch only', 'why': 'highway capex', 'relevant': True},
    ]

    with patch('backend.analytics.theme_baskets.load_theme_baskets', return_value={
        'baskets': [{'theme_id': 'infrastructure', 'display_name': 'Infrastructure', 'stocks': {'direct': ['LT']}}],
        'catalyst_cache': {'infrastructure': cache_rows},
    }), patch('backend.analytics.theme_baskets.get_basket_by_id', return_value={
        'theme_id': 'infrastructure',
        'display_name': 'Infrastructure',
        'stocks': {'direct': ['LT']},
    }), patch('backend.analytics.theme_baskets.resolve_theme_id', return_value='infrastructure'):
        text = format_theme_news_telegram('infrastructure')

    if 'Telegram' in text or 'NEET' in text or 'SpaceX' in text:
        return _fail('theme news output must filter unrelated noise headlines')
    if good[:40] not in text and NO_CATALYST_MESSAGE not in text:
        return _fail('theme news should show valid infra headline or no-catalyst message')

    print('THEME_NEWS_FILTERS_UNRELATED_NOISE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
