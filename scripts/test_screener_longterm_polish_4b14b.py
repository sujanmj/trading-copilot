#!/usr/bin/env python3
"""Phase 4B.14B — Screener long-term import normalization and scoring polish."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'SCREENER_LONGTERM_POLISH_4B14B_FAIL: {msg}', file=sys.stderr)
    return 1


class _ScreenerEnv:
    def __init__(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.imports_file = self.root / 'screener_imports.jsonl'
        self.stock_file = self.root / 'screener_stock_memory.jsonl'
        self.imports_dir = self.root / 'imports'
        self.imports_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> Path:
        os.environ['SCREENER_IMPORTS_FILE'] = str(self.imports_file)
        os.environ['SCREENER_STOCK_MEMORY_FILE'] = str(self.stock_file)
        os.environ['SCREENER_IMPORTS_DIR'] = str(self.imports_dir)
        return self.imports_dir

    def __exit__(self, *args: object) -> None:
        os.environ.pop('SCREENER_IMPORTS_FILE', None)
        os.environ.pop('SCREENER_STOCK_MEMORY_FILE', None)
        os.environ.pop('SCREENER_IMPORTS_DIR', None)
        self.tmpdir.cleanup()


SAMPLE_NAME_ONLY_CSV = """Name,CMP Rs.,Mar Cap Rs.Cr.,FCF Prev Ann Rs.Cr.,ROE %,Payout ratio %,Debt / Eq,ROCE %
Gillette India,8500,45000,1200,28,35,0.08,42
Jeena Sikho,120,300,,-5,120,0.45,18
Garden Reach Sh.,1800,8500,-200,22,0,0.55,15
Alpha Quality,500,12000,800,30,40,0.05,35
Beta Weak,90,250,-50,8,0,0.48,9
"""

SAMPLE_DEBT_CSV = """Name,Debt / Eq,ROCE %,ROE %
No Debt Data,,18,15
LowDebt,0.2,20,16
"""


def test_full_company_name_preserved() -> int:
    from backend.trading.screener_memory import import_screener_file, load_stock_memory

    with _ScreenerEnv() as imports_dir:
        path = imports_dir / 'names.csv'
        path.write_text(SAMPLE_NAME_ONLY_CSV, encoding='utf-8')
        import_screener_file(path)
        rows = load_stock_memory('GILLETTE')
        if not rows:
            return _fail('expected GILLETTE row')
        row = rows[0]
        if row.get('company_name') != 'Gillette India':
            return _fail(f'expected Gillette India got {row.get("company_name")!r}')
        if row.get('display_name') != 'Gillette India':
            return _fail(f'expected display_name Gillette India got {row.get("display_name")!r}')
    return 0


def test_symbol_key_and_company_lookup() -> int:
    from backend.trading.screener_memory import import_screener_file, summarize_symbol_screener

    with _ScreenerEnv() as imports_dir:
        path = imports_dir / 'names.csv'
        path.write_text(SAMPLE_NAME_ONLY_CSV, encoding='utf-8')
        import_screener_file(path)
        by_key = summarize_symbol_screener('JEENA')
        by_name = summarize_symbol_screener('Jeena Sikho')
        if not int(by_key.get('count') or 0):
            return _fail('symbol_key lookup failed')
        if not int(by_name.get('count') or 0):
            return _fail('company_name lookup failed')
        if by_key.get('display_name') != 'Jeena Sikho':
            return _fail(f'expected Jeena Sikho display got {by_key.get("display_name")!r}')
    return 0


def test_debt_column_normalizes() -> int:
    from backend.trading.screener_memory import import_screener_file, load_stock_memory

    with _ScreenerEnv() as imports_dir:
        path = imports_dir / 'debt.csv'
        path.write_text(SAMPLE_DEBT_CSV, encoding='utf-8')
        import_screener_file(path)
        rows = load_stock_memory('LOWDEBT')
        if not rows:
            return _fail('expected LOWDEBT row')
        if rows[0].get('debt_to_equity') in (None, ''):
            return _fail('debt_to_equity must be populated from Debt / Eq')
    return 0


def test_debt_reason_missing_when_debt_missing() -> int:
    from backend.trading.longterm_scoring import score_longterm_stock

    scored = score_longterm_stock({'roce': 18, 'roe': 15})
    if 'debt low' in scored.get('reasons', []):
        return _fail('debt low must not appear when debt missing')
    return 0


def test_debt_reason_when_low_debt() -> int:
    from backend.trading.longterm_scoring import score_longterm_stock

    scored = score_longterm_stock({'roce': 18, 'roe': 15, 'debt_to_equity': 0.2})
    if 'debt low' not in scored.get('reasons', []):
        return _fail('debt low must appear when debt <= 0.5')
    return 0


def test_fcf_negative_risk_flag() -> int:
    from backend.trading.longterm_scoring import score_longterm_stock

    scored = score_longterm_stock({'roce': 20, 'roe': 15, 'free_cashflow': -100})
    if 'negative free cash flow' not in scored.get('risk_flags', []):
        return _fail('negative FCF must create risk flag')
    return 0


def test_payout_above_100_risk_flag() -> int:
    from backend.trading.longterm_scoring import score_longterm_stock

    scored = score_longterm_stock({'roce': 20, 'roe': 15, 'dividend_payout': 120})
    if 'payout above earnings' not in scored.get('risk_flags', []):
        return _fail('payout > 100 must create risk flag')
    return 0


def test_scores_differentiated() -> int:
    from backend.trading.screener_memory import import_screener_file, latest_import_stocks

    with _ScreenerEnv() as imports_dir:
        path = imports_dir / 'names.csv'
        path.write_text(SAMPLE_NAME_ONLY_CSV, encoding='utf-8')
        import_screener_file(path)
        stocks = latest_import_stocks(limit=10)
        scores = [int(s.get('longterm_score') or 0) for s in stocks]
        if len(set(scores)) < 2:
            return _fail(f'expected differentiated scores got {scores}')
    return 0


def test_longterm_display_uses_company_name() -> int:
    from backend.trading.screener_memory import import_screener_file
    from backend.telegram.response_format import format_longterm_telegram

    with _ScreenerEnv() as imports_dir:
        path = imports_dir / 'names.csv'
        path.write_text(SAMPLE_NAME_ONLY_CSV, encoding='utf-8')
        import_screener_file(path)
        text = format_longterm_telegram(limit=5)
        if 'Gillette India' not in text:
            return _fail('/longterm must show full company name')
        if text.count('GILLETTE —') > 0:
            return _fail('/longterm must not show symbol_key as primary label')
    return 0


def test_longterm_explain_shows_debt_when_present() -> int:
    from backend.trading.screener_memory import import_screener_file
    from backend.telegram.response_format import format_longterm_explain_telegram

    with _ScreenerEnv() as imports_dir:
        path = imports_dir / 'names.csv'
        path.write_text(SAMPLE_NAME_ONLY_CSV, encoding='utf-8')
        import_screener_file(path)
        text = format_longterm_explain_telegram('Gillette India')
        if 'Debt/Equity: 0.08' not in text and 'Debt/Equity: 0.080' not in text:
            if 'Debt/Equity: 0.08' not in text.replace(' ', ''):
                if '0.08' not in text:
                    return _fail(f'debt/equity must appear when present: {text!r}')
    return 0


def test_screener_status_no_import_csv_xlsx_wording() -> int:
    from backend.telegram.response_format import format_screener_status_telegram

    with _ScreenerEnv():
        text = format_screener_status_telegram()
        if 'CSV/XLSX' not in text:
            return _fail('status must mention CSV/XLSX')
        if 'Place CSV in' in text:
            return _fail('status must not say CSV only')
        if '/screener import longterm' not in text:
            return _fail('status must mention attachment caption')
    return 0


def test_build_label_51w() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51Y' or ASTRAEDGE_BUILD_STAGE != '51Y':
        return _fail(f'expected AstraEdge 51Y got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def _run_regression(script: str) -> int:
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return _fail(f'{script} failed with code {proc.returncode}')
    return 0


def test_regression_4b14a_4b14_4b13() -> int:
    for script in (
        'test_screener_import_attachment_4b14a.py',
        'test_screener_longterm_memory_4b14.py',
        'test_tradecard_memory_4b13.py',
    ):
        rc = _run_regression(script)
        if rc:
            return rc
    return 0


def main() -> int:
    tests = [
        test_full_company_name_preserved,
        test_symbol_key_and_company_lookup,
        test_debt_column_normalizes,
        test_debt_reason_missing_when_debt_missing,
        test_debt_reason_when_low_debt,
        test_fcf_negative_risk_flag,
        test_payout_above_100_risk_flag,
        test_scores_differentiated,
        test_longterm_display_uses_company_name,
        test_longterm_explain_shows_debt_when_present,
        test_screener_status_no_import_csv_xlsx_wording,
        test_build_label_51w,
        test_regression_4b14a_4b14_4b13,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print(f'ALL {len(tests)} SCREENER_LONGTERM_POLISH_4B14B TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
