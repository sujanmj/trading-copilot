#!/usr/bin/env python3
"""Phase 4B.18B — opening workflow accounting and EOD consistency."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')
SESSION_DATE = '2026-07-07'


def _fail(msg: str) -> int:
    print(f'OPENING_WORKFLOW_ACCOUNTING_4B18B_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 7, hour, minute, tzinfo=IST)


@contextmanager
def _isolated_accounting(tmp_root: Path):
    memory_file = tmp_root / 'tradecard_memory.jsonl'
    journal_file = tmp_root / 'tradecard_journal.jsonl'
    alert_log = tmp_root / 'alert_event_log.jsonl'
    summary_dir = tmp_root / 'opening_workflow'
    summary_dir.mkdir(parents=True, exist_ok=True)

    with patch.dict(os.environ, {
        'TRADECARD_MEMORY_FILE': str(memory_file),
        'TRADECARD_JOURNAL_FILE': str(journal_file),
    }), patch('backend.trading.tradecard_journal.JOURNAL_FILE', journal_file), \
         patch('backend.trading.tradecard_journal._today', return_value=SESSION_DATE), \
         patch('backend.trading.opening_workflow_accounting.SUMMARY_DIR', summary_dir), \
         patch('backend.orchestration.alert_event_log.ALERT_LOG_FILE', alert_log):
        yield {
            'memory_file': memory_file,
            'journal_file': journal_file,
            'alert_log': alert_log,
            'summary_dir': summary_dir,
        }


def _fake_board() -> dict:
    return {
        'session_date': SESSION_DATE,
        'generated_at': '2026-07-07T09:25:00+05:30',
        'time_ist': '09:25',
        'ranked_candidates': [
            {
                'ticker': 'BEL',
                'state': 'TRADECARD_CANDIDATE',
                'score': 92,
                'why': ['fresh order win', 'defence theme'],
                'has_catalyst': True,
                'scanner_row': {'price': 285.0, 'open_price': 278.0, 'vwap': 280.0},
            },
            {
                'ticker': 'METROPOLIS',
                'state': 'VOLUME_IGNITION',
                'score': 88,
                'why': ['volume 2.4x'],
                'has_catalyst': False,
                'themes': ['healthcare'],
                'scanner_row': {'price': 1850.0, 'open_price': 1820.0, 'vwap': 1835.0},
            },
        ],
    }


def test_scheduled_early_persists_ranked_candidates() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_accounting(Path(tmp)) as paths:
            from backend.trading.opening_workflow_accounting import record_scheduled_early_tradecards
            from backend.trading.tradecard_memory import load_tradecard_memory

            board = _fake_board()
            record_scheduled_early_tradecards(
                board,
                best_sym='BEL',
                candidates=board['ranked_candidates'],
                timestamp='2026-07-07T09:25:00+05:30',
            )
            rows = load_tradecard_memory(limit=20)
            if len(rows) < 2:
                return _fail(f'expected >=2 memory rows, got {len(rows)}')
            sources = {str(r.get('command_source') or '') for r in rows}
            if 'scheduled_early_tradecards' not in sources:
                return _fail(f'missing scheduled_early_tradecards source in {sources!r}')
            summary_path = paths['summary_dir'] / f'{SESSION_DATE}.json'
            if not summary_path.is_file():
                return _fail('opening workflow summary missing after early tradecards')
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            if summary.get('best_provisional_pick') != 'BEL':
                return _fail(f'expected best_provisional_pick BEL got {summary!r}')
    return 0


def test_scheduled_final_persists_best_pick() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_accounting(Path(tmp)):
            from backend.trading.opening_workflow_accounting import record_scheduled_final_confirmation
            from backend.trading.tradecard_memory import load_tradecard_memory

            board = _fake_board()
            bel = board['ranked_candidates'][0]
            record_scheduled_final_confirmation(
                board,
                best_sym='BEL',
                best_row=bel,
                confirm_state='CONFIRMED',
                timestamp='2026-07-07T09:31:00+05:30',
                now=_dt(9, 31),
            )
            rows = load_tradecard_memory(symbol='BEL', limit=5)
            if not rows:
                return _fail('final confirmation must persist tradecard memory for BEL')
            if rows[0].get('command_source') != 'scheduled_final_opening_confirmation':
                return _fail(f'unexpected source {rows[0].get("command_source")!r}')
    return 0


def test_final_confirmed_increments_daily_review_confirmed() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_accounting(Path(tmp)):
            from backend.analytics.eod_outcome_scoring import summarize_alert_review_tracking
            from backend.trading.opening_workflow_accounting import record_scheduled_final_confirmation

            board = _fake_board()
            bel = board['ranked_candidates'][0]
            record_scheduled_final_confirmation(
                board,
                best_sym='BEL',
                best_row=bel,
                confirm_state='CONFIRMED',
                timestamp='2026-07-07T09:31:00+05:30',
                now=_dt(9, 31),
            )
            tracking = summarize_alert_review_tracking(SESSION_DATE)
            if int(tracking.get('confirmed_count') or 0) < 1:
                return _fail(f'expected confirmed_count >=1 got {tracking!r}')
    return 0


def test_daily_review_tradecards_generated_not_zero() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_accounting(Path(tmp)):
            from backend.orchestration.alert_quality_engine import daily_review_quality_buckets
            from backend.trading.opening_workflow_accounting import (
                record_scheduled_early_tradecards,
                record_scheduled_final_confirmation,
            )

            board = _fake_board()
            record_scheduled_early_tradecards(
                board,
                best_sym='BEL',
                candidates=board['ranked_candidates'],
                timestamp='2026-07-07T09:25:00+05:30',
            )
            record_scheduled_final_confirmation(
                board,
                best_sym='BEL',
                best_row=board['ranked_candidates'][0],
                confirm_state='CONFIRMED',
                timestamp='2026-07-07T09:31:00+05:30',
                now=_dt(9, 31),
            )
            with patch('backend.orchestration.alert_quality_engine.datetime') as mock_dt:
                mock_dt.now.return_value = _dt(12, 0)
                buckets = daily_review_quality_buckets()
            if int(buckets.get('tradecards_generated') or 0) < 1:
                return _fail(f'expected tradecards_generated >=1 got {buckets!r}')
            opening = buckets.get('opening_workflow') or {}
            if int(opening.get('early_tradecards_generated') or 0) < 1:
                return _fail('expected early_tradecards_generated >=1')
            if int(opening.get('final_confirmation_generated') or 0) < 1:
                return _fail('expected final_confirmation_generated >=1')
            if int(opening.get('confirmed') or 0) < 1:
                return _fail('expected opening confirmed >=1')
    return 0


def test_intraday_batch_counts_three_alerts() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        with _isolated_accounting(Path(tmp)):
            from backend.analytics.eod_outcome_scoring import summarize_alert_review_tracking
            from backend.orchestration.alert_event_log import log_intraday_batch_ticker_events

            events = [
                {'ticker': 'TRENT', 'confidence': 0.8, 'detail': 'breakout', 'signal': {'price': 5100}},
                {'ticker': 'MCX', 'confidence': 0.75, 'detail': 'volume spike', 'signal': {'price': 2100}},
                {'ticker': 'RADICO', 'confidence': 0.7, 'detail': 'momentum', 'signal': {'price': 2800}},
            ]
            batch_ts = f'{SESSION_DATE}T10:15:00+05:30'
            log_intraday_batch_ticker_events(events, regime='trending_day', timestamp=batch_ts)
            tracking = summarize_alert_review_tracking(SESSION_DATE)
            if int(tracking.get('intraday_alert_count') or 0) != 3:
                return _fail(f'expected 3 intraday alerts got {tracking!r}')
    return 0


def test_cap_bucket_resolves_bel() -> int:
    from backend.trading.all_cap_gainers import resolve_cap_bucket_for_symbol

    bucket = resolve_cap_bucket_for_symbol('BEL', {})
    if bucket != 'large cap':
        return _fail(f'expected BEL large cap got {bucket!r}')
    return 0


def test_cap_bucket_resolves_metropolis() -> int:
    from backend.trading.all_cap_gainers import resolve_cap_bucket_for_symbol

    bucket = resolve_cap_bucket_for_symbol('METROPOLIS', {})
    if bucket != 'mid cap':
        return _fail(f'expected METROPOLIS mid cap got {bucket!r}')
    return 0


def test_pattern_phrase_deduplicates_retest() -> int:
    from backend.trading.chart_patterns import pattern_phrase_for_why

    phrase = pattern_phrase_for_why({
        'label': 'Breakout retest',
        'status': 'retest_confirmed',
    })
    if phrase != 'Breakout retest confirmed':
        return _fail(f'expected deduped phrase got {phrase!r}')
    return 0


def test_early_tradecards_sorted_by_score_and_tiebreak() -> int:
    from backend.trading.opening_workflow_accounting import sort_early_tradecard_candidates

    candidates = [
        {'ticker': 'CHASE', 'state': 'CHASE_RISK', 'score': 90, 'has_catalyst': True},
        {'ticker': 'BEL', 'state': 'TRADECARD_CANDIDATE', 'score': 90, 'has_catalyst': True},
        {'ticker': 'THEME', 'state': 'TRADECARD_CANDIDATE', 'score': 90, 'themes': ['defence']},
        {'ticker': 'VOL', 'state': 'TRADECARD_CANDIDATE', 'score': 90, 'catalyst_state': 'PRICE_VOLUME_ONLY'},
    ]
    ranked = sort_early_tradecard_candidates(candidates)
    order = [str(r.get('ticker')) for r in ranked]
    if order[0] != 'BEL':
        return _fail(f'catalyst-confirmed safer pick should lead: {order!r}')
    if order.index('CHASE') < order.index('THEME'):
        return _fail(f'chase risk should sort after theme-only: {order!r}')
    if order.index('VOL') < order.index('THEME'):
        return _fail(f'price-volume-only should sort after theme: {order!r}')
    return 0


def test_regression_catalyst_classification_4b18() -> int:
    import subprocess
    rc = subprocess.run(
        [sys.executable, 'scripts/test_catalyst_gainer_classification_4b18.py'],
        cwd=PROJECT_ROOT,
        check=False,
    ).returncode
    return 0 if rc == 0 else _fail('test_catalyst_gainer_classification_4b18.py failed')


def test_regression_qa_smoke_isolation_4b18a() -> int:
    import subprocess
    rc = subprocess.run(
        [sys.executable, 'scripts/test_qa_smoke_isolation_4b18a.py'],
        cwd=PROJECT_ROOT,
        check=False,
    ).returncode
    return 0 if rc == 0 else _fail('test_qa_smoke_isolation_4b18a.py failed')


def test_regression_pattern_board_4b17a() -> int:
    import subprocess
    rc = subprocess.run(
        [sys.executable, 'scripts/test_pattern_board_4b17a.py'],
        cwd=PROJECT_ROOT,
        check=False,
    ).returncode
    return 0 if rc == 0 else _fail('test_pattern_board_4b17a.py failed')


def test_regression_pattern_board_consistency_4b17b() -> int:
    import subprocess
    rc = subprocess.run(
        [sys.executable, 'scripts/test_pattern_board_consistency_4b17b.py'],
        cwd=PROJECT_ROOT,
        check=False,
    ).returncode
    return 0 if rc == 0 else _fail('test_pattern_board_consistency_4b17b.py failed')


def main() -> int:
    tests = [
        ('scheduled early persists ranked candidates', test_scheduled_early_persists_ranked_candidates),
        ('scheduled final persists best pick', test_scheduled_final_persists_best_pick),
        ('final CONFIRMED increments daily review confirmed', test_final_confirmed_increments_daily_review_confirmed),
        ('daily review tradecards generated not zero', test_daily_review_tradecards_generated_not_zero),
        ('intraday batch counts three alerts', test_intraday_batch_counts_three_alerts),
        ('cap bucket resolves BEL', test_cap_bucket_resolves_bel),
        ('cap bucket resolves METROPOLIS', test_cap_bucket_resolves_metropolis),
        ('pattern phrase deduplicates retest', test_pattern_phrase_deduplicates_retest),
        ('early tradecards sorted by score tie-break', test_early_tradecards_sorted_by_score_and_tiebreak),
        ('regression catalyst classification 4B18', test_regression_catalyst_classification_4b18),
        ('regression QA smoke isolation 4B18A', test_regression_qa_smoke_isolation_4b18a),
        ('regression pattern board 4B17A', test_regression_pattern_board_4b17a),
        ('regression pattern board consistency 4B17B', test_regression_pattern_board_consistency_4b17b),
    ]
    failed = 0
    for name, test in tests:
        rc = test()
        if rc != 0:
            print(f'FAIL: {name}', file=sys.stderr)
            failed += 1
    if failed:
        return 1
    print('OPENING_WORKFLOW_ACCOUNTING_4B18B_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
