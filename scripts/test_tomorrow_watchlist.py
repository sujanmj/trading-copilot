#!/usr/bin/env python3
"""
Test tomorrow watchlist generation with mock final confidence data.

Prints exactly TOMORROW_WATCHLIST_TEST_OK on success.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TOMORROW_WATCHLIST_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _mock_confidence_report() -> dict:
    return {
        'ok': True,
        'shadow_mode': True,
        'active_mode': 'RESEARCH_MODE',
        'market_closed': True,
        'buy_cap_active': True,
        'rows': [
            {
                'ticker': 'ALPHA',
                'prediction_id': 'test:alpha',
                'final_score': 62,
                'decision': 'BUY_CANDIDATE',
                'confidence_label': 'HIGH',
                'warnings': ['market_closed'],
                'hard_warnings': [],
                'explanations': ['A: memory => +5', 'B: broker consensus => +3', 'H: simulation => +2'],
                'historical_simulation': {'inferred_strategy': 'momentum_breakout_20', 'confidence_adjustment': 2},
            },
            {
                'ticker': 'BETA',
                'prediction_id': 'test:beta',
                'final_score': 55,
                'decision': 'WATCH',
                'confidence_label': 'MEDIUM',
                'warnings': ['low_sample_size'],
                'hard_warnings': [],
                'explanations': ['A: memory advisor neutral => +0', 'D: historical replay n=3 => +0'],
            },
            {
                'ticker': 'GAMMA',
                'prediction_id': 'test:gamma',
                'final_score': 28,
                'decision': 'AVOID',
                'confidence_label': 'LOW',
                'warnings': ['suspicious_price_scale', 'broker_intelligence_conflict'],
                'hard_warnings': ['suspicious_price_scale'],
                'explanations': ['G: price sanity => -12'],
            },
            {
                'ticker': 'DELTA',
                'prediction_id': 'test:delta',
                'final_score': 40,
                'decision': 'NO_DECISION',
                'confidence_label': None,
                'warnings': ['insufficient_evidence'],
                'hard_warnings': ['insufficient_evidence'],
                'explanations': [],
            },
        ],
    }


def main() -> int:
    from backend.analytics import tomorrow_watchlist_report as tw_mod
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init_market_memory_db failed')

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)
    outcomes_before = int(stats_before.get('outcomes') or 0)

    mock_report = _mock_confidence_report()
    mock_mode = {
        'active_mode': 'RESEARCH_MODE',
        'active_mode_label': 'Research mode',
        'india_session': 'closed',
        'usa_session': 'closed',
        'market_closed': True,
        'buy_cap_active': True,
        'next_india_open': {'next_open_local': '2026-06-02T09:15:00+05:30'},
        'next_usa_open': {'next_open_local': '2026-06-02T09:30:00-04:00'},
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out_path = tmp_path / 'tomorrow_watchlist_report.json'

        with patch.object(tw_mod, 'load_final_confidence_report', return_value=mock_report), \
             patch.object(tw_mod, '_market_mode_summary', return_value=mock_mode), \
             patch.object(tw_mod, 'TOMORROW_WATCHLIST_PATH', out_path):
            report = tw_mod.write_tomorrow_watchlist_report(limit=10)

    if report.get('ok') is not True:
        return _fail('generate failed')

    summary = report.get('summary') or {}
    if int(summary.get('buy_candidates') or 0) != 0:
        return _fail('RESEARCH_MODE must block buy_candidates in summary')

    top = report.get('top_watchlist') or []
    if not top:
        return _fail('expected top_watchlist entries')
    if any(str(item.get('decision') or '') == 'BUY_CANDIDATE' for item in top):
        return _fail('BUY_CANDIDATE must not appear in top watchlist during RESEARCH_MODE')

    beta = next((item for item in top if item.get('ticker') == 'BETA'), None)
    if not beta or not beta.get('reason'):
        return _fail('WATCH candidate missing reason')

    avoid = report.get('avoid') or []
    gamma = next((item for item in avoid if item.get('ticker') == 'GAMMA'), None)
    if not gamma or 'suspicious_price_scale' not in (gamma.get('warnings') or []):
        return _fail('AVOID candidate missing blocking warnings')

    no_dec = report.get('no_decision') or []
    if not any(item.get('ticker') == 'DELTA' for item in no_dec):
        return _fail('NO_DECISION candidate missing')

    for forbidden in ('trade_execution', 'execute_trade', 'order_placed'):
        blob = json.dumps(report).lower()
        if forbidden in blob:
            return _fail(f'forbidden field {forbidden}')

    stats_after = get_market_memory_stats()
    if int(stats_after.get('predictions') or 0) != preds_before:
        return _fail('canonical predictions changed')
    if int(stats_after.get('outcomes') or 0) != outcomes_before:
        return _fail('canonical outcomes changed')

    if report.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')

    print('TOMORROW_WATCHLIST_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
