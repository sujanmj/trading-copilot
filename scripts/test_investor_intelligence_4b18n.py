#!/usr/bin/env python3
"""Phase 4B.18N — Investor / shareholding intelligence (AstraEdge 52L)."""

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


def _fail(msg: str) -> int:
    print(f'INVESTOR_INTELLIGENCE_4B18N_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


class _InvestorEnv:
    def __init__(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.records_file = self.root / 'investor_records.jsonl'
        self.signals_file = self.root / 'weekly_signals.jsonl'

    def __enter__(self) -> '_InvestorEnv':
        return self

    def __exit__(self, *args: object) -> None:
        self.tmpdir.cleanup()


def test_build_label() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52L' or ASTRAEDGE_BUILD_STAGE != '52L':
        return _fail(f'expected AstraEdge 52L got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    print('OK: test_build_label')
    return 0


def test_extraction_and_scoring() -> int:
    from backend.trading.investor_intelligence import (
        build_investor_record,
        extract_investor_fields_from_stock_row,
        score_investor_record,
    )

    row = {
        'symbol': 'IRCTC',
        'company_name': 'IRCTC',
        'promoter_holding': 62.4,
        'pledged_percent': 0,
        'fii_holding': 7.2,
        'dii_holding': 8.0,
        'mutual_fund_holding': 4.8,
        'public_holding': 17.6,
    }
    fields = extract_investor_fields_from_stock_row(row)
    if fields.get('promoter_holding') != 62.4:
        return _fail('promoter extraction failed')
    rec = build_investor_record(symbol='IRCTC', company_name='IRCTC', fields=fields)
    if str(rec.get('data_quality') or '') not in ('GOOD', 'LIMITED'):
        return _fail(f'unexpected data quality {rec.get("data_quality")!r}')
    if int(rec.get('investor_score') or 0) < 65:
        return _fail('stable promoter low pledge should score well')
    if 'promoter holding stable/high' not in (rec.get('investor_reason_tags') or []):
        return _fail('expected positive promoter tag')
    if 'pledge low' not in (rec.get('investor_reason_tags') or []):
        return _fail('expected pledge low tag')

    risky = score_investor_record({
        'promoter_holding': 40,
        'promoter_pledge': 30,
        'fii_holding': 5,
    })
    if 'high promoter pledge' not in (risky.get('investor_risk_tags') or []):
        return _fail('high pledge should create risk tag')
    if risky.get('investor_band') not in ('WEAK', 'RISKY', 'NEUTRAL'):
        return _fail('high pledge should weaken band')

    missing = score_investor_record({})
    if missing.get('data_quality') != 'MISSING':
        return _fail('empty row should be MISSING quality')
    if missing.get('investor_band') != 'NEUTRAL':
        return _fail('missing data should be NEUTRAL not negative')
    print('OK: test_extraction_and_scoring')
    return 0


def test_storage_and_weekly_signal() -> int:
    from backend.trading.investor_intelligence import (
        append_investor_record,
        build_investor_record,
        capture_investor_from_screener_stocks,
        investor_memory_stats,
        latest_investor_record,
    )

    with _InvestorEnv() as env:
        with patch('backend.trading.investor_intelligence._records_path', return_value=env.records_file), \
             patch('backend.trading.weekly_conviction_engine._signal_events_path', return_value=env.signals_file), \
             patch('backend.trading.weekly_signal_capture.capture_investor_weekly_signal') as cap_mock:
            stocks = [{
                'symbol': 'GILLETTE',
                'company_name': 'Gillette India',
                'promoter_holding': 55,
                'pledged_percent': 0,
                'fii_holding': 10,
                'dii_holding': 12,
            }]
            stored = capture_investor_from_screener_stocks(stocks, import_id='imp1', imported_at='2026-07-04T10:00:00+05:30')
            if len(stored) != 1:
                return _fail('expected one investor record')
            rec = latest_investor_record('GILLETTE')
            if not rec:
                return _fail('latest record missing')
            stats = investor_memory_stats()
            if stats.get('investor_records', 0) < 1:
                return _fail('stats should count records')
            if not cap_mock.called:
                return _fail('weekly investor signal should be captured')
    print('OK: test_storage_and_weekly_signal')
    return 0


def test_investor_routing() -> int:
    from backend.telegram.telegram_analysis_bot import parse_command

    cmd, args = parse_command('/investor IRCTC')
    if cmd != 'investor' or args != 'IRCTC':
        return _fail(f'/investor SYMBOL routing got {cmd!r} {args!r}')
    cmd, args = parse_command('/investor weekly')
    if cmd != 'investor' or args != 'weekly':
        return _fail('/investor weekly routing failed')
    cmd, args = parse_command('/investor memory IRCTC')
    if cmd != 'investor' or not args.startswith('memory'):
        return _fail('/investor memory routing failed')
    print('OK: test_investor_routing')
    return 0


def test_weekly_explain_investor_block() -> int:
    from backend.trading.investor_intelligence import append_investor_record, build_investor_record
    from backend.trading.weekly_conviction_engine import format_weekly_explain_telegram

    with _InvestorEnv() as env:
        with patch('backend.trading.investor_intelligence._records_path', return_value=env.records_file):
            rec = build_investor_record(
                symbol='IRCTC',
                company_name='IRCTC',
                fields={'promoter_holding': 62, 'promoter_pledge': 0, 'fii_holding': 7, 'dii_holding': 10},
            )
            append_investor_record(rec)
            text = format_weekly_explain_telegram('IRCTC')
            if 'INVESTOR:' not in text:
                return _fail('weekly explain missing INVESTOR block')
            if 'score' not in text.lower():
                return _fail('weekly explain missing investor score')
    print('OK: test_weekly_explain_investor_block')
    return 0


def test_memory_stats_includes_investor() -> int:
    from backend.telegram.response_format import format_tradecard_memory_stats_telegram
    from backend.trading.investor_intelligence import append_investor_record, build_investor_record

    with _InvestorEnv() as env:
        with patch('backend.trading.investor_intelligence._records_path', return_value=env.records_file):
            append_investor_record(build_investor_record(
                symbol='TCS',
                fields={'promoter_holding': 70, 'promoter_pledge': 0},
            ))
            text = format_tradecard_memory_stats_telegram()
            if 'Investor memory:' not in text:
                return _fail('memory stats missing investor section')
            if 'investor_records:' not in text:
                return _fail('memory stats missing investor_records')
    print('OK: test_memory_stats_includes_investor')
    return 0


def main() -> int:
    tests = [
        test_build_label,
        test_extraction_and_scoring,
        test_storage_and_weekly_signal,
        test_investor_routing,
        test_weekly_explain_investor_block,
        test_memory_stats_includes_investor,
    ]
    failed = 0
    for fn in tests:
        if fn():
            failed += 1
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print(f'ALL {len(tests)} INVESTOR_INTELLIGENCE_4B18N TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
