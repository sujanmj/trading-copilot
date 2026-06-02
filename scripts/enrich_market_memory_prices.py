#!/usr/bin/env python3
"""
Enrich latest price coverage for market memory tickers using real project fetchers.

Reads unique tickers from canonical_market_memory.db (read-only), merges existing
data/latest_market_data.json prices with newly fetched real prices, and writes
data/latest_market_data_memory_enriched.json.

Usage:
  python scripts/enrich_market_memory_prices.py --dry-run --limit 20
  python scripts/enrich_market_memory_prices.py --limit 50
  python scripts/enrich_market_memory_prices.py --limit 50 --promote
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.storage.market_memory_outcomes import (
    LATEST_MARKET_DATA_PATH,
    load_latest_market_data,
    lookup_latest_price,
)
from backend.utils.config import DATA_DIR
from backend.utils.market_data_validator import validate_price_row
from scripts.audit_price_coverage import build_ticker_variants, lookup_price_with_variants

ENRICHED_OUTPUT_PATH = DATA_DIR / 'latest_market_data_memory_enriched.json'
TEST_TICKER_PREFIX = '__TEST__'


def _normalize_storage_symbol(ticker: str) -> str:
    """Canonical symbol key for latest_market_data prices dict."""
    raw = str(ticker or '').strip().upper()
    if raw.startswith('NSE:'):
        raw = raw[4:]
    if raw.endswith('-EQ'):
        raw = raw[:-3]
    if raw.endswith('.NS') or raw.endswith('.BO'):
        raw = raw.rsplit('.', 1)[0]
    return raw


def _yfinance_ticker(symbol: str) -> str:
    clean = _normalize_storage_symbol(symbol)
    if clean.startswith('^') or ' ' in clean:
        return clean
    return f'{clean}.NS'


def fetch_memory_tickers(*, limit: int | None = None) -> list[str]:
    """Return unique prediction tickers from canonical DB (read-only)."""
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    init_market_memory_db()
    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        query = """
            SELECT DISTINCT ticker
            FROM predictions
            WHERE ticker IS NOT NULL
              AND TRIM(ticker) != ''
              AND ticker NOT LIKE ?
            ORDER BY ticker ASC
        """
        params: list[Any] = [f'{TEST_TICKER_PREFIX}%']
        if limit is not None and limit > 0:
            query += ' LIMIT ?'
            params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    tickers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        symbol = _normalize_storage_symbol(row['ticker'])
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        tickers.append(symbol)
    return tickers


def ticker_has_price(market_data: dict, ticker: str) -> bool:
    for variant in build_ticker_variants(ticker):
        if lookup_latest_price(market_data, variant) is not None:
            return True
    return False


def _discover_fetchers() -> dict[str, Any]:
    """Wire available project fetchers; import failures are non-fatal."""
    fetchers: dict[str, Any] = {
        'angel': None,
        'yfinance': None,
        'scanner_cache': None,
    }

    try:
        from backend.utils.angel_one_client import fetch_ltp, is_configured

        fetchers['angel'] = {'fetch_ltp': fetch_ltp, 'is_configured': is_configured}
    except Exception as exc:
        fetchers['angel_error'] = str(exc)

    try:
        from backend.collectors.collector import fetch_symbol_yfinance

        fetchers['yfinance'] = {'fetch_symbol_yfinance': fetch_symbol_yfinance}
    except Exception as exc:
        fetchers['yfinance_error'] = str(exc)

    scanner_path = DATA_DIR / 'scanner_data.json'
    if scanner_path.is_file():
        fetchers['scanner_cache'] = {'path': scanner_path}
    return fetchers


def _load_scanner_price_index(path: Path) -> dict[str, float]:
    """Build symbol -> price index from existing scanner_data.json (if present)."""
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}

    index: dict[str, float] = {}
    if not isinstance(data, dict):
        return index

    candidates: list[Any] = []
    for key in ('signals', 'opportunities', 'stocks', 'results'):
        block = data.get(key)
        if isinstance(block, list):
            candidates.extend(block)
        elif isinstance(block, dict):
            candidates.extend(block.values())

    for item in candidates:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_storage_symbol(
            str(item.get('ticker') or item.get('symbol') or item.get('name') or ''),
        )
        if not symbol:
            continue
        for field in ('price', 'ltp', 'close', 'last_price'):
            val = item.get(field)
            if val is None:
                continue
            try:
                price = float(val)
            except (TypeError, ValueError):
                continue
            if price > 0:
                index[symbol] = price
                break
    return index


def _fetch_via_angel(fetchers: dict[str, Any], symbol: str, *, verbose: bool) -> dict | None:
    angel = fetchers.get('angel')
    if not angel or not angel['is_configured']():
        return None
    price, tag = angel['fetch_ltp'](symbol)
    if price is None or price <= 0:
        if verbose:
            print(f'[PRICE_ENRICH] angel miss {symbol} tag={tag}')
        return None
    row = {
        'price': round(float(price), 2),
        'change_percent': 0.0,
        'source': 'angel_one',
    }
    ok, reason, cleaned = validate_price_row(row, symbol_name=symbol)
    if ok and cleaned:
        if verbose:
            print(f'[PRICE_ENRICH] angel ok {symbol} price={cleaned["price"]}')
        return cleaned
    if verbose:
        print(f'[PRICE_ENRICH] angel reject {symbol} reason={reason}')
    return None


def _fetch_via_yfinance(fetchers: dict[str, Any], symbol: str, *, verbose: bool) -> dict | None:
    yf_mod = fetchers.get('yfinance')
    if not yf_mod:
        return None
    yf_ticker = _yfinance_ticker(symbol)
    try:
        row = yf_mod['fetch_symbol_yfinance'](symbol, yf_ticker)
    except Exception as exc:
        if verbose:
            print(f'[PRICE_ENRICH] yfinance error {symbol}: {exc}')
        return None
    if not row:
        if verbose:
            print(f'[PRICE_ENRICH] yfinance miss {symbol}')
        return None
    ok, reason, cleaned = validate_price_row(row, symbol_name=symbol)
    if ok and cleaned:
        if verbose:
            print(f'[PRICE_ENRICH] yfinance ok {symbol} price={cleaned["price"]}')
        return cleaned
    if verbose:
        print(f'[PRICE_ENRICH] yfinance reject {symbol} reason={reason}')
    return None


def _fetch_via_scanner_cache(
    fetchers: dict[str, Any],
    symbol: str,
    scanner_index: dict[str, float],
    *,
    verbose: bool,
) -> dict | None:
    if not fetchers.get('scanner_cache'):
        return None
    price = scanner_index.get(symbol)
    if price is None:
        for variant in build_ticker_variants(symbol):
            norm = _normalize_storage_symbol(variant)
            price = scanner_index.get(norm)
            if price is not None:
                break
    if price is None or price <= 0:
        return None
    row = {
        'price': round(float(price), 2),
        'change_percent': 0.0,
        'source': 'scanner_data.json',
    }
    ok, reason, cleaned = validate_price_row(row, symbol_name=symbol)
    if ok and cleaned:
        if verbose:
            print(f'[PRICE_ENRICH] scanner_cache ok {symbol} price={cleaned["price"]}')
        return cleaned
    if verbose:
        print(f'[PRICE_ENRICH] scanner_cache reject {symbol} reason={reason}')
    return None


def fetch_real_price(
    symbol: str,
    fetchers: dict[str, Any],
    scanner_index: dict[str, float],
    *,
    verbose: bool,
) -> tuple[dict | None, str | None]:
    """Try Angel -> yfinance -> scanner cache. Returns (price_row, fetcher_name)."""
    row = _fetch_via_angel(fetchers, symbol, verbose=verbose)
    if row:
        return row, 'angel'

    row = _fetch_via_yfinance(fetchers, symbol, verbose=verbose)
    if row:
        return row, 'yfinance'

    row = _fetch_via_scanner_cache(fetchers, symbol, scanner_index, verbose=verbose)
    if row:
        return row, 'scanner_cache'

    return None, None


def _load_existing_enriched_prices() -> dict[str, dict]:
    if not ENRICHED_OUTPUT_PATH.is_file():
        return {}
    try:
        data = json.loads(ENRICHED_OUTPUT_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    prices = data.get('prices') if isinstance(data, dict) else None
    return dict(prices) if isinstance(prices, dict) else {}


def _load_enriched_peak_symbols() -> int:
    """Return tracked peak symbol count from enriched file metadata (or current count)."""
    if not ENRICHED_OUTPUT_PATH.is_file():
        return 0
    try:
        data = json.loads(ENRICHED_OUTPUT_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    prices = data.get('prices')
    current = len(prices) if isinstance(prices, dict) else 0
    meta = data.get('enrichment_meta')
    if isinstance(meta, dict) and meta.get('peak_symbols') is not None:
        try:
            return max(int(meta['peak_symbols']), current)
        except (TypeError, ValueError):
            pass
    return current


def merge_prices_preserve_coverage(
    existing_prices: dict[str, dict],
    new_prices: dict[str, dict],
) -> tuple[dict[str, dict], int]:
    """Merge new prices into existing; never drop symbols when new set is smaller."""
    merged = {**existing_prices, **new_prices}
    preserved_existing = sum(1 for sym in existing_prices if sym not in new_prices)
    return merged, preserved_existing


def build_enriched_snapshot(
    base_data: dict,
    newly_fetched: dict[str, dict],
    *,
    existing_enriched_prices: dict[str, dict] | None = None,
) -> dict:
    """Merge base snapshot with newly fetched prices; preserve resolver-compatible shape."""
    output = copy.deepcopy(base_data) if base_data else {}
    prices = output.get('prices')
    if not isinstance(prices, dict):
        prices = {}
    merged_prices = dict(prices)
    if existing_enriched_prices:
        merged_prices = {**existing_enriched_prices, **merged_prices}
    now = datetime.now().isoformat()

    for symbol, row in newly_fetched.items():
        entry = dict(row)
        entry.setdefault('validated_at', now)
        merged_prices[symbol] = entry

    output['prices'] = merged_prices
    output['last_updated'] = now
    output.setdefault('market_period', base_data.get('market_period', 'post_market'))
    output['symbols_ok'] = len(merged_prices)
    prev_peak = _load_enriched_peak_symbols()
    peak_symbols = max(prev_peak, len(merged_prices))
    output['enrichment_meta'] = {
        'source_script': 'enrich_market_memory_prices.py',
        'enriched_at': now,
        'new_symbols_added': len(newly_fetched),
        'base_symbols': len(prices),
        'peak_symbols': peak_symbols,
    }
    return output


def run_enrichment(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    promote: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    fetchers = _discover_fetchers()
    scanner_index: dict[str, float] = {}
    if fetchers.get('scanner_cache'):
        scanner_index = _load_scanner_price_index(fetchers['scanner_cache']['path'])

    memory_tickers = fetch_memory_tickers(limit=limit)
    base_data = load_latest_market_data() or {'prices': {}}
    existing_enriched_prices = _load_existing_enriched_prices()
    existing_prices = base_data.get('prices') if isinstance(base_data.get('prices'), dict) else {}

    missing: list[str] = []
    for ticker in memory_tickers:
        if not ticker_has_price(base_data, ticker):
            missing.append(ticker)

    newly_fetched: dict[str, dict] = {}
    failed: list[str] = []
    fetcher_hits: dict[str, int] = {'angel': 0, 'yfinance': 0, 'scanner_cache': 0}

    if verbose:
        wired = []
        if fetchers.get('angel'):
            wired.append('angel')
        if fetchers.get('yfinance'):
            wired.append('yfinance')
        if fetchers.get('scanner_cache'):
            wired.append('scanner_cache')
        print(f'[PRICE_ENRICH] fetchers_wired={wired}')

    for symbol in missing:
        if dry_run:
            if verbose:
                print(f'[PRICE_ENRICH] dry-run would fetch {symbol}')
            continue

        row, fetcher = fetch_real_price(
            symbol,
            fetchers,
            scanner_index,
            verbose=verbose,
        )
        if row and fetcher:
            storage_key = _normalize_storage_symbol(symbol)
            newly_fetched[storage_key] = row
            fetcher_hits[fetcher] = fetcher_hits.get(fetcher, 0) + 1
        else:
            failed.append(symbol)

    output_path = ENRICHED_OUTPUT_PATH
    promoted = False

    preserved_existing = 0
    final_symbols = 0

    if not dry_run:
        enriched = build_enriched_snapshot(
            base_data,
            newly_fetched,
            existing_enriched_prices=existing_enriched_prices,
        )
        new_prices = enriched.get('prices') if isinstance(enriched.get('prices'), dict) else {}
        if existing_enriched_prices:
            merged_prices, preserved_existing = merge_prices_preserve_coverage(
                existing_enriched_prices,
                new_prices,
            )
            enriched['prices'] = merged_prices
            enriched['symbols_ok'] = len(merged_prices)
        final_symbols = len(enriched.get('prices') or {})
        prev_peak = _load_enriched_peak_symbols()
        if prev_peak and final_symbols < prev_peak:
            print('[PRICE_ENRICH] coverage_below_previous_peak')
        print(f'[PRICE_ENRICH] preserved_existing={preserved_existing}')
        print(f'[PRICE_ENRICH] final_symbols={final_symbols}')
        print(f'[PRICE_ENRICH] peak_symbols={enriched.get("enrichment_meta", {}).get("peak_symbols", final_symbols)}')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(enriched, indent=2, default=str),
            encoding='utf-8',
        )
        if promote:
            shutil.copy2(output_path, LATEST_MARKET_DATA_PATH)
            promoted = True

    result = {
        'memory_tickers': len(memory_tickers),
        'existing_prices': len(existing_prices),
        'existing_enriched_prices': len(existing_enriched_prices),
        'missing_before': len(missing),
        'fetched_real': len(newly_fetched),
        'failed': len(failed) if not dry_run else len(missing),
        'fake_prices': 0,
        'preserved_existing': preserved_existing,
        'final_symbols': final_symbols,
        'output': str(output_path.relative_to(PROJECT_ROOT)).replace('\\', '/'),
        'promoted': promoted,
        'dry_run': dry_run,
        'fetcher_hits': fetcher_hits,
        'failed_symbols': failed[:20],
        'sample_fetched': {
            k: v.get('price')
            for k, v in list(newly_fetched.items())[:5]
        },
    }
    return result


def print_summary(result: dict[str, Any]) -> None:
    print(f'[PRICE_ENRICH] memory_tickers={result["memory_tickers"]}')
    print(f'[PRICE_ENRICH] existing_prices={result["existing_prices"]}')
    if result.get('existing_enriched_prices') is not None:
        print(f'[PRICE_ENRICH] existing_enriched_prices={result["existing_enriched_prices"]}')
    if not result.get('dry_run'):
        print(f'[PRICE_ENRICH] preserved_existing={result.get("preserved_existing", 0)}')
        print(f'[PRICE_ENRICH] final_symbols={result.get("final_symbols", 0)}')
    print(f'[PRICE_ENRICH] fetched_real={result["fetched_real"]}')
    print(f'[PRICE_ENRICH] failed={result["failed"]}')
    print(f'[PRICE_ENRICH] fake_prices={result["fake_prices"]}')
    print(f'[PRICE_ENRICH] output={result["output"]}')
    print(f'[PRICE_ENRICH] promoted={result["promoted"]}')
    if result.get('fetcher_hits'):
        hits = result['fetcher_hits']
        active = {k: v for k, v in hits.items() if v}
        if active:
            print(f'[PRICE_ENRICH] fetcher_hits={active}')
    if result.get('sample_fetched'):
        print(f'[PRICE_ENRICH] sample_fetched={result["sample_fetched"]}')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Enrich latest_market_data prices for market memory tickers (real fetchers only)',
    )
    parser.add_argument('--dry-run', action='store_true', help='List tickers to fetch; no file write')
    parser.add_argument('--limit', type=int, default=None, help='Limit unique tickers from DB')
    parser.add_argument(
        '--promote',
        action='store_true',
        help='Copy enriched output to data/latest_market_data.json',
    )
    parser.add_argument('--verbose', action='store_true', help='Per-ticker fetch details')
    args = parser.parse_args()

    if args.promote and args.dry_run:
        print('[PRICE_ENRICH] --promote ignored with --dry-run', file=sys.stderr)

    from backend.storage.market_memory_db import get_market_memory_stats

    stats_before = get_market_memory_stats()
    preds_before = int(stats_before.get('predictions') or 0)

    result = run_enrichment(
        dry_run=args.dry_run,
        limit=args.limit,
        promote=args.promote and not args.dry_run,
        verbose=args.verbose,
    )
    print_summary(result)

    stats_after = get_market_memory_stats()
    preds_after = int(stats_after.get('predictions') or 0)
    if preds_before != preds_after:
        print(
            f'[PRICE_ENRICH] warning: prediction count changed {preds_before} -> {preds_after}',
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
