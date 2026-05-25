"""
India market collector — Angel One primary, Yahoo fallback, validated output.
"""

import json
from datetime import datetime
from pathlib import Path

from backend.utils.config import DATA_DIR, MARKET_SOURCE_STATUS_FILE
from backend.utils.market_hours import get_collection_profile, get_market_period
from backend.utils.angel_one_client import fetch_ltp, get_status, is_configured
from backend.utils.market_data_validator import (
    load_previous_snapshot,
    validate_market_snapshot,
    validate_price_row,
    preserve_previous_row,
)
from backend.storage.json_io import atomic_write_json

OUTPUT_FILE = DATA_DIR / 'latest_market_data.json'

INDIA_SYMBOLS = {
    'NIFTY 50': {'ticker': '^NSEI', 'type': 'index'},
    'SENSEX': {'ticker': '^BSESN', 'type': 'index'},
    'RELIANCE': {'ticker': 'RELIANCE.NS', 'type': 'equity'},
    'TCS': {'ticker': 'TCS.NS', 'type': 'equity'},
    'HDFCBANK': {'ticker': 'HDFCBANK.NS', 'type': 'equity'},
    'INFY': {'ticker': 'INFY.NS', 'type': 'equity'},
    'ICICIBANK': {'ticker': 'ICICIBANK.NS', 'type': 'equity'},
    'SBIN': {'ticker': 'SBIN.NS', 'type': 'equity'},
    'BHARTIARTL': {'ticker': 'BHARTIARTL.NS', 'type': 'equity'},
    'ITC': {'ticker': 'ITC.NS', 'type': 'equity'},
    'LT': {'ticker': 'LT.NS', 'type': 'equity'},
    'AXISBANK': {'ticker': 'AXISBANK.NS', 'type': 'equity'},
    'KOTAKBANK': {'ticker': 'KOTAKBANK.NS', 'type': 'equity'},
    'BAJAJFINSV': {'ticker': 'BAJAJFINSV.NS', 'type': 'equity'},
    'MARUTI': {'ticker': 'MARUTI.NS', 'type': 'equity'},
}


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _fetch_yfinance_once(name, ticker):
    import yfinance as yf
    print(f"  [FETCH] {name} ({ticker}) via yfinance...")
    stock = yf.Ticker(ticker)
    hist = stock.history(period='5d')
    if hist is None or hist.empty or len(hist) < 1:
        print(f"  [FAIL] {name} ({ticker}): no yfinance history")
        return None
    close = float(hist['Close'].iloc[-1])
    prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else close
    if close != close or prev != prev:  # NaN check
        print(f"  [FAIL] {name}: NaN in yfinance data")
        return None
    change_pct = ((close - prev) / prev * 100) if prev else 0.0
    print(f"  [OK] {name} ({ticker}): Rs.{close:,.2f} ({change_pct:+.2f}%)")
    return {
        'price': round(close, 2),
        'change_percent': round(change_pct, 2),
        'source': f'yfinance:{ticker}',
    }


def fetch_symbol_yfinance(name, ticker):
    try:
        row = _fetch_yfinance_once(name, ticker)
        if row:
            return row
        if ticker.endswith('.NS'):
            bo_ticker = ticker[:-3] + '.BO'
            print(f"  [RETRY] {name}: .NS failed, trying BSE {bo_ticker}...")
            return _fetch_yfinance_once(name, bo_ticker)
        return None
    except Exception as e:
        print(f"  [FAIL] {name} ({ticker}) yfinance error: {e}")
        return None


def _build_row_from_ltp(name: str, price: float, source: str, previous_row: dict) -> dict:
    prev_price = (previous_row or {}).get('price')
    if prev_price and float(prev_price) > 0:
        change_pct = ((price - float(prev_price)) / float(prev_price)) * 100
    else:
        change_pct = 0.0
    return {
        'price': round(price, 2),
        'change_percent': round(change_pct, 2),
        'source': source,
    }


