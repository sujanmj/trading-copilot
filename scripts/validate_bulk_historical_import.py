#!/usr/bin/env python3
"""
Validate bulk historical import pipeline artifacts and DB safety.

Prints BULK_HISTORICAL_VALIDATE_OK on success.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.utils.config import DATA_DIR

UNIVERSE_PATH = DATA_DIR / 'historical_ticker_universe.json'
PROGRESS_PATH = DATA_DIR / 'historical_import_progress.json'
IMPORT_REPORT_PATH = DATA_DIR / 'historical_import_report.json'
REPLAY_REPORT_PATH = DATA_DIR / 'historical_replay_report.json'


def _fail(msg: str) -> int:
    print(f'BULK_HISTORICAL_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    from backend.analytics.historical_price_audit import audit_historical_prices
    from backend.storage.historical_market_store import get_historical_db_path, get_stats, init_db
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    if not init_db():
        return _fail('historical init_db failed')

    db_path = get_historical_db_path()
    if not db_path.exists():
        return _fail(f'historical DB missing: {db_path}')

    stats = get_stats()
    price_rows = int(stats.get('historical_prices') or 0)
    if price_rows <= 0:
        return _fail('historical_prices rows must be > 0')

    fake_rows = int(stats.get('fake_prices_rows') or 0)
    if fake_rows != 0:
        return _fail(f'fake_prices_rows={fake_rows}')

    audit = audit_historical_prices()
    if audit.get('fake_prices', 0) != 0:
        return _fail('audit fake_prices != 0')

    blocking_types = {
        'nan_ohlc',
        'high_lt_low',
        'open_outside_range',
        'close_outside_range',
        'fake_prices_flag',
        'duplicate_row',
    }
    blocking = [
        item for item in (audit.get('anomaly_details') or [])
        if item.get('type') in blocking_types
    ]
    if blocking:
        return _fail(f'blocking price anomalies={len(blocking)}')

    audit_script = PROJECT_ROOT / 'scripts' / 'audit_historical_price_quality.py'
    proc = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return _fail(f'audit subprocess failed: {proc.stderr.strip() or proc.stdout.strip()}')

    if not init_market_memory_db():
        return _fail('canonical init_market_memory_db failed')

    canonical_stats = get_market_memory_stats()
    if not canonical_stats.get('db_exists'):
        return _fail('canonical db_exists is False')

    validate_market = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / 'validate_market_memory.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if validate_market.returncode != 0:
        return _fail('validate_market_memory.py failed')

    if not UNIVERSE_PATH.is_file():
        return _fail('historical_ticker_universe.json missing')

    universe = _read_json(UNIVERSE_PATH)
    if not universe.get('tickers'):
        return _fail('universe tickers empty')

    for path, label in (
        (IMPORT_REPORT_PATH, 'import report'),
        (PROGRESS_PATH, 'import progress'),
    ):
        if not path.is_file():
            return _fail(f'{label} missing: {path.name}')
        try:
            _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            return _fail(f'{label} unreadable: {exc}')

    if REPLAY_REPORT_PATH.is_file():
        try:
            _read_json(REPLAY_REPORT_PATH)
        except (OSError, json.JSONDecodeError) as exc:
            return _fail(f'replay report unreadable: {exc}')

    print('BULK_HISTORICAL_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
