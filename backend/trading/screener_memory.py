"""
Screener import memory — Phase 4B.14.

CSV import, long-term stock memory, query helpers.
Paper/research only — no LLM calls; does not create intraday tradecards.
"""

from __future__ import annotations

import csv
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.trading.longterm_scoring import score_longterm_stock
from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.14'

DEFAULT_IMPORTS_FILE = DATA_DIR / 'screener_imports.jsonl'
DEFAULT_STOCK_MEMORY_FILE = DATA_DIR / 'screener_stock_memory.jsonl'
DEFAULT_IMPORTS_DIR = DATA_DIR / 'imports'

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    'company_name': ('name', 'company', 'company name', 'stock name'),
    'symbol': ('symbol', 'nse code', 'nse symbol', 'ticker', 'bse code'),
    'market_cap': ('market capitalization', 'market cap', 'mcap'),
    'pe': ('stock p/e', 'p/e', 'pe', 'pe ratio', 'price to earning'),
    'debt_to_equity': ('debt to equity', 'debt / equity', 'debt/equity'),
    'roce': ('return on capital employed', 'roce', 'return on capital employed %'),
    'roe': ('return on equity', 'roe', 'return on equity %'),
    'dividend_payout': ('dividend payout', 'dividend payout ratio', 'payout ratio'),
    'sales_growth': ('sales growth', 'sales growth %', 'revenue growth'),
    'profit_growth': ('profit growth', 'profit growth %', 'net profit growth'),
    'free_cashflow': ('free cash flow', 'fcf', 'free cash flow crores'),
    'promoter_holding': ('promoter holding', 'promoter holding %'),
    'pledged_percent': ('pledged percentage', 'pledged %', 'promoter shares pledged'),
    'current_price': ('current price', 'price', 'cmp', 'close'),
    'avg_volume': ('average volume', 'avg volume', 'volume', 'traded volume'),
}


def imports_file_path() -> Path:
    override = os.environ.get('SCREENER_IMPORTS_FILE', '').strip()
    return Path(override) if override else DEFAULT_IMPORTS_FILE


def stock_memory_file_path() -> Path:
    override = os.environ.get('SCREENER_STOCK_MEMORY_FILE', '').strip()
    return Path(override) if override else DEFAULT_STOCK_MEMORY_FILE


def imports_dir_path() -> Path:
    override = os.environ.get('SCREENER_IMPORTS_DIR', '').strip()
    return Path(override) if override else DEFAULT_IMPORTS_DIR


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _normalize_header(header: str) -> str:
    return re.sub(r'\s+', ' ', str(header or '').strip().lower())


def _map_headers(fieldnames: list[str] | None) -> dict[str, str]:
    """Map CSV headers to canonical field names."""
    mapping: dict[str, str] = {}
    if not fieldnames:
        return mapping
    normalized = {_normalize_header(h): h for h in fieldnames if h}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            key = _normalize_header(alias)
            if key in normalized:
                mapping[canonical] = normalized[key]
                break
    return mapping


def _normalize_symbol(value: object) -> str:
    text = str(value or '').strip().upper()
    text = re.sub(r'[^A-Z0-9&-]', '', text)
    return text


def _row_value(raw: dict[str, Any], header_map: dict[str, str], field: str) -> Any:
    src = header_map.get(field)
    if not src:
        return None
    val = raw.get(src)
    if val in (None, '', '-', 'NA', 'N/A'):
        return None
    return val


