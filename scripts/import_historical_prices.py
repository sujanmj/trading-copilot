#!/usr/bin/env python3
"""
Import historical OHLCV prices into historical_market_memory.db.

Angel first for INDIA if available, yfinance fallback (.NS).
USA uses yfinance direct.
Rejects NaN OHLCV; fake_prices=0 only.

Usage:
  python scripts/import_historical_prices.py --tickers RELIANCE,TCS --market INDIA --from 2026-05-01 --to 2026-05-30
  python scripts/import_historical_prices.py --tickers RELIANCE --market INDIA --from 2026-05-01 --to 2026-05-30 --dry-run
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os
    os.chdir(PROJECT_ROOT)


def _normalize_ticker(ticker: str) -> str:
    from backend.analytics.historical_symbol_mapping import normalize_historical_ticker

    return normalize_historical_ticker(ticker)


def _yfinance_symbol(ticker: str, market: str) -> str:
    from backend.analytics.historical_symbol_mapping import resolve_yfinance_symbol

    return resolve_yfinance_symbol(ticker, market)


def _parse_tickers(raw: str) -> list[str]:
    return [_normalize_ticker(part) for part in raw.split(',') if part.strip()]


def _timestamp_utc_date(ts: int | float) -> str:
    """Convert Unix timestamp to YYYY-MM-DD in UTC (Python 3.11 compatible)."""
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%d')


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _load_cached_candles(
    ticker: str,
    market: str,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """Load existing OHLCV rows from historical_market_memory.db (read-only)."""
    from backend.storage.historical_market_store import get_prices

    rows = get_prices(
        market=market,
        ticker=_normalize_ticker(ticker),
        from_date=from_date,
        to_date=to_date,
    )
    candles: list[dict] = []
    for row in rows:
        candles.append({
            'date': row.get('date'),
            'open': row.get('open'),
            'high': row.get('high'),
            'low': row.get('low'),
            'close': row.get('close'),
            'volume': row.get('volume'),
            'source': f"cache:{row.get('source') or 'historical_db'}",
        })
    return candles


def _discover_fetchers() -> dict[str, Any]:
    fetchers: dict[str, Any] = {'angel': None, 'yfinance': None}
    try:
        from backend.utils.angel_one_client import is_configured

        fetchers['angel'] = {'is_configured': is_configured}
    except Exception as exc:
        fetchers['angel_error'] = str(exc)
    return fetchers


def _fetch_angel_daily_candles(
    ticker: str,
    from_date: str,
    to_date: str,
    *,
    verbose: bool,
) -> list[dict]:
    try:
        from backend.utils.angel_one_client import is_configured

        if not is_configured():
            return []
        from SmartApi import SmartConnect
        import pyotp
        import requests
        from backend.utils.config import get_env
    except Exception:
        return []

    from backend.analytics.historical_symbol_mapping import is_index_ticker

    clean = _normalize_ticker(ticker)
    if is_index_ticker(clean):
        return []
    try:
        obj = SmartConnect(api_key=get_env('ANGEL_API_KEY'))
        totp = pyotp.TOTP(get_env('ANGEL_TOTP_SECRET')).now()
        session = obj.generateSession(get_env('ANGEL_CLIENT_ID'), get_env('ANGEL_PIN'), totp)
        if session.get('status') is False:
            return []

        url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
        instruments = requests.get(url, timeout=20).json()
        token = None
        for item in instruments:
            if item.get('exch_seg') == 'NSE' and item.get('symbol') == f'{clean}-EQ':
                token = item.get('token')
                break
        if not token:
            if verbose:
                print(f'[HISTORICAL_IMPORT] angel token miss {clean}')
            return []

        from_dt = f'{from_date} 09:00'
        to_dt = f'{to_date} 15:30'
        payload = {
            'exchange': 'NSE',
            'symboltoken': token,
            'interval': 'ONE_DAY',
            'fromdate': from_dt,
            'todate': to_dt,
        }
        response = obj.getCandleData(payload)
        if not response or not response.get('status'):
            if verbose:
                print(f'[HISTORICAL_IMPORT] angel candle miss {clean}')
            return []

        rows: list[dict] = []
        for item in response.get('data') or []:
            if not isinstance(item, list) or len(item) < 6:
                continue
            ts = datetime.fromtimestamp(float(item[0]) / 1000.0)
            open_val = _safe_float(item[1])
            high_val = _safe_float(item[2])
            low_val = _safe_float(item[3])
            close_val = _safe_float(item[4])
            volume_val = _safe_float(item[5])
            if None in (open_val, high_val, low_val, close_val, volume_val):
                continue
            rows.append({
                'date': ts.strftime('%Y-%m-%d'),
                'open': open_val,
                'high': high_val,
                'low': low_val,
                'close': close_val,
                'volume': volume_val,
                'source': 'angel_one',
            })
        if verbose and rows:
            print(f'[HISTORICAL_IMPORT] angel ok {clean} rows={len(rows)}')
        return rows
    except Exception as exc:
        if verbose:
            print(f'[HISTORICAL_IMPORT] angel error {clean}: {exc}')
        return []


def _fetch_yahoo_chart_daily_candles(
    ticker: str,
    market: str,
    from_date: str,
    to_date: str,
    *,
    verbose: bool,
) -> list[dict]:
    """Fetch daily OHLCV via Yahoo chart API (no yfinance dependency)."""
    import requests

    symbol = _yfinance_symbol(ticker, market)
    try:
        start_ts = int(datetime.strptime(from_date, '%Y-%m-%d').timestamp())
        end_ts = int(
            (datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)).timestamp()
        )
    except ValueError:
        return []

    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    params = {
        'period1': start_ts,
        'period2': end_ts,
        'interval': '1d',
        'includePrePost': 'false',
    }
    headers = {'User-Agent': 'trading-copilot-historical-import/1.0'}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        if verbose:
            print(f'[HISTORICAL_IMPORT] yahoo_chart error {symbol}: {exc}')
        return []

    chart = (payload.get('chart') or {}).get('result') or []
    if not chart:
        if verbose:
            print(f'[HISTORICAL_IMPORT] yahoo_chart miss {symbol}')
        return []

    block = chart[0]
    timestamps = block.get('timestamp') or []
    quote = (block.get('indicators') or {}).get('quote') or [{}]
    q = quote[0] if quote else {}

    rows: list[dict] = []
    for idx, ts in enumerate(timestamps):
        try:
            open_val = (q.get('open') or [None])[idx]
            high_val = (q.get('high') or [None])[idx]
            low_val = (q.get('low') or [None])[idx]
            close_val = (q.get('close') or [None])[idx]
            volume_val = (q.get('volume') or [None])[idx]
        except (IndexError, TypeError):
            continue
        open_num = _safe_float(open_val)
        high_num = _safe_float(high_val)
        low_num = _safe_float(low_val)
        close_num = _safe_float(close_val)
        volume_num = _safe_float(volume_val if volume_val is not None else 0.0)
        if None in (open_num, high_num, low_num, close_num, volume_num):
            continue
        rows.append({
            'date': _timestamp_utc_date(ts),
            'open': open_num,
            'high': high_num,
            'low': low_num,
            'close': close_num,
            'volume': volume_num,
            'source': f'yahoo_chart:{symbol}',
        })

    if verbose and rows:
        print(f'[HISTORICAL_IMPORT] yahoo_chart ok {symbol} rows={len(rows)}')
    return rows


def _fetch_yfinance_daily_candles(
    ticker: str,
    market: str,
    from_date: str,
    to_date: str,
    *,
    verbose: bool,
) -> list[dict]:
    rows = _fetch_yahoo_chart_daily_candles(
        ticker,
        market,
        from_date,
        to_date,
        verbose=verbose,
    )
    if rows:
        return rows

    try:
        import yfinance as yf
    except Exception:
        if verbose:
            print('[HISTORICAL_IMPORT] yfinance unavailable')
        return []

    symbol = _yfinance_symbol(ticker, market)
    end_exclusive = (
        datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)
    ).strftime('%Y-%m-%d')

    try:
        hist = yf.Ticker(symbol).history(start=from_date, end=end_exclusive, auto_adjust=False)
    except Exception as exc:
        if verbose:
            print(f'[HISTORICAL_IMPORT] yfinance error {symbol}: {exc}')
        return []

    if hist is None or hist.empty:
        if verbose:
            print(f'[HISTORICAL_IMPORT] yfinance miss {symbol}')
        return []

    out: list[dict] = []
    for idx, row in hist.iterrows():
        candle = {
            'date': idx.strftime('%Y-%m-%d'),
            'open': row['Open'],
            'high': row['High'],
            'low': row['Low'],
            'close': row['Close'],
            'volume': row.get('Volume') if row.get('Volume') is not None else 0.0,
            'source': f'yfinance:{symbol}',
        }
        open_num = _safe_float(candle['open'])
        high_num = _safe_float(candle['high'])
        low_num = _safe_float(candle['low'])
        close_num = _safe_float(candle['close'])
        volume_num = _safe_float(candle['volume'])
        if None in (open_num, high_num, low_num, close_num, volume_num):
            continue
        out.append({
            'date': candle['date'],
            'open': open_num,
            'high': high_num,
            'low': low_num,
            'close': close_num,
            'volume': volume_num,
            'source': candle['source'],
        })
    if verbose and out:
        print(f'[HISTORICAL_IMPORT] yfinance ok {symbol} rows={len(out)}')
    return out


def fetch_ticker_candles(
    ticker: str,
    market: str,
    from_date: str,
    to_date: str,
    fetchers: dict[str, Any],
    *,
    verbose: bool,
) -> tuple[list[dict], str | None]:
    """Return (rows, fetcher_name)."""
    from backend.analytics.historical_symbol_mapping import is_index_ticker

    market = str(market).strip().upper()
    if market == 'INDIA' and fetchers.get('angel') and not is_index_ticker(ticker):
        rows = _fetch_angel_daily_candles(ticker, from_date, to_date, verbose=verbose)
        if rows:
            return rows, 'angel_one'

    rows = _fetch_yfinance_daily_candles(
        ticker,
        market,
        from_date,
        to_date,
        verbose=verbose,
    )
    if rows:
        return rows, 'yfinance'
    return [], None


def run_import(
    *,
    tickers: list[str],
    market: str,
    from_date: str,
    to_date: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    from backend.storage.historical_market_store import get_stats, init_db, upsert_prices
    from backend.storage.historical_outcome_replay import is_valid_ohlcv_row

    init_db()
    fetchers = _discover_fetchers()
    result: dict[str, Any] = {
        'dry_run': dry_run,
        'market': market,
        'from_date': from_date,
        'to_date': to_date,
        'tickers': tickers,
        'stats_before': get_stats(),
        'rows_fetched': 0,
        'cache_rows': 0,
        'rows_valid': 0,
        'rows_written': 0,
        'rows_rejected_nan': 0,
        'fake_prices': 0,
        'failed_tickers': [],
        'fetcher_hits': {},
    }

    all_rows: list[dict] = []
    for ticker in tickers:
        candles, fetcher = fetch_ticker_candles(
            ticker,
            market,
            from_date,
            to_date,
            fetchers,
            verbose=verbose,
        )
        from_cache = False
        if not candles:
            candles = _load_cached_candles(ticker, market, from_date, to_date)
            from_cache = bool(candles)

        if not candles:
            result['failed_tickers'].append(ticker)
            continue

        if from_cache:
            result['cache_rows'] += len(candles)
            if verbose:
                print(f'[HISTORICAL_IMPORT] cache hit {ticker} rows={len(candles)}')
        else:
            result['fetcher_hits'][fetcher or 'unknown'] = (
                result['fetcher_hits'].get(fetcher or 'unknown', 0) + 1
            )
            result['rows_fetched'] += len(candles)

        for candle in candles:
            row = {
                'market': market,
                'ticker': _normalize_ticker(ticker),
                'date': candle['date'],
                'source': candle['source'],
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close'],
                'volume': candle['volume'],
                'fake_prices': 0,
            }
            if not is_valid_ohlcv_row(row):
                result['rows_rejected_nan'] += 1
                continue
            all_rows.append(row)
            result['rows_valid'] += 1

    if dry_run:
        result['stats_after'] = get_stats()
        return result

    result['rows_written'] = upsert_prices(all_rows)
    result['stats_after'] = get_stats()
    return result


def print_summary(result: dict[str, Any]) -> None:
    print(f'[HISTORICAL_IMPORT] market={result["market"]}')
    print(f'[HISTORICAL_IMPORT] tickers={",".join(result["tickers"])}')
    print(f'[HISTORICAL_IMPORT] from={result["from_date"]} to={result["to_date"]}')
    print(f'[HISTORICAL_IMPORT] rows_fetched={result["rows_fetched"]}')
    print(f'[HISTORICAL_IMPORT] cache_rows={result.get("cache_rows", 0)}')
    print(f'[HISTORICAL_IMPORT] rows_valid={result["rows_valid"]}')
    print(f'[HISTORICAL_IMPORT] rows_written={result["rows_written"]}')
    print(f'[HISTORICAL_IMPORT] rows_rejected_nan={result["rows_rejected_nan"]}')
    print(f'[HISTORICAL_IMPORT] fake_prices={result["fake_prices"]}')
    if result.get('fetcher_hits'):
        print(f'[HISTORICAL_IMPORT] fetcher_hits={result["fetcher_hits"]}')
    if result.get('failed_tickers'):
        print(f'[HISTORICAL_IMPORT] failed_tickers={result["failed_tickers"]}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Import historical OHLCV prices.')
    parser.add_argument('--tickers', required=True, help='Comma-separated tickers')
    parser.add_argument('--market', required=True, choices=('INDIA', 'USA'))
    parser.add_argument('--from', dest='from_date', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--to', dest='to_date', required=True, help='End date YYYY-MM-DD')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    tickers = _parse_tickers(args.tickers)
    if not tickers:
        print('HISTORICAL_PRICES_IMPORT_FAIL: no tickers', file=sys.stderr)
        return 1

    result = run_import(
        tickers=tickers,
        market=args.market,
        from_date=args.from_date,
        to_date=args.to_date,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    print_summary(result)

    if result['fake_prices'] != 0:
        print('HISTORICAL_PRICES_IMPORT_FAIL: fake_prices must be 0', file=sys.stderr)
        return 1

    print('HISTORICAL_PRICES_IMPORT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
