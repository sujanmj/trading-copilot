#!/usr/bin/env python3
"""Phase 4B.14A — Screener Telegram attachment import (CSV + XLSX)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

SAMPLE_CSV = """Name,NSE Code,Market Capitalization,Stock P/E,Debt to equity,Return on capital employed,Return on equity,Dividend payout,Sales growth,Profit growth,Promoter holding,Pledged percentage,Current Price
Persistent Systems,PERSISTENT,45000,45,0.1,28,22,15,12,14,45,0,5200
Coforge,COFORGE,60000,35,0.2,20,18,10,8,10,50,2,8000
"""


def _fail(msg: str) -> int:
    print(f'SCREENER_IMPORT_ATTACHMENT_4B14A_FAIL: {msg}', file=sys.stderr)
    return 1


def _ensure_openpyxl() -> None:
    """Install openpyxl from requirements when missing locally."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'openpyxl>=3.1.0'],
        )
        import openpyxl  # noqa: F401


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


def _write_sample_csv(imports_dir: Path, name: str = 'longterm_test.csv') -> Path:
    path = imports_dir / name
    path.write_text(SAMPLE_CSV, encoding='utf-8')
    return path


def _write_sample_xlsx(path: Path, *, repeat_header: bool = False) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    headers = [
        'Name', 'NSE Code', 'Mar Cap Rs.Cr.', 'Stock P/E', 'Debt / Eq',
        'ROCE %', 'ROE %', 'Payout ratio %', 'Sales growth', 'Profit growth',
        'Promoter holding', 'Pledged percentage', 'CMP Rs.',
    ]
    ws.append(headers)
    ws.append(['Alpha Ltd', 'ALPHA', 1200, 22, 0.3, 18, 16, 12, 10, 8, 55, 0, 450])
    if repeat_header:
        ws.append(headers)
    ws.append(['Beta Ltd', 'BETA', 800, 28, 0.5, 15, 14, 8, 6, 5, 48, 1, 320])
    wb.save(path)


def test_csv_filename_parsing() -> int:
    from backend.trading.screener_memory import parse_screener_import_filename

    got = parse_screener_import_filename('import longterm longterm_quality_screener.csv')
    if got != 'longterm_quality_screener.csv':
        return _fail(f'expected longterm_quality_screener.csv got {got!r}')
    return 0


def test_xlsx_filename_parsing() -> int:
    from backend.trading.screener_memory import parse_screener_import_filename

    got = parse_screener_import_filename('import longterm longterm_quality_screener_aligned.xlsx')
    if got != 'longterm_quality_screener_aligned.xlsx':
        return _fail(f'expected longterm_quality_screener_aligned.xlsx got {got!r}')
    return 0


def test_parser_strips_prefix_not_whole_args() -> int:
    from backend.trading.screener_memory import parse_screener_import_filename

    args = 'import longterm filename.csv'
    got = parse_screener_import_filename(args)
    if got == args:
        return _fail('parser must not treat full args string as filename')
    if got != 'filename.csv':
        return _fail(f'expected filename.csv got {got!r}')
    return 0


def test_csv_import_still_works() -> int:
    from backend.trading.screener_memory import import_screener_file

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        result = import_screener_file(csv_path)
        if not result.get('ok') or int(result.get('stored_count') or 0) < 2:
            return _fail('CSV import must store stocks')
    return 0


def test_xlsx_import_works() -> int:
    from backend.trading.screener_memory import import_screener_file

    with _ScreenerEnv() as imports_dir:
        xlsx_path = imports_dir / 'screener_sample.xlsx'
        _write_sample_xlsx(xlsx_path)
        result = import_screener_file(xlsx_path)
        if not result.get('ok'):
            return _fail('XLSX import must succeed')
        imp = result.get('import') or {}
        if imp.get('source') != 'screener_xlsx':
            return _fail(f'expected screener_xlsx source got {imp.get("source")!r}')
        if int(result.get('stored_count') or 0) != 2:
            return _fail(f'expected 2 stored stocks got {result.get("stored_count")!r}')
    return 0


def test_repeated_header_rows_ignored() -> int:
    from backend.trading.screener_memory import import_screener_file

    with _ScreenerEnv() as imports_dir:
        xlsx_path = imports_dir / 'repeat_header.xlsx'
        _write_sample_xlsx(xlsx_path, repeat_header=True)
        result = import_screener_file(xlsx_path)
        imp = result.get('import') or {}
        if int(imp.get('row_count') or 0) != 2:
            return _fail(f'expected 2 data rows got row_count={imp.get("row_count")!r}')
    return 0


def test_missing_columns_no_crash() -> int:
    from backend.trading.screener_memory import import_screener_file

    with _ScreenerEnv() as imports_dir:
        path = imports_dir / 'minimal.csv'
        path.write_text('Name,NSE Code\nOnlyName,ONLYONE\n', encoding='utf-8')
        try:
            result = import_screener_file(path)
        except Exception as exc:
            return _fail(f'missing columns must not crash: {exc}')
        if not result.get('ok'):
            return _fail('minimal CSV import must succeed')
    return 0