def fetch_symbol_with_failover(name: str, spec: dict, previous_row: dict) -> tuple:
    """
    Priority: Angel One (equities) → Yahoo → preserve previous valid snapshot.
    Indices always use Yahoo (reliable for ^NSEI / ^BSESN).
    """
    ticker = spec['ticker']
    sym_type = spec.get('type', 'equity')
    stats = {'angel': 0, 'yahoo': 0, 'preserved': 0}

    row = None
    if sym_type == 'index' or ticker.startswith('^'):
        row = fetch_symbol_yfinance(name, ticker)
        if row:
            stats['yahoo'] = 1
    elif is_configured():
        clean = ticker.replace('.NS', '').replace('.BO', '')
        ltp, tag = fetch_ltp(clean)
        if ltp and ltp > 0:
            row = _build_row_from_ltp(name, ltp, 'angel_one', previous_row)
            stats['angel'] = 1
            print(f"  [OK] {name} via Angel One: Rs.{ltp:,.2f}")
        else:
            _log('DATA SOURCE FAILOVER', f'{name} Angel failed ({tag}) → Yahoo')

    if not row:
        row = fetch_symbol_yfinance(name, ticker)
        if row:
            stats['yahoo'] = 1
            row['source'] = f"yahoo_fallback:{row.get('source', ticker)}"

    ok, reason, cleaned = validate_price_row(row or {}, symbol_name=name, previous_row=previous_row)
    if ok and cleaned:
        return cleaned, stats

    if previous_row and previous_row.get('price'):
        preserved = preserve_previous_row(previous_row, reason or 'validation_failed')
        stats['preserved'] = 1
        return preserved, stats

    return None, stats


def collect_india_market_data(force: bool = False):
    """Collect India prices with source priority routing and validation."""
    profile = get_collection_profile()
    period = profile.get('period', get_market_period())
    if profile.get('lightweight_only') and not force:
        print(f"[COLLECTOR] {period} mode — lightweight India refresh only")

    print("=" * 60)
    print("INDIA MARKET COLLECTOR (Angel One primary)")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Period: {period}")
    print(f"Angel configured: {is_configured()} | {get_status()}")
    print("=" * 60)

    previous = load_previous_snapshot(OUTPUT_FILE)
    prev_prices = previous.get('prices') or {}

    prices = {}
    source_stats = {'angel_one': 0, 'yahoo_fallback': 0, 'preserved_previous': 0, 'failed': 0}

    for name, spec in INDIA_SYMBOLS.items():
        row, stats = fetch_symbol_with_failover(name, spec, prev_prices.get(name))
        if row:
            prices[name] = row
            source_stats['angel_one'] += stats.get('angel', 0)
            source_stats['yahoo_fallback'] += stats.get('yahoo', 0)
            source_stats['preserved_previous'] += stats.get('preserved', 0)
        else:
            source_stats['failed'] += 1

    raw_output = {
        'last_updated': datetime.now().isoformat(),
        'market_period': period,
        'prices': prices,
        'symbols_ok': len(prices),
        'symbols_failed': source_stats['failed'],
        'total_symbols': len(INDIA_SYMBOLS),
        'source_meta': {
            'primary_source': 'angel_one' if source_stats['angel_one'] > 0 else 'yahoo',
            'angel_one_count': source_stats['angel_one'],
            'yahoo_fallback_count': source_stats['yahoo_fallback'],
            'preserved_previous_count': source_stats['preserved_previous'],
            'degraded': source_stats['preserved_previous'] > 0 or source_stats['failed'] > 0,
        },
    }

    output, validation_meta = validate_market_snapshot(raw_output, previous_snapshot=previous, file_label='india')
    output['source_meta']['validation'] = validation_meta

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUTPUT_FILE, output)

    status = {
        'updated_at': datetime.now().isoformat(),
        'market_period': period,
        'active_source': output['source_meta'].get('primary_source'),
        'angel_one_count': source_stats['angel_one'],
        'yahoo_fallback_count': source_stats['yahoo_fallback'],
        'preserved_previous_count': source_stats['preserved_previous'],
        'degraded': output['source_meta'].get('degraded', False),
        'symbols_ok': output.get('symbols_ok', 0),
        'symbols_failed': output.get('symbols_failed', 0),
    }
    atomic_write_json(MARKET_SOURCE_STATUS_FILE, status)

    print("-" * 60)
    print(f"[SAVED] {OUTPUT_FILE}")
    print(
        f"  Angel: {source_stats['angel_one']} | Yahoo: {source_stats['yahoo_fallback']} | "
        f"Preserved: {source_stats['preserved_previous']} | Failed: {source_stats['failed']}"
    )
    print("=" * 60)
    return output


# Backward-compatible exports for other modules
def fetch_accurate_nse_price(symbol: str) -> float:
    ltp, _ = fetch_ltp(symbol)
    return ltp or 0.0


def get_stock_price(symbol):
    return fetch_accurate_nse_price(symbol)


if __name__ == '__main__':
    collect_india_market_data()
