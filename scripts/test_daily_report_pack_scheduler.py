#!/usr/bin/env python3
"""
Test daily report pack scheduler — local guard, dry-run, writes, safety.

Prints exactly DAILY_REPORT_PACK_SCHEDULER_TEST_OK on success.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

DATA_DIR = PROJECT_ROOT / 'data'
LATEST = DATA_DIR / 'daily_report_pack_latest.json'
HISTORY = DATA_DIR / 'daily_report_pack_history.jsonl'
STATE = DATA_DIR / 'daily_report_pack_job_state.json'


def _fail(msg: str) -> int:
    print(f'DAILY_REPORT_PACK_SCHEDULER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _apply_local_defaults() -> None:
    for key, val in {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
    }.items():
        os.environ[key] = val


def _mtime(path: Path) -> float | None:
    return path.stat().st_mtime if path.is_file() else None


def main() -> int:
    _apply_local_defaults()

    from backend.scheduler import daily_report_pack_job as job_mod
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    if not init_market_memory_db():
        return _fail('market memory init failed')

    stats_before = get_market_memory_stats()

    with patch.object(job_mod, 'LOCAL_ONLY', False), patch.object(job_mod, 'IS_LOCAL_DEV', False), \
         patch.dict(os.environ, {'LOCAL_ONLY': '', 'LOCAL_DEV_MODE': ''}, clear=False):
        blocked = job_mod.run_daily_report_pack_job('premarket')
    if blocked.get('ok') is not False:
        return _fail('local guard should return ok=false')
    if not any('LOCAL_ONLY' in w for w in (blocked.get('warnings') or [])):
        return _fail('local guard warning missing')

    latest_before = _mtime(LATEST)
    history_before = _mtime(HISTORY)
    state_before = _mtime(STATE)

    dry = job_mod.run_daily_report_pack_job('research', dry_run=True)
    if dry.get('generated') is not False:
        return _fail('dry_run should not generate')
    if dry.get('ok') is not True:
        return _fail('dry_run ok != true')

    if _mtime(LATEST) != latest_before or _mtime(HISTORY) != history_before:
        return _fail('dry_run modified pack files')

    telegram_calls: list[str] = []

    def _telegram_stub(*_a, **_k):
        telegram_calls.append('called')
        return None

    router_stub = {
        'ok': True,
        'active_mode': 'RESEARCH_MODE',
        'india': {'session': 'closed'},
        'usa': {'session': 'closed'},
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        latest = tmp_path / 'daily_report_pack_latest.json'
        history = tmp_path / 'daily_report_pack_history.jsonl'
        state = tmp_path / 'daily_report_pack_job_state.json'
        fc = tmp_path / 'final_confidence_report.json'
        tw = tmp_path / 'tomorrow_watchlist_report.json'
        cal = tmp_path / 'confidence_calibration_report.json'

        fc.write_text(json.dumps({
            'ok': True,
            'active_mode': 'RESEARCH_MODE',
            'summary': {'checked': 1, 'watch': 0, 'avoid': 0, 'no_decision': 1, 'buy_candidate': 0},
        }), encoding='utf-8')
        tw.write_text(json.dumps({
            'ok': True,
            'market_mode': 'RESEARCH_MODE',
            'summary': {
                'watch': 0,
                'avoid': 0,
                'no_decision': 1,
                'raw_candidates': 1,
                'unique_tickers': 1,
                'duplicates_removed': 0,
            },
            'top_watchlist': [],
            'risk_notes': [],
        }), encoding='utf-8')
        cal.write_text(json.dumps({'ok': True, 'summary': {}, 'recommendations': [], 'warnings': []}), encoding='utf-8')

        file_paths = {
            'final_confidence': fc,
            'tomorrow_watchlist': tw,
            'calibration': cal,
        }

        import backend.analytics.daily_report_pack as pack_mod

        with patch.object(job_mod, 'STATE_PATH', state), \
             patch.object(job_mod, '_research_already_ran_today', return_value=False), \
             patch.object(job_mod, '_market_closed_or_research', return_value=True), \
             patch('backend.analytics.market_calendar_router.get_market_router_payload', return_value=router_stub), \
             patch.object(job_mod, '_refresh_components', return_value={
                 'final_confidence': 'ok',
                 'tomorrow_watchlist': 'ok',
                 'calibration': 'skipped',
             }), \
             patch.object(pack_mod, 'LATEST_PATH', latest), \
             patch.object(pack_mod, 'HISTORY_PATH', history), \
             patch.object(pack_mod, 'DATA_DIR', tmp_path), \
             patch.object(pack_mod, 'FILE_PATHS', file_paths), \
             patch('backend.analytics.source_freshness.get_source_freshness_report', return_value={'ok': True}), \
             patch('backend.analytics.broker_prediction_intelligence.get_broker_intelligence_dashboard', return_value={
                 'ok': True,
                 'stats': {},
             }), \
             patch('backend.analytics.historical_learning_engine.get_historical_learning_summary', return_value={
                 'stats': {},
                 'overall': {},
                 'simulation': {},
             }), \
             patch('backend.analytics.historical_prediction_simulator.get_simulation_dashboard', return_value={
                 'simulation': {'stats': {}},
             }), \
             patch('backend.utils.telegram_bot.send_message', _telegram_stub), \
             patch('backend.orchestration.telegram_brain_pusher.send_message', _telegram_stub):
            live = job_mod.run_daily_report_pack_job('research', dry_run=False, limit=5)

        if live.get('generated') is not True:
            return _fail('research job should generate pack')
        if not latest.is_file():
            return _fail('latest pack not written')

    if telegram_calls:
        return _fail('telegram send was invoked')

    stats_after = get_market_memory_stats()
    if int(stats_after.get('predictions') or 0) != int(stats_before.get('predictions') or 0):
        return _fail('canonical predictions changed')
    if int(stats_after.get('outcomes') or 0) != int(stats_before.get('outcomes') or 0):
        return _fail('canonical outcomes changed')

    if _mtime(STATE) == state_before and state_before is not None:
        pass  # state may update in tmp only due to patch

    print('DAILY_REPORT_PACK_SCHEDULER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