def test_telegram_csv_attachment() -> int:
    from backend.telegram.screener_intake import try_handle_screener_document
    from backend.trading.screener_memory import load_screener_imports

    with _ScreenerEnv():
        message = {
            'caption': '/screener import longterm',
            'document': {
                'file_id': 'csv-file-id',
                'file_name': 'uploaded_screener.csv',
            },
        }
        with patch(
            'backend.telegram.screener_intake.download_telegram_file',
            return_value=SAMPLE_CSV.encode('utf-8'),
        ):
            reply = try_handle_screener_document(message)
        if not reply or 'SCREENER IMPORTED' not in reply:
            return _fail(f'unexpected CSV attachment reply: {reply!r}')
        if not load_screener_imports(limit=1):
            return _fail('CSV attachment must persist import record')
    return 0


def test_telegram_xlsx_attachment() -> int:
    from backend.telegram.screener_intake import try_handle_screener_document

    buf = BytesIO()
    with _ScreenerEnv() as imports_dir:
        xlsx_path = imports_dir / 'tmp.xlsx'
        _write_sample_xlsx(xlsx_path)
        payload = xlsx_path.read_bytes()
        message = {
            'caption': '/screener import longterm',
            'document': {
                'file_id': 'xlsx-file-id',
                'file_name': 'uploaded_screener.xlsx',
            },
        }
        with patch(
            'backend.telegram.screener_intake.download_telegram_file',
            return_value=payload,
        ):
            reply = try_handle_screener_document(message)
        if not reply or 'SCREENER IMPORTED' not in reply:
            return _fail(f'unexpected XLSX attachment reply: {reply!r}')
        if 'Rows imported: 2' not in reply:
            return _fail(f'expected 2 rows in reply: {reply!r}')
    return 0


def test_unsupported_attachment_rejected() -> int:
    from backend.telegram.screener_intake import try_handle_screener_document

    message = {
        'caption': '/screener import longterm',
        'document': {
            'file_id': 'pdf-file-id',
            'file_name': 'report.pdf',
        },
    }
    reply = try_handle_screener_document(message)
    if reply != 'Unsupported file type. Upload CSV or XLSX.':
        return _fail(f'expected unsupported type message got {reply!r}')
    return 0


def test_help_trade_memory_section() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    if '<b>Trade Memory:</b>' not in HELP_TEXT:
        return _fail('help must contain Trade Memory section')
    if '/memory stock SYMBOL' not in HELP_TEXT:
        return _fail('help must list /memory stock')
    return 0


def test_help_screener_longterm_section() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    if '<b>Screener / Long-term:</b>' not in HELP_TEXT:
        return _fail('help must contain Screener / Long-term section')
    if '/screener import longterm' not in HELP_TEXT:
        return _fail('help must list screener import')
    return 0


def test_core_excludes_memory_screener_longterm() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    core_start = HELP_TEXT.find('<b>Core:</b>')
    trade_start = HELP_TEXT.find('<b>Trade Memory:</b>')
    if core_start < 0 or trade_start < 0:
        return _fail('help sections missing')
    core_block = HELP_TEXT[core_start:trade_start]
    for needle in ('/memory', '/screener', '/longterm'):
        if needle in core_block:
            return _fail(f'Core section must not contain {needle}')
    return 0


def test_build_label_51w() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    err = assert_canonical_build(_fail)
    if err:
        return err
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


def test_regression_4b14_4b13_4b12() -> int:
    from backend.qa.smoke_mode import should_skip_nested_regression

    if should_skip_nested_regression():
        print('SKIP: test_regression_4b14_4b13_4b12 (ASTRAEDGE_QA_SMOKE=1)')
        return 0
    for script in (
        'test_screener_longterm_memory_4b14.py',
        'test_tradecard_memory_4b13.py',
        'test_cap_bucket_visibility_4b12.py',
        'test_tradecard_closed_market_no_legacy_4b12.py',
    ):
        rc = _run_regression(script)
        if rc:
            return rc
    return 0


def main() -> int:
    _ensure_openpyxl()
    tests = [
        test_csv_filename_parsing,
        test_xlsx_filename_parsing,
        test_parser_strips_prefix_not_whole_args,
        test_csv_import_still_works,
        test_xlsx_import_works,
        test_repeated_header_rows_ignored,
        test_missing_columns_no_crash,
        test_telegram_csv_attachment,
        test_telegram_xlsx_attachment,
        test_unsupported_attachment_rejected,
        test_help_trade_memory_section,
        test_help_screener_longterm_section,
        test_core_excludes_memory_screener_longterm,
        test_build_label_51w,
        test_regression_4b14_4b13_4b12,
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
    print(f'ALL {len(tests)} SCREENER_IMPORT_ATTACHMENT_4B14A TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
