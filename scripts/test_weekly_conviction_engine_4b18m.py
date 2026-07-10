#!/usr/bin/env python3
"""Phase 4B.18M — Weekly conviction engine (AstraEdge 52M)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

SAMPLE_CSV = """Name,NSE Code,Market Capitalization,Stock P/E,Debt to equity,Return on capital employed,Return on equity,Dividend payout,Sales growth,Profit growth,Promoter holding,Pledged percentage,Current Price
Gillette India,GILLETTE,45000,45,0.1,32,24,15,12,14,45,0,5200
Tips Music,TIPS,8000,28,0.0,35,28,10,8,10,70,0,600
Weak Micro,WEAK,200,90,3.0,4,3,0,-8,-12,25,50,8
"""


def _fail(msg: str) -> int:
    print(f'WEEKLY_CONVICTION_4B18M_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


class _WeeklyEnv:
    def __init__(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.signals_file = self.root / 'weekly_signal_events.jsonl'
        self.runs_file = self.root / 'weekly_pick_runs.jsonl'
        self.picks_file = self.root / 'weekly_pick_records.jsonl'
        self.evals_file = self.root / 'weekly_candidate_evaluations.jsonl'
        self.imports_file = self.root / 'screener_imports.jsonl'
        self.stock_file = self.root / 'screener_stock_memory.jsonl'
        self.imports_dir = self.root / 'imports'
        self.imports_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> '_WeeklyEnv':
        return self

    def __exit__(self, *args: object) -> None:
        self.tmpdir.cleanup()

    def patches(self):
        return [
            patch('backend.trading.weekly_conviction_engine._signal_events_path', return_value=self.signals_file),
            patch('backend.trading.weekly_conviction_engine._weekly_runs_path', return_value=self.runs_file),
            patch('backend.trading.weekly_conviction_engine._weekly_records_path', return_value=self.picks_file),
            patch('backend.trading.weekly_conviction_engine._weekly_evaluations_path', return_value=self.evals_file),
            patch('backend.trading.screener_memory.imports_file_path', return_value=self.imports_file),
            patch('backend.trading.screener_memory.stock_memory_file_path', return_value=self.stock_file),
            patch('backend.trading.screener_memory.imports_dir_path', return_value=self.imports_dir),
            patch('backend.trading.weekly_conviction_engine.backfill_partial_longterm_signals_for_week', return_value=0),
            patch('backend.trading.weekly_conviction_engine._macro_penalty_from_events', return_value=(0, [], False)),
        ]

    def patch_all(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            patches = self.patches()
            stack = []
            try:
                for p in patches:
                    stack.append(p)
                    p.start()
                yield self
            finally:
                for p in reversed(stack):
                    p.stop()

        return _cm()


def _seed_multi_source_signals(env: _WeeklyEnv, sym: str = 'GILLETTE', company: str = 'Gillette India') -> None:
    from backend.trading.weekly_conviction_engine import capture_weekly_signal_event

    for source, score in (
        ('SCREENER', 90),
        ('LONGTERM', 88),
        ('TRADECARD', 80),
        ('NEWS', 78),
        ('CATALYST', 75),
        ('PATTERN', 70),
    ):
        capture_weekly_signal_event(
            symbol=sym,
            company_name=company,
            source_type=source,
            source_command_or_module='test',
            signal_score=score,
            signal_direction='positive',
            signal_strength='strong',
            reason=f'test {source}',
        )


def test_build_label() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52M' or ASTRAEDGE_BUILD_STAGE != '52M':
        return _fail(f'expected AstraEdge 52M got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    print('OK: test_build_label')
    return 0


def test_week_helpers() -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from backend.trading.weekly_conviction_engine import (
        _coverage_label,
        current_week_id,
        week_end_date,
        week_start_date,
    )

    week = current_week_id()
    if '-W' not in week:
        return _fail(f'bad week id {week!r}')
    if week_start_date() > week_end_date():
        return _fail('week start after end')

    ist = ZoneInfo('Asia/Kolkata')
    thu = datetime(2026, 7, 9, 14, 0, tzinfo=ist)
    if _coverage_label(thu) != 'Mon–Thu / partial week':
        return _fail(f'Thu coverage wrong: {_coverage_label(thu)!r}')
    fri_early = datetime(2026, 7, 10, 1, 53, tzinfo=ist)
    if _coverage_label(fri_early) != 'Mon–Fri / in progress — Friday session pending':
        return _fail(f'Fri 01:53 coverage wrong: {_coverage_label(fri_early)!r}')
    fri_late = datetime(2026, 7, 10, 16, 0, tzinfo=ist)
    if _coverage_label(fri_late) != 'Mon–Fri / complete week':
        return _fail(f'Fri 16:00 coverage wrong: {_coverage_label(fri_late)!r}')
    sat = datetime(2026, 7, 11, 10, 0, tzinfo=ist)
    if _coverage_label(sat) != 'Mon–Fri / complete week':
        return _fail(f'Sat coverage wrong: {_coverage_label(sat)!r}')
    print('OK: test_week_helpers')
    return 0


def test_multi_source_qualifies_and_stores_run() -> int:
    from backend.trading.weekly_conviction_engine import (
        MIN_CONVICTION_SCORE,
        format_weekly_picks_telegram,
        generate_weekly_conviction_picks,
        weekly_memory_stats,
    )

    with _WeeklyEnv() as env:
        with env.patch_all():
            _seed_multi_source_signals(env)
            result = generate_weekly_conviction_picks(persist=True)
            if not result.get('records'):
                return _fail('expected qualifying multi-source pick')
            if int(result['records'][0].get('conviction_score') or 0) < MIN_CONVICTION_SCORE:
                return _fail('pick below threshold')
            if not result.get('run'):
                return _fail('expected run record even with picks')
            stats = weekly_memory_stats()
            if stats.get('weekly_pick_runs', 0) < 1:
                return _fail('weekly_pick_runs should be > 0')
            if stats.get('weekly_signal_events', 0) < 6:
                return _fail('expected signal events')
            text = format_weekly_picks_telegram()
            if 'Signals scanned:' not in text:
                return _fail('missing signals scanned line')
    print('OK: test_multi_source_qualifies_and_stores_run')
    return 0


def test_zero_pick_stores_run_with_best_candidate() -> int:
    from backend.trading.weekly_conviction_engine import (
        capture_weekly_signal_event,
        format_weekly_picks_telegram,
        generate_weekly_conviction_picks,
    )

    with _WeeklyEnv() as env:
        with env.patch_all():
            capture_weekly_signal_event(
                symbol='IRCTC',
                company_name='I R C T C',
                source_type='LONGTERM',
                source_command_or_module='test',
                signal_score=81,
                signal_direction='positive',
                signal_strength='strong',
                reason='longterm only',
            )
            result = generate_weekly_conviction_picks(persist=True)
            if result.get('records'):
                return _fail('longterm-only should not qualify')
            run = result.get('run') or {}
            if run.get('pick_count', -1) != 0:
                return _fail('expected pick_count=0 run')
            text = format_weekly_picks_telegram()
            if 'NO WEEKLY HIGH-CONVICTION PICK' not in text:
                return _fail('missing no-pick message')
            if 'Best candidate:' not in text:
                return _fail('missing best candidate line')
            if 'Missing evidence:' not in text and 'missing' not in text.lower():
                return _fail('missing evidence line')
    print('OK: test_zero_pick_stores_run_with_best_candidate')
    return 0


def test_weekly_explain_without_screener_row() -> int:
    from backend.trading.weekly_conviction_engine import (
        capture_weekly_signal_event,
        format_weekly_explain_telegram,
        generate_weekly_conviction_picks,
    )

    with _WeeklyEnv() as env:
        with env.patch_all():
            capture_weekly_signal_event(
                symbol='IRCTC',
                company_name='I R C T C',
                source_type='LONGTERM',
                source_command_or_module='test',
                signal_score=81,
                signal_direction='positive',
                signal_strength='strong',
                reason='confidence 81',
            )
            generate_weekly_conviction_picks(persist=True)
            text = format_weekly_explain_telegram('IRCTC')
            if 'WEEKLY EXPLAIN — IRCTC' not in text:
                return _fail('missing explain header')
            if 'NOT_SELECTED' not in text and 'SELECTED' not in text:
                return _fail('missing weekly status')
            if 'LONGTERM:' not in text:
                return _fail('missing longterm signal line')
            if 'TRADECARD: missing' not in text:
                return _fail('expected missing tradecard')
    print('OK: test_weekly_explain_without_screener_row')
    return 0


def test_weekly_history_shows_zero_pick_run() -> int:
    from backend.trading.weekly_conviction_engine import (
        capture_weekly_signal_event,
        format_weekly_history_telegram,
        generate_weekly_conviction_picks,
    )

    with _WeeklyEnv() as env:
        with env.patch_all():
            capture_weekly_signal_event(
                symbol='GILLETTE',
                company_name='Gillette India',
                source_type='LONGTERM',
                source_command_or_module='test',
                signal_score=75,
                signal_direction='positive',
                signal_strength='medium',
                reason='test',
            )
            generate_weekly_conviction_picks(persist=True)
            hist = format_weekly_history_telegram()
            if '0 picks' not in hist:
                return _fail('history should show zero-pick run')
            if 'best' not in hist.lower():
                return _fail('history should show best candidate')
    print('OK: test_weekly_history_shows_zero_pick_run')
    return 0


def test_telegram_routing() -> int:
    from backend.telegram.telegram_analysis_bot import parse_command

    cmd, args = parse_command('/weekly picks')
    if cmd != 'weekly' or args != 'picks':
        return _fail(f'/weekly picks routing got {cmd!r} {args!r}')
    cmd, args = parse_command('/weekly explain IRCTC')
    if cmd != 'weekly' or not args.startswith('explain'):
        return _fail('/weekly explain routing failed')
    print('OK: test_telegram_routing')
    return 0


def main() -> int:
    tests = [
        test_build_label,
        test_week_helpers,
        test_multi_source_qualifies_and_stores_run,
        test_zero_pick_stores_run_with_best_candidate,
        test_weekly_explain_without_screener_row,
        test_weekly_history_shows_zero_pick_run,
        test_telegram_routing,
    ]
    failed = 0
    for fn in tests:
        rc = fn()
        if rc:
            failed += 1
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print(f'ALL {len(tests)} WEEKLY_CONVICTION_4B18M TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
