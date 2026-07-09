#!/usr/bin/env python3
"""Phase 4B.18M — Weekly conviction engine (AstraEdge 52K)."""

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
        self.imports_file = self.root / 'screener_imports.jsonl'
        self.stock_file = self.root / 'screener_stock_memory.jsonl'
        self.weekly_file = self.root / 'weekly_pick_records.jsonl'
        self.longterm_file = self.root / 'longterm_recommendation_snapshots.jsonl'
        self.imports_dir = self.root / 'imports'
        self.imports_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> '_WeeklyEnv':
        return self

    def __exit__(self, *args: object) -> None:
        self.tmpdir.cleanup()


def test_build_label() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52K' or ASTRAEDGE_BUILD_STAGE != '52K':
        return _fail(f'expected AstraEdge 52K got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    print('OK: test_build_label')
    return 0


def test_threshold_and_storage() -> int:
    from backend.trading.screener_memory import import_screener_csv
    from backend.trading.weekly_conviction_engine import (
        MIN_CONVICTION_SCORE,
        format_weekly_picks_telegram,
        generate_weekly_conviction_picks,
        weekly_memory_stats,
    )

    with _WeeklyEnv() as env:
        csv_path = env.imports_dir / 'weekly_test.csv'
        csv_path.write_text(SAMPLE_CSV, encoding='utf-8')
        with patch('backend.trading.screener_memory.imports_file_path', return_value=env.imports_file), \
             patch('backend.trading.screener_memory.stock_memory_file_path', return_value=env.stock_file), \
             patch('backend.trading.screener_memory.imports_dir_path', return_value=env.imports_dir), \
             patch('backend.trading.weekly_conviction_engine._weekly_records_path', return_value=env.weekly_file), \
             patch('backend.trading.weekly_conviction_engine._macro_risk_penalty', return_value=(0, [], False)), \
             patch('backend.trading.weekly_conviction_engine._score_news_catalyst', side_effect=lambda sym, row: (80, ['positive news/catalyst strength this week'], [], True)), \
             patch('backend.trading.weekly_conviction_engine._score_repeated_pick', side_effect=lambda sym: (100, [f'appeared in long-term list 3 times'], True)), \
             patch('backend.trading.weekly_conviction_engine._score_confidence_trend', side_effect=lambda sym: (90, ['confidence trend improving 70 → 82'], [], True)):
            import_screener_csv(csv_path, screen_name='quality_growth', query_text='weekly')
            result = generate_weekly_conviction_picks(persist=True)
            picks = result.get('records') or []
            if not picks:
                return _fail('expected at least one weekly pick above threshold')
            if int(picks[0].get('conviction_score') or 0) < MIN_CONVICTION_SCORE:
                return _fail(f'pick below threshold {MIN_CONVICTION_SCORE}')
            weak = [p for p in picks if _normalize(p.get('symbol')) == 'WEAK']
            if weak:
                return _fail('weak stock should not qualify')
            stats = weekly_memory_stats()
            if stats.get('weekly_pick_records', 0) < 1:
                return _fail('weekly_pick_records should be > 0')
            text = format_weekly_picks_telegram()
            if 'WEEKLY CONVICTION PICKS' not in text:
                return _fail('missing weekly picks header')
            if '/weekly history' not in text:
                return _fail('missing weekly footer')
    print('OK: test_threshold_and_storage')
    return 0


def test_no_qualifying_picks_message() -> int:
    from backend.trading.weekly_conviction_engine import format_weekly_picks_telegram, generate_weekly_conviction_picks

    with _WeeklyEnv() as env:
        with patch('backend.trading.weekly_conviction_engine._weekly_records_path', return_value=env.weekly_file), \
             patch('backend.trading.weekly_conviction_engine._candidate_universe', return_value={}), \
             patch('backend.trading.weekly_conviction_engine._macro_risk_penalty', return_value=(0, [], False)):
            result = generate_weekly_conviction_picks(persist=True)
            if result.get('records'):
                return _fail('empty universe should produce no records')
            text = format_weekly_picks_telegram()
            if 'NO WEEKLY HIGH-CONVICTION PICK' not in text:
                return _fail('missing no-pick message')
    print('OK: test_no_qualifying_picks_message')
    return 0


def test_weekly_history_and_explain() -> int:
    from backend.trading.screener_memory import import_screener_csv
    from backend.trading.weekly_conviction_engine import (
        format_weekly_explain_telegram,
        format_weekly_history_telegram,
        generate_weekly_conviction_picks,
    )

    with _WeeklyEnv() as env:
        csv_path = env.imports_dir / 'weekly_test.csv'
        csv_path.write_text(SAMPLE_CSV, encoding='utf-8')
        with patch('backend.trading.screener_memory.imports_file_path', return_value=env.imports_file), \
             patch('backend.trading.screener_memory.stock_memory_file_path', return_value=env.stock_file), \
             patch('backend.trading.screener_memory.imports_dir_path', return_value=env.imports_dir), \
             patch('backend.trading.weekly_conviction_engine._weekly_records_path', return_value=env.weekly_file), \
             patch('backend.trading.weekly_conviction_engine._macro_risk_penalty', return_value=(0, [], False)), \
             patch('backend.trading.weekly_conviction_engine._score_news_catalyst', side_effect=lambda sym, row: (80, [], [], True)), \
             patch('backend.trading.weekly_conviction_engine._score_repeated_pick', side_effect=lambda sym: (100, ['appeared in long-term list 3 times'], True)), \
             patch('backend.trading.weekly_conviction_engine._score_confidence_trend', side_effect=lambda sym: (90, [], [], True)):
            import_screener_csv(csv_path, screen_name='quality_growth', query_text='weekly')
            generate_weekly_conviction_picks(persist=True)
            hist = format_weekly_history_telegram()
            if 'Gillette' not in hist and 'GILLETTE' not in hist:
                return _fail('history should list weekly picks')
            explain = format_weekly_explain_telegram('GILLETTE')
            if 'Score components' not in explain:
                return _fail('explain missing score components')
            if 'conviction' not in explain.lower():
                return _fail('explain missing conviction')
    print('OK: test_weekly_history_and_explain')
    return 0


def test_telegram_routing() -> int:
    from backend.telegram.telegram_analysis_bot import parse_command

    cmd, args = parse_command('/weekly picks')
    if cmd != 'weekly' or args != 'picks':
        return _fail(f'/weekly picks routing got {cmd!r} {args!r}')
    cmd, args = parse_command('/weekly top')
    if cmd != 'weekly':
        return _fail('/weekly top not routed')
    cmd, args = parse_command('/weekly history')
    if cmd != 'weekly' or args != 'history':
        return _fail('/weekly history routing failed')
    cmd, args = parse_command('/weekly explain GILLETTE')
    if cmd != 'weekly' or not args.startswith('explain'):
        return _fail('/weekly explain routing failed')
    print('OK: test_telegram_routing')
    return 0


def _normalize(value: object) -> str:
    return str(value or '').strip().upper()


def main() -> int:
    tests = [
        test_build_label,
        test_threshold_and_storage,
        test_no_qualifying_picks_message,
        test_weekly_history_and_explain,
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
