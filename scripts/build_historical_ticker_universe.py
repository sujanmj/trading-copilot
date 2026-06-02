#!/usr/bin/env python3
"""
Build historical ticker universe from canonical memory, enriched prices, brokers, manual list.

Output: data/historical_ticker_universe.json
Prints exactly HISTORICAL_TICKER_UNIVERSE_OK on success.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.utils.config import DATA_DIR

OUTPUT_PATH = DATA_DIR / 'historical_ticker_universe.json'
MANUAL_PATH = DATA_DIR / 'historical_ticker_universe_manual.json'
ENRICHED_PATH = DATA_DIR / 'latest_market_data_memory_enriched.json'
BROKER_INBOX_PATH = DATA_DIR / 'broker_prediction_inbox.json'
TEST_PREFIX = '__TEST__'


def _fail(msg: str) -> int:
    print(f'HISTORICAL_TICKER_UNIVERSE_FAIL: {msg}', file=sys.stderr)
    return 1


def _normalize_ticker(ticker: str) -> str:
    raw = str(ticker or '').strip().upper()
    if raw.startswith('NSE:'):
        raw = raw[4:]
    if raw.endswith('-EQ'):
        raw = raw[:-3]
    if raw.endswith('.NS') or raw.endswith('.BO'):
        raw = raw.rsplit('.', 1)[0]
    return raw


def _fetch_market_memory_tickers() -> set[str]:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    init_market_memory_db()
    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = conn.execute(
            """
            SELECT DISTINCT ticker
            FROM predictions
            WHERE ticker IS NOT NULL
              AND TRIM(ticker) != ''
              AND ticker NOT LIKE ?
            """,
            (f'{TEST_PREFIX}%',),
        ).fetchall()
    finally:
        conn.close()

    out: set[str] = set()
    for row in rows:
        symbol = _normalize_ticker(row['ticker'])
        if symbol and not symbol.startswith(TEST_PREFIX):
            out.add(symbol)
    return out


def _fetch_enriched_tickers() -> set[str]:
    if not ENRICHED_PATH.is_file():
        return set()
    try:
        data = json.loads(ENRICHED_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return set()

    prices = data.get('prices') or data.get('symbols') or {}
    out: set[str] = set()
    if isinstance(prices, dict):
        for key in prices:
            symbol = _normalize_ticker(key)
            if symbol and len(symbol) >= 2 and not symbol.startswith(TEST_PREFIX):
                out.add(symbol)
    return out


def _fetch_broker_tickers() -> set[str]:
    out: set[str] = set()
    try:
        from backend.storage.market_memory_db import get_connection, init_market_memory_db

        init_market_memory_db()
        conn = get_connection()
        try:
            conn.execute('PRAGMA query_only = ON')
            tables = {
                row['name']
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if 'broker_predictions' in tables:
                rows = conn.execute(
                    """
                    SELECT DISTINCT ticker
                    FROM broker_predictions
                    WHERE ticker IS NOT NULL AND TRIM(ticker) != ''
                    """
                ).fetchall()
                for row in rows:
                    symbol = _normalize_ticker(row['ticker'])
                    if symbol and not symbol.startswith(TEST_PREFIX):
                        out.add(symbol)
        finally:
            conn.close()
    except Exception:
        pass

    if BROKER_INBOX_PATH.is_file():
        try:
            inbox = json.loads(BROKER_INBOX_PATH.read_text(encoding='utf-8'))
            items = inbox if isinstance(inbox, list) else inbox.get('items') or inbox.get('picks') or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = _normalize_ticker(item.get('ticker') or item.get('symbol') or '')
                if symbol and not symbol.startswith(TEST_PREFIX):
                    out.add(symbol)
        except (OSError, json.JSONDecodeError):
            pass

    return out


def _fetch_manual_tickers() -> set[str]:
    if not MANUAL_PATH.is_file():
        return set()
    try:
        data = json.loads(MANUAL_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return set()

    tickers = data.get('tickers') if isinstance(data, dict) else data
    out: set[str] = set()
    if isinstance(tickers, list):
        for entry in tickers:
            if isinstance(entry, str):
                symbol = _normalize_ticker(entry)
            elif isinstance(entry, dict):
                symbol = _normalize_ticker(entry.get('ticker') or entry.get('symbol') or '')
            else:
                continue
            if symbol and not symbol.startswith(TEST_PREFIX):
                out.add(symbol)
    return out


def build_universe(*, market: str = 'INDIA') -> dict[str, Any]:
    from_market = _fetch_market_memory_tickers()
    from_enriched = _fetch_enriched_tickers()
    from_brokers = _fetch_broker_tickers()
    from_manual = _fetch_manual_tickers()

    source_map = {
        'market_memory': from_market,
        'enriched_prices': from_enriched,
        'broker_predictions': from_brokers,
        'manual': from_manual,
    }

    all_tickers: set[str] = set()
    for bucket in source_map.values():
        all_tickers.update(bucket)

    entries: list[dict[str, Any]] = []
    for ticker in sorted(all_tickers):
        sources: list[str] = []
        if ticker in from_market:
            sources.append('market_memory')
        if ticker in from_enriched:
            sources.append('enriched_prices')
        if ticker in from_brokers:
            sources.append('broker_predictions')
        if ticker in from_manual:
            sources.append('manual')
        priority = max(1, 5 - len(sources))
        entries.append({
            'ticker': ticker,
            'sources': sources,
            'priority': priority,
        })

    entries.sort(key=lambda item: (item['priority'], item['ticker']))

    return {
        'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'market': market,
        'tickers': entries,
        'summary': {
            'total': len(entries),
            'from_market_memory': len(from_market),
            'from_enriched_prices': len(from_enriched),
            'from_brokers': len(from_brokers),
            'from_manual': len(from_manual),
        },
    }


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_universe(market='INDIA')
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    summary = payload['summary']
    print(f'[HISTORICAL_TICKER_UNIVERSE] total={summary["total"]}')
    print(f'[HISTORICAL_TICKER_UNIVERSE] market_memory={summary["from_market_memory"]}')
    print(f'[HISTORICAL_TICKER_UNIVERSE] enriched={summary["from_enriched_prices"]}')
    print(f'[HISTORICAL_TICKER_UNIVERSE] brokers={summary["from_brokers"]}')
    print('HISTORICAL_TICKER_UNIVERSE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
