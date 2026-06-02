#!/usr/bin/env python3
"""
Read-only audit of prediction price coverage against a market price file.

Usage:
  python scripts/audit_price_coverage.py
  python scripts/audit_price_coverage.py --limit 50
  python scripts/audit_price_coverage.py --ticker TCS --verbose
  python scripts/audit_price_coverage.py --price-file data/latest_market_data_memory_enriched.json
"""

from __future__ import annotations

import argparse
import json
import sys
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
    extract_prediction_price_context,
    load_latest_market_data,
    lookup_latest_price,
    resolve_outcome_from_prices,
)
from backend.storage.price_outcome_sanity import (
    check_price_sanity_gates,
    is_suspicious_price_scale,
    pct_move,
)

CLASSIFICATIONS = (
    'missing_price_context',
    'missing_latest_price',
    'suspicious_price_scale',
    'eligible_unresolved',
    'eligible_target_hit',
    'eligible_stop_hit',
)


def build_ticker_variants(ticker: str) -> list[str]:
    """Generate safe ticker lookup variants (uppercase, exchange suffixes, -EQ)."""
    raw = str(ticker or '').strip()
    if not raw:
        return []

    base = raw.upper()
    variants: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        key = str(value).strip().upper()
        if key and key not in seen:
            seen.add(key)
            variants.append(key)

    _add(base)
    _add(f'{base}.NS')
    _add(f'NSE:{base}')

    if base.startswith('NSE:'):
        _add(base[4:])

    if base.endswith('-EQ'):
        _add(base[:-3])
    else:
        _add(f'{base}-EQ')

    return variants


def find_price_key(data: dict, ticker: str) -> str | None:
    prices = data.get('prices')
    if not isinstance(prices, dict) or not ticker:
        return None
    symbol = str(ticker).strip().upper()
    if symbol in prices:
        return symbol
    for key in prices:
        if str(key).strip().upper() == symbol:
            return key
    return None


def lookup_price_with_variants(
    data: dict,
    ticker: str,
) -> tuple[float | None, str | None, str | None]:
    """Return (price, matched_prices_key, matched_variant)."""
    for variant in build_ticker_variants(ticker):
        price = lookup_latest_price(data, variant)
        if price is not None:
            matched_key = find_price_key(data, variant)
            return price, matched_key, variant
    return None, None, None


def _row_to_dict(row: Any) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def fetch_predictions(
    *,
    limit: int | None = None,
    ticker: str | None = None,
) -> list[dict]:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    init_market_memory_db()
    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        query = 'SELECT * FROM predictions'
        params: list[Any] = []
        if ticker:
            query += ' WHERE UPPER(ticker) = UPPER(?)'
            params.append(ticker.strip())
        query += ' ORDER BY timestamp ASC'
        if limit is not None and limit > 0:
            query += ' LIMIT ?'
            params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row) for row in rows]


def describe_market_data(data: dict) -> dict[str, Any]:
    prices = data.get('prices')
    price_type = type(prices).__name__
    symbols: list[str] = []
    if isinstance(prices, dict):
        symbols = list(prices.keys())

    sample_object: Any = None
    for symbol in symbols:
        entry = prices.get(symbol)
        if entry is not None:
            sample_object = {symbol: entry}
            break

    return {
        'top_level_keys': sorted(data.keys()),
        'price_container_type': price_type,
        'price_symbol_count': len(symbols),
        'sample_symbols': symbols[:20],
        'sample_price_object': sample_object,
    }


def print_market_data_structure(data: dict) -> None:
    info = describe_market_data(data)
    print('[PRICE_COVERAGE] latest_market_data structure:')
    print(f'  top_level_keys={info["top_level_keys"]}')
    print(f'  price_container_type={info["price_container_type"]}')
    print(f'  price_symbol_count={info["price_symbol_count"]}')
    print(f'  sample_symbols={info["sample_symbols"]}')
    if info['sample_price_object'] is not None:
        print(
            '  sample_price_object='
            + json.dumps(info['sample_price_object'], default=str),
        )
    else:
        print('  sample_price_object=None')


