#!/usr/bin/env python3
"""Stage 50P — /catalysts and /catalysts today share get_clean_catalyst_radar."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'CATALYSTS_AND_TODAY_SAME_CLEAN_BUILDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.intelligence import stock_catalyst_radar as scr

    if not hasattr(scr, 'get_clean_catalyst_radar'):
        return _fail('get_clean_catalyst_radar missing')

    fake_radar = {
        'ok': True,
        'priority_list': [
            {'ticker': 'GICRE', 'freshness_label': 'today', 'side': 'BEARISH', 'catalyst_type': 'OFS',
             'priority': 'HIGH', 'trade_status': 'AVOID/RISK', 'price_display': 'unavailable', 'volume_display': 'unavailable'},
            {'ticker': 'HCLTECH', 'freshness_label': 'recent', 'side': 'BULLISH', 'catalyst_type': 'AI_INVESTMENT',
             'priority': 'HIGH', 'trade_status': 'VALID ENTRY WATCH', 'price_display': '+2.0%', 'volume_display': '1.2x'},
        ],
    }
    calls: list[bool] = []

    def _track(*, today_only: bool = False):
        calls.append(today_only)
        return fake_radar if not today_only else {
            **fake_radar,
            'priority_list': [r for r in fake_radar['priority_list'] if r.get('freshness_label') == 'today'],
        }

    with patch.object(scr, 'get_clean_catalyst_radar', side_effect=_track):
        full = scr.format_catalyst_radar_telegram(today_only=False)
        today = scr.format_catalyst_radar_telegram(today_only=True)

    if calls != [False, True]:
        return _fail(f'expected get_clean_catalyst_radar(False) then True, got {calls!r}')
    if full.count('GICRE') != 1:
        return _fail(f'/catalysts must dedupe GICRE to one row, count={full.count("GICRE")}')
    if 'HCLTECH' in full and full.count('HCLTECH') != 1:
        return _fail('HCLTECH must appear once in /catalysts output')
    if 'HCLTECH' in today:
        return _fail('/catalysts today must filter to freshness_label=today only')
    if 'GICRE' not in today:
        return _fail('/catalysts today must include today-only GICRE')

    src = (PROJECT_ROOT / 'backend/intelligence/stock_catalyst_radar.py').read_text(encoding='utf-8')
    if 'build_catalyst_radar(force_refresh=today_only)' in src:
        return _fail('format_catalyst_radar_telegram must not force_refresh on today_only')

    print('CATALYSTS_AND_TODAY_SAME_CLEAN_BUILDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
