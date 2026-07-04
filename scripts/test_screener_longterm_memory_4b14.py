#!/usr/bin/env python3
"""Phase 4B.14 — Screener import and long-term stock memory."""

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
Persistent Systems,PERSISTENT,45000,45,0.1,28,22,15,12,14,45,0,5200
Coforge,COFORGE,60000,35,0.2,20,18,10,8,10,50,2,8000
Risky Micro,RISKXYZ,300,80,2.5,5,4,0,-5,-10,30,40,12
"""


def _fail(msg: str) -> int:
    print(f'SCREENER_LONGTERM_4B14_TEST_FAIL: {msg}', file=sys.stderr)
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


def _write_sample_csv(imports_dir: Path, name: str = 'longterm_test.csv') -> Path:
    path = imports_dir / name
    path.write_text(SAMPLE_CSV, encoding='utf-8')
    return path


def test_csv_import_stores_import_record() -> int:
    from backend.trading.screener_memory import import_screener_csv, load_screener_imports

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        result = import_screener_csv(csv_path, screen_name='quality_growth', query_text='ROCE>15')
        if not result.get('ok'):
            return _fail('import must succeed')
        imports = load_screener_imports(limit=5)
        if not imports:
            return _fail('expected import record')
        imp = imports[0]
        if imp.get('query_text') != 'ROCE>15':
            return _fail(f'expected query_text got {imp.get("query_text")!r}')
        if int(imp.get('row_count') or 0) != 3:
            return _fail(f'expected row_count 3 got {imp.get("row_count")!r}')
    return 0


def test_csv_import_stores_stock_rows() -> int:
    from backend.trading.screener_memory import import_screener_csv, load_stock_memory

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        import_screener_csv(csv_path, screen_name='quality_growth', query_text='test')
        rows = load_stock_memory(limit=20)
        if len(rows) < 3:
            return _fail(f'expected 3 stock rows got {len(rows)}')
        persistent = next((r for r in rows if r.get('symbol') == 'PERSISTENT'), None)
        if not persistent:
            return _fail('expected PERSISTENT row')
        if persistent.get('roce') is None:
            return _fail('expected normalized ROCE on PERSISTENT')
        if not persistent.get('longterm_score'):
            return _fail('expected longterm_score on stock row')
    return 0


def test_longterm_scoring() -> int:
    from backend.trading.longterm_scoring import score_longterm_stock

    scored = score_longterm_stock({
        'symbol': 'PERSISTENT',
        'roce': 28,
        'roe': 22,
        'debt_to_equity': 0.1,
        'sales_growth': 12,
        'profit_growth': 14,
        'pe': 45,
        'market_cap': 45000,
    })
    if int(scored.get('longterm_score') or 0) <= 0:
        return _fail('expected positive longterm_score')
    if not scored.get('reasons'):
        return _fail('expected reasons list')
    if not scored.get('verdict'):
        return _fail('expected verdict')
    if 'risk_flags' not in scored:
        return _fail('expected risk_flags key')
    return 0


def test_screener_status() -> int:
    from backend.telegram.response_format import format_screener_status_telegram
    from backend.trading.screener_memory import import_screener_csv

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        import_screener_csv(csv_path, screen_name='quality_growth', query_text='test')
        text = format_screener_status_telegram()
        if 'SCREENER — STATUS' not in text:
            return _fail('status output missing title')
        if 'quality_growth' not in text:
            return _fail('status must show screen name')
        if 'Rows imported: 3' not in text:
            return _fail('status must show row count')
    return 0


def test_screener_latest() -> int:
    from backend.telegram.response_format import format_screener_latest_telegram
    from backend.trading.screener_memory import import_screener_csv

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        import_screener_csv(csv_path, screen_name='quality_growth', query_text='test')
        text = format_screener_latest_telegram()
        if 'Top long-term candidates' not in text:
            return _fail('latest must show top candidates header')
        if 'PERSISTENT' not in text and 'COFORGE' not in text:
            return _fail('latest must list imported symbols')
    return 0


def test_longterm_ranks_by_score() -> int:
    from backend.telegram.response_format import format_longterm_telegram
    from backend.trading.screener_memory import import_screener_csv, latest_import_stocks

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        import_screener_csv(csv_path, screen_name='quality_growth', query_text='test')
        stocks = latest_import_stocks()
        if len(stocks) < 2:
            return _fail('expected ranked stocks')
        if int(stocks[0].get('longterm_score') or 0) < int(stocks[1].get('longterm_score') or 0):
            return _fail('stocks must be sorted by longterm_score desc')
        text = format_longterm_telegram(limit=5)
        if 'LONG-TERM WATCHLIST' not in text:
            return _fail('longterm output missing title')
        first_line = [ln for ln in text.splitlines() if ln.startswith('1.')][0]
        if stocks[0].get('symbol') not in first_line:
            return _fail('longterm #1 must match highest score symbol')
    return 0


def test_longterm_explain() -> int:
    from backend.telegram.response_format import format_longterm_explain_telegram
    from backend.trading.screener_memory import import_screener_csv

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        import_screener_csv(csv_path, screen_name='quality_growth', query_text='test')
        text = format_longterm_explain_telegram('PERSISTENT')
        if 'LONG-TERM — PERSISTENT' not in text:
            return _fail('explain missing title')
        if 'Long-term score' not in text:
            return _fail('explain missing score')
        if 'Reasons:' not in text:
            return _fail('explain missing reasons section')
    return 0


def test_memory_stock_combined() -> int:
    from backend.telegram.response_format import format_tradecard_memory_stock_telegram
    from backend.trading.screener_memory import import_screener_csv
    from backend.trading.tradecard_memory import append_tradecard_memory, build_memory_record

    with _ScreenerEnv() as imports_dir:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jsonl') as tc_tmp:
            tc_path = Path(tc_tmp.name)
        os.environ['TRADECARD_MEMORY_FILE'] = str(tc_path)
        try:
            csv_path = _write_sample_csv(imports_dir)
            import_screener_csv(csv_path, screen_name='quality_growth', query_text='test')
            append_tradecard_memory(build_memory_record(
                command_source='/tradecards',
                board={'session_date': '2026-05-27', 'data_status': 'current'},
                symbol='PERSISTENT',
                row={'ticker': 'PERSISTENT', 'score': 70, 'why': ['top gainer'], 'gainer_bucket': 'large cap'},
                rank=1,
                selected_best=True,
            ))
            text = format_tradecard_memory_stock_telegram('PERSISTENT')
            if 'Tradecard memory' not in text:
                return _fail('combined memory must include tradecard section')
            if 'Screener memory' not in text:
                return _fail('combined memory must include Screener section')
        finally:
            os.environ.pop('TRADECARD_MEMORY_FILE', None)
            if tc_path.exists():
                tc_path.unlink()
    return 0


def test_screener_does_not_create_tradecard() -> int:
    from backend.trading.screener_memory import import_screener_csv

    with _ScreenerEnv() as imports_dir:
        csv_path = _write_sample_csv(imports_dir)
        with patch('backend.trading.trade_card_engine.get_trade_card') as mock_card, \
             patch('backend.trading.trade_card_engine.build_trade_card') as mock_build:
            import_screener_csv(csv_path, screen_name='quality_growth', query_text='test')
            if mock_card.called or mock_build.called:
                return _fail('Screener import must not call tradecard engine')
    return 0


def test_missing_columns_no_crash() -> int:
    from backend.trading.screener_memory import import_screener_csv

    with _ScreenerEnv() as imports_dir:
        minimal = imports_dir / 'minimal.csv'
        minimal.write_text('Name,NSE Code\nOnly Name,ONLYME\n', encoding='utf-8')
        try:
            result = import_screener_csv(minimal, screen_name='minimal', query_text='minimal')
        except Exception as exc:
            return _fail(f'minimal CSV must not crash: {exc}')
        if int(result.get('stored_count') or 0) != 1:
            return _fail('minimal CSV should store one symbol row')
    return 0


def test_build_label_51o() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51O' or ASTRAEDGE_BUILD_STAGE != '51O':
        return _fail(f'expected AstraEdge 51O got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_csv_import_stores_import_record,
        test_csv_import_stores_stock_rows,
        test_longterm_scoring,
        test_screener_status,
        test_screener_latest,
        test_longterm_ranks_by_score,
        test_longterm_explain,
        test_memory_stock_combined,
        test_screener_does_not_create_tradecard,
        test_missing_columns_no_crash,
        test_build_label_51o,
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
    print(f'ALL {len(tests)} SCREENER_LONGTERM_4B14 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
