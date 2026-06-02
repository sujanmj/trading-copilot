#!/usr/bin/env python3
"""
Test daily report pack generation with mocked component summaries.

Prints exactly DAILY_REPORT_PACK_TEST_OK on success.
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
    print(f'DAILY_REPORT_PACK_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics import daily_report_pack as pack_mod
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    if not init_market_memory_db():
        return _fail('init failed')

    stats_before = get_market_memory_stats()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        latest = tmp_path / 'daily_report_pack_latest.json'
        history = tmp_path / 'daily_report_pack_history.jsonl'
        fc_path = tmp_path / 'final_confidence_report.json'
        tw_path = tmp_path / 'tomorrow_watchlist_report.json'
        cal_path = tmp_path / 'confidence_calibration_report.json'

        fc_path.write_text(json.dumps({
            'ok': True,
            'active_mode': 'RESEARCH_MODE',
            'summary': {'checked': 3, 'watch': 1, 'avoid': 1, 'no_decision': 1, 'buy_candidate': 0},
        }), encoding='utf-8')
        tw_path.write_text(json.dumps({
            'ok': True,
            'market_mode': 'RESEARCH_MODE',
            'summary': {
                'watch': 1,
                'avoid': 1,
                'no_decision': 1,
                'raw_candidates': 3,
                'unique_tickers': 3,
                'duplicates_removed': 0,
            },
            'top_watchlist': [{
                'ticker': 'ALPHA',
                'score': 55,
                'decision': 'WATCH',
                'reason': 'watch candidate',
                'warnings': [],
            }],
            'risk_notes': ['Market closed'],
        }), encoding='utf-8')
        cal_path.write_text(json.dumps({
            'ok': True,
            'summary': {'live_resolved': 5},
            'recommendations': [],
            'warnings': [],
        }), encoding='utf-8')

        file_paths = {
            'final_confidence': fc_path,
            'tomorrow_watchlist': tw_path,
            'calibration': cal_path,
        }

        with patch.object(pack_mod, 'LATEST_PATH', latest), \
             patch.object(pack_mod, 'HISTORY_PATH', history), \
             patch.object(pack_mod, 'DATA_DIR', tmp_path), \
             patch.object(pack_mod, 'FILE_PATHS', file_paths), \
             patch('backend.analytics.market_calendar_router.get_market_router_payload', return_value={
                 'ok': True,
                 'active_mode': 'RESEARCH_MODE',
                 'market_closed': True,
             }), \
             patch('backend.analytics.source_freshness.get_source_freshness_report', return_value={
                 'ok': True,
                 'safe_to_use': False,
                 'warnings': ['stale_critical_sources'],
             }), \
             patch('backend.analytics.broker_prediction_intelligence.get_broker_intelligence_dashboard', return_value={
                 'ok': True,
                 'stats': {'broker_predictions': 2, 'sources': 1, 'tickers': 2},
             }), \
             patch('backend.analytics.historical_learning_engine.get_historical_learning_summary', return_value={
                 'stats': {'historical_prices': 100},
                 'overall': {'win_rate': 0.5},
                 'simulation': {},
             }), \
             patch('backend.analytics.historical_prediction_simulator.get_simulation_dashboard', return_value={
                 'simulation': {'stats': {'simulation_runs': 1, 'simulated_predictions': 10}},
             }):
            report = pack_mod.generate_daily_report_pack(refresh=False, limit=10)

        if report.get('ok') is not True:
            return _fail('pack ok != true')
        if report.get('shadow_mode') is not True:
            return _fail('shadow_mode must be true')

        blob = json.dumps(report).lower()
        for token in ('trade_execution', 'execute_trade', 'telegram_sent'):
            if token in blob:
                return _fail(f'forbidden token {token}')

        if not latest.is_file() or not history.is_file():
            return _fail('latest/history files not written')

        if len(history.read_text(encoding='utf-8').strip().splitlines()) < 1:
            return _fail('history not appended')

    stats_after = get_market_memory_stats()
    if int(stats_after.get('predictions') or 0) != int(stats_before.get('predictions') or 0):
        return _fail('canonical predictions changed')

    print('DAILY_REPORT_PACK_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