def _parse_csv_rows(path: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        header_map = _map_headers(fieldnames)
        rows = list(reader)
    return rows, fieldnames, header_map


def _normalize_stock_row(
    raw: dict[str, Any],
    header_map: dict[str, str],
    *,
    import_id: str,
    imported_at: str,
    screen_name: str,
) -> dict[str, Any] | None:
    sym = _normalize_symbol(_row_value(raw, header_map, 'symbol'))
    if not sym:
        name_val = _row_value(raw, header_map, 'company_name')
        if name_val:
            sym = _normalize_symbol(str(name_val).split()[0])
    if not sym:
        return None

    base = {
        'import_id': import_id,
        'imported_at': imported_at,
        'symbol': sym,
        'company_name': str(_row_value(raw, header_map, 'company_name') or sym),
        'market_cap': _row_value(raw, header_map, 'market_cap'),
        'pe': _row_value(raw, header_map, 'pe'),
        'debt_to_equity': _row_value(raw, header_map, 'debt_to_equity'),
        'roce': _row_value(raw, header_map, 'roce'),
        'roe': _row_value(raw, header_map, 'roe'),
        'dividend_payout': _row_value(raw, header_map, 'dividend_payout'),
        'sales_growth': _row_value(raw, header_map, 'sales_growth'),
        'profit_growth': _row_value(raw, header_map, 'profit_growth'),
        'free_cashflow': _row_value(raw, header_map, 'free_cashflow'),
        'promoter_holding': _row_value(raw, header_map, 'promoter_holding'),
        'pledged_percent': _row_value(raw, header_map, 'pledged_percent'),
        'current_price': _row_value(raw, header_map, 'current_price'),
        'avg_volume': _row_value(raw, header_map, 'avg_volume'),
        'screen_name': screen_name,
    }
    scored = score_longterm_stock(base)
    base.update(scored)
    return base


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')


def _load_jsonl(path: Path, limit: int = 10000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows[-limit:]


def append_screener_import(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.setdefault('import_id', uuid.uuid4().hex)
    _append_jsonl(imports_file_path(), payload)
    return payload


def append_stock_memory(record: dict[str, Any]) -> dict[str, Any]:
    _append_jsonl(stock_memory_file_path(), dict(record))
    return record


def load_screener_imports(limit: int = 50) -> list[dict[str, Any]]:
    rows = _load_jsonl(imports_file_path(), limit=limit)
    rows.sort(key=lambda r: str(r.get('imported_at') or ''), reverse=True)
    return rows[:limit]


def load_stock_memory(symbol: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    sym = _normalize_symbol(symbol) if symbol else ''
    rows = _load_jsonl(stock_memory_file_path(), limit=10000)
    rows.sort(key=lambda r: str(r.get('imported_at') or ''), reverse=True)
    if sym:
        rows = [r for r in rows if _normalize_symbol(r.get('symbol')) == sym]
    return rows[:limit]


def latest_import() -> dict[str, Any] | None:
    imports = load_screener_imports(limit=1)
    return imports[0] if imports else None


def latest_import_stocks(limit: int = 500) -> list[dict[str, Any]]:
    imp = latest_import()
    if not imp:
        return []
    import_id = str(imp.get('import_id') or '')
    rows = load_stock_memory(limit=5000)
    matched = [r for r in rows if str(r.get('import_id') or '') == import_id]
    matched.sort(key=lambda r: int(r.get('longterm_score') or 0), reverse=True)
    return matched[:limit]


def screener_status() -> dict[str, Any]:
    imp = latest_import()
    all_stocks = _load_jsonl(stock_memory_file_path(), limit=100000)
    symbols = {_normalize_symbol(r.get('symbol')) for r in all_stocks if _normalize_symbol(r.get('symbol'))}
    return {
        'latest_import': imp,
        'total_stocks': len(symbols),
        'total_records': len(all_stocks),
    }


def summarize_symbol_screener(symbol: str) -> dict[str, Any]:
    sym = _normalize_symbol(symbol)
    rows = load_stock_memory(symbol=sym, limit=50)
    if not rows:
        return {'symbol': sym, 'count': 0}
    latest = rows[0]
    return {
        'symbol': sym,
        'count': len(rows),
        'latest': latest,
        'imported_at': str(latest.get('imported_at') or ''),
        'screen_name': str(latest.get('screen_name') or ''),
        'longterm_score': int(latest.get('longterm_score') or 0),
        'verdict': str(latest.get('verdict') or 'unknown'),
        'reasons': list(latest.get('reasons') or [])[:5],
        'risk_flags': list(latest.get('risk_flags') or [])[:5],
        'cap_bucket': str(latest.get('cap_bucket') or 'unknown'),
    }


def import_screener_csv(
    filepath: Path | str,
    *,
    screen_name: str = '',
    query_text: str = '',
    notes: str = '',
) -> dict[str, Any]:
    """
    Import Screener CSV into memory stores.

    Does not create intraday tradecards.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f'Screener CSV not found: {path}')

    raw_rows, fieldnames, header_map = _parse_csv_rows(path)
    ist_now = _now_ist()
    import_id = uuid.uuid4().hex
    imported_at = ist_now.replace(microsecond=0).isoformat()
    screen = str(screen_name or path.stem).strip() or 'screener_import'
    query = str(query_text or screen).strip()

    import_record = {
        'import_id': import_id,
        'imported_at': imported_at,
        'current_ist': ist_now.strftime('%Y-%m-%d %H:%M IST'),
        'screen_name': screen,
        'query_text': query,
        'source': 'screener_csv',
        'filename': path.name,
        'row_count': len(raw_rows),
        'normalized_columns': sorted(header_map.keys()),
        'notes': notes,
    }
    append_screener_import(import_record)

    stored: list[dict[str, Any]] = []
    for raw in raw_rows:
        stock = _normalize_stock_row(
            raw,
            header_map,
            import_id=import_id,
            imported_at=imported_at,
            screen_name=screen,
        )
        if stock:
            append_stock_memory(stock)
            stored.append(stock)

    return {
        'ok': True,
        'import': import_record,
        'stored_count': len(stored),
        'skipped': max(0, len(raw_rows) - len(stored)),
    }


def resolve_import_filepath(filename: str) -> Path:
    """Resolve CSV path under imports dir."""
    name = Path(str(filename or '').strip()).name
    if not name:
        raise ValueError('filename required')
    if not name.lower().endswith('.csv'):
        name = f'{name}.csv'
    return imports_dir_path() / name