def classify_prediction(
    prediction: dict,
    market_data: dict,
) -> dict[str, Any]:
    prediction_id = prediction.get('prediction_id')
    ticker = prediction.get('ticker')
    direction = prediction.get('direction')

    ctx = extract_prediction_price_context(prediction)
    entry_price = ctx.get('entry_price') if ctx else None
    target_price = ctx.get('target_price') if ctx else None
    stop_loss = ctx.get('stop_loss') if ctx else None

    latest_price: float | None = None
    matched_key: str | None = None
    matched_variant: str | None = None
    has_latest = False

    lookup_ticker = ctx.get('ticker') if ctx else str(ticker or '').strip().upper()
    if lookup_ticker:
        latest_price, matched_key, matched_variant = lookup_price_with_variants(
            market_data,
            lookup_ticker,
        )
        has_latest = latest_price is not None

    record: dict[str, Any] = {
        'prediction_id': prediction_id,
        'ticker': ticker,
        'direction': direction,
        'entry_price': entry_price,
        'target_price': target_price,
        'stop_loss': stop_loss,
        'has_latest_price': has_latest,
        'matched_latest_price_key': matched_key,
        'matched_variant': matched_variant,
        'latest_price': latest_price,
        'classification': 'missing_price_context',
        'sanity_gate_failures': [],
    }

    if ctx is None:
        record['classification'] = 'missing_price_context'
        return record

    if latest_price is None:
        record['classification'] = 'missing_latest_price'
        return record

    gate_failures = check_price_sanity_gates(
        entry_price=entry_price,
        latest_price=latest_price,
        target_price=target_price,
        stop_loss=stop_loss,
    )
    record['sanity_gate_failures'] = gate_failures

    if is_suspicious_price_scale(
        entry_price=entry_price,
        latest_price=latest_price,
        target_price=target_price,
        stop_loss=stop_loss,
    ):
        record['classification'] = 'suspicious_price_scale'
        return record

    if target_price is None or stop_loss is None:
        record['classification'] = 'missing_price_context'
        return record

    outcome_payload = resolve_outcome_from_prices(
        prediction,
        latest_price,
        price_context=ctx,
    )
    if outcome_payload is None:
        record['classification'] = 'eligible_unresolved'
        return record

    expiry_result = outcome_payload.get('expiry_result')
    if expiry_result == 'TARGET_HIT_BY_PRICE':
        record['classification'] = 'eligible_target_hit'
    elif expiry_result == 'STOP_LOSS_HIT_BY_PRICE':
        record['classification'] = 'eligible_stop_hit'
    else:
        record['classification'] = 'eligible_unresolved'
    return record


def _format_price(value: float | None) -> str:
    if value is None:
        return '-'
    return f'{value:.4f}'


def print_prediction_record(record: dict[str, Any], *, verbose: bool = False) -> None:
    if not verbose:
        return
    print(
        f'[PRICE_COVERAGE] {record.get("prediction_id")} '
        f'ticker={record.get("ticker")} '
        f'direction={record.get("direction")} '
        f'entry={_format_price(record.get("entry_price"))} '
        f'target={_format_price(record.get("target_price"))} '
        f'stop={_format_price(record.get("stop_loss"))} '
        f'has_latest={record.get("has_latest_price")} '
        f'matched_key={record.get("matched_latest_price_key")} '
        f'variant={record.get("matched_variant")} '
        f'latest={_format_price(record.get("latest_price"))} '
        f'class={record.get("classification")}',
    )
    failures = record.get('sanity_gate_failures') or []
    if failures and record.get('classification') == 'suspicious_price_scale':
        entry = record.get('entry_price')
        latest = record.get('latest_price')
        target = record.get('target_price')
        stop = record.get('stop_loss')
        moves = {
            'latest_vs_entry_pct': pct_move(entry, latest),
            'target_vs_entry_pct': pct_move(entry, target),
            'stop_vs_entry_pct': pct_move(entry, stop),
        }
        print(f'  sanity_gate_failures={failures} pct_moves={moves}')


def run_audit(
    *,
    limit: int | None = None,
    ticker: str | None = None,
    verbose: bool = False,
    market_data: dict | None = None,
) -> dict[str, Any]:
    data = market_data if market_data is not None else load_latest_market_data()
    if not data:
        raise RuntimeError('latest_market_data.json missing or invalid')

    structure = describe_market_data(data)
    predictions = fetch_predictions(limit=limit, ticker=ticker)

    counts = {key: 0 for key in CLASSIFICATIONS}
    records: list[dict[str, Any]] = []

    for prediction in predictions:
        record = classify_prediction(prediction, data)
        records.append(record)
        classification = record.get('classification')
        if classification in counts:
            counts[classification] += 1
        print_prediction_record(record, verbose=verbose)

    summary = {
        'predictions_checked': len(predictions),
        'price_symbols': structure['price_symbol_count'],
        'structure': structure,
        'counts': counts,
        'records': records,
    }
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    counts = summary.get('counts') or {}
    print(f'[PRICE_COVERAGE] predictions_checked={summary.get("predictions_checked", 0)}')
    print(f'[PRICE_COVERAGE] price_symbols={summary.get("price_symbols", 0)}')
    for key in CLASSIFICATIONS:
        print(f'[PRICE_COVERAGE] {key}={counts.get(key, 0)}')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Audit prediction price coverage against latest_market_data (read-only)',
    )
    parser.add_argument('--limit', type=int, default=None, help='Max predictions to examine')
    parser.add_argument('--ticker', default=None, help='Filter to one ticker symbol')
    parser.add_argument('--verbose', action='store_true', help='Print per-prediction details')
    parser.add_argument(
        '--price-file',
        default=str(LATEST_MARKET_DATA_PATH),
        help='Market price JSON to audit against (default: data/latest_market_data.json)',
    )
    args = parser.parse_args()

    price_file = Path(args.price_file)
    print(f'[PRICE_COVERAGE] price_file={price_file}')

    data = load_latest_market_data(price_file)
    if not data:
        print(
            f'[PRICE_COVERAGE] price file missing or invalid: {price_file}',
            file=sys.stderr,
        )
        return 1

    print_market_data_structure(data)

    try:
        summary = run_audit(
            limit=args.limit,
            ticker=args.ticker,
            verbose=args.verbose,
            market_data=data,
        )
    except RuntimeError as exc:
        print(f'[PRICE_COVERAGE] audit failed: {exc}', file=sys.stderr)
        return 1

    print_summary(summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
