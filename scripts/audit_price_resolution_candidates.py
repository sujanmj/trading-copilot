#!/usr/bin/env python3
"""
Read-only audit of predictions that would resolve from market price evidence.

Uses the same resolution gates as resolve_market_memory_outcomes_from_prices.py
without writing outcomes.

Usage:
  python scripts/audit_price_resolution_candidates.py
  python scripts/audit_price_resolution_candidates.py --limit 500
  python scripts/audit_price_resolution_candidates.py --ticker TCS --verbose
  python scripts/audit_price_resolution_candidates.py --json
"""

from __future__ import annotations

import argparse
import json
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

from backend.storage.market_memory_outcomes import (
    DEFAULT_PRICE_HOLDING_PERIOD,
    extract_prediction_price_context,
    get_latest_market_data_timestamp,
    is_latest_market_data_stale,
    load_latest_market_data,
    lookup_latest_price,
    parse_prediction_raw_payload,
    resolve_outcome_from_prices,
)
from backend.storage.price_outcome_sanity import (
    DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    DEFAULT_MAX_STOP_VS_ENTRY_PCT,
    DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    check_price_sanity_gates,
    is_suspicious_price_scale,
    pct_move,
)
from backend.utils.config import DATA_DIR
from scripts.audit_price_coverage import fetch_predictions

DEFAULT_PRICE_FILE = DATA_DIR / 'latest_market_data_memory_enriched.json'

ROW_COLUMNS = (
    'prediction_id',
    'ticker',
    'prediction_date',
    'direction',
    'confidence',
    'entry_price',
    'target_price',
    'stop_loss',
    'latest_price',
    'latest_source',
    'latest_validated_at',
    'actual_move_pct',
    'would_result',
    'would_expiry_result',
    'sanity_status',
)

ANOMALY_ACTUAL_MOVE_ABS_PCT = 10.0
ANOMALY_TARGET_STOP_WIDE_PCT = 15.0
ANOMALY_LOW_CONFIDENCE = 0.5
ANOMALY_STALE_PREDICTION_DAYS = 5


def _to_float(value: Any) -> float | None:
    if value is None or str(value).strip() == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or str(value).strip() == '':
        return None
    text = str(value).strip()
    if len(text) == 10 and text[4] == '-' and text[7] == '-':
        text = f'{text}T00:00:00+00:00'
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _find_price_key(data: dict, ticker: str) -> str | None:
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


def lookup_price_metadata(
    data: dict,
    ticker: str,
) -> tuple[float | None, str | None, str | None]:
    """Return (latest_price, source, validated_at) for ticker."""
    latest_price = lookup_latest_price(data, ticker)
    match_key = _find_price_key(data, ticker)
    if match_key is None:
        return latest_price, None, None

    entry = data.get('prices', {}).get(match_key)
    if not isinstance(entry, dict):
        return latest_price, None, None

    source = entry.get('source')
    validated_at = entry.get('validated_at')
    if validated_at is not None:
        validated_at = str(validated_at)
    if source is not None:
        source = str(source)
    return latest_price, source, validated_at


def extract_prediction_date(prediction: dict) -> str | None:
    raw = parse_prediction_raw_payload(prediction.get('raw_payload'))
    for key in ('prediction_date', 'date'):
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    timestamp = prediction.get('timestamp')
    if timestamp is not None and str(timestamp).strip():
        text = str(timestamp).strip()
        if len(text) >= 10:
            return text[:10]
        return text
    return None


def detect_candidate_anomalies(
    *,
    prediction: dict,
    actual_move_pct: float | None,
    entry_price: float | None,
    target_price: float | None,
    stop_loss: float | None,
    now: datetime | None = None,
) -> list[str]:
    flags: list[str] = []

    if actual_move_pct is not None and abs(actual_move_pct) > ANOMALY_ACTUAL_MOVE_ABS_PCT:
        flags.append('actual_move_abs_gt_10_pct')

    target_vs_entry = pct_move(entry_price, target_price)
    stop_vs_entry = pct_move(entry_price, stop_loss)
    if (
        (target_vs_entry is not None and abs(target_vs_entry) > ANOMALY_TARGET_STOP_WIDE_PCT)
        or (stop_vs_entry is not None and abs(stop_vs_entry) > ANOMALY_TARGET_STOP_WIDE_PCT)
    ):
        flags.append('target_or_stop_too_wide')

    confidence = _to_float(prediction.get('confidence'))
    if confidence is not None and confidence < ANOMALY_LOW_CONFIDENCE:
        flags.append('low_confidence')
    else:
        label = str(prediction.get('confidence_label') or '').strip().upper()
        if label == 'LOW':
            flags.append('low_confidence')

    prediction_ts = _parse_timestamp(prediction.get('timestamp'))
    if prediction_ts is not None:
        reference = now or datetime.now(timezone.utc)
        age_days = (reference - prediction_ts).total_seconds() / 86400.0
        if age_days > ANOMALY_STALE_PREDICTION_DAYS:
            flags.append('stale_prediction_gt_5d')

    return flags


def _format_cell(value: Any) -> str:
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.4f}'
    if isinstance(value, list):
        return ','.join(str(item) for item in value)
    return str(value)


def build_candidate_row(
    prediction: dict,
    market_data: dict,
    *,
    holding_period: str = DEFAULT_PRICE_HOLDING_PERIOD,
    max_latest_vs_entry_pct: float = DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    max_target_vs_entry_pct: float = DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    max_stop_vs_entry_pct: float = DEFAULT_MAX_STOP_VS_ENTRY_PCT,
    latest_market_data_timestamp: str | None = None,
) -> dict[str, Any] | None:
    ctx = extract_prediction_price_context(prediction)
    if not ctx:
        return None

    latest_price, latest_source, latest_validated_at = lookup_price_metadata(
        market_data,
        ctx['ticker'],
    )
    if latest_price is None:
        return None

    if is_suspicious_price_scale(
        entry_price=ctx.get('entry_price'),
        latest_price=latest_price,
        target_price=ctx.get('target_price'),
        stop_loss=ctx.get('stop_loss'),
        max_latest_vs_entry_pct=max_latest_vs_entry_pct,
        max_target_vs_entry_pct=max_target_vs_entry_pct,
        max_stop_vs_entry_pct=max_stop_vs_entry_pct,
    ):
        return None

    outcome_payload = resolve_outcome_from_prices(
        prediction,
        latest_price,
        price_context=ctx,
        holding_period=holding_period,
        latest_market_data_timestamp=latest_market_data_timestamp,
    )
    if not outcome_payload:
        return None

    entry_price = ctx.get('entry_price')
    actual_move_pct = _to_float(outcome_payload.get('actual_move'))
    if actual_move_pct is None:
        actual_move_pct = pct_move(entry_price, latest_price)

    gate_failures = check_price_sanity_gates(
        entry_price=entry_price,
        latest_price=latest_price,
        target_price=ctx.get('target_price'),
        stop_loss=ctx.get('stop_loss'),
        max_latest_vs_entry_pct=max_latest_vs_entry_pct,
        max_target_vs_entry_pct=max_target_vs_entry_pct,
        max_stop_vs_entry_pct=max_stop_vs_entry_pct,
    )
    sanity_status = 'ok' if not gate_failures else ','.join(gate_failures)

    row: dict[str, Any] = {
        'prediction_id': prediction.get('prediction_id'),
        'ticker': prediction.get('ticker'),
        'prediction_date': extract_prediction_date(prediction),
        'direction': prediction.get('direction'),
        'confidence': prediction.get('confidence'),
        'entry_price': entry_price,
        'target_price': ctx.get('target_price'),
        'stop_loss': ctx.get('stop_loss'),
        'latest_price': latest_price,
        'latest_source': latest_source,
        'latest_validated_at': latest_validated_at,
        'actual_move_pct': actual_move_pct,
        'would_result': outcome_payload.get('resolved_as'),
        'would_expiry_result': outcome_payload.get('expiry_result'),
        'sanity_status': sanity_status,
    }
    row['anomalies'] = detect_candidate_anomalies(
        prediction=prediction,
        actual_move_pct=actual_move_pct,
        entry_price=entry_price,
        target_price=ctx.get('target_price'),
        stop_loss=ctx.get('stop_loss'),
    )
    return row


def classify_prediction_skip(
    prediction: dict,
    market_data: dict,
    *,
    max_latest_vs_entry_pct: float = DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    max_target_vs_entry_pct: float = DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    max_stop_vs_entry_pct: float = DEFAULT_MAX_STOP_VS_ENTRY_PCT,
) -> str:
    ctx = extract_prediction_price_context(prediction)
    if not ctx:
        return 'missing_context'

    latest_price = lookup_latest_price(market_data, ctx['ticker'])
    if latest_price is None:
        return 'missing_latest_price'

    if is_suspicious_price_scale(
        entry_price=ctx.get('entry_price'),
        latest_price=latest_price,
        target_price=ctx.get('target_price'),
        stop_loss=ctx.get('stop_loss'),
        max_latest_vs_entry_pct=max_latest_vs_entry_pct,
        max_target_vs_entry_pct=max_target_vs_entry_pct,
        max_stop_vs_entry_pct=max_stop_vs_entry_pct,
    ):
        return 'suspicious_skipped'

    outcome_payload = resolve_outcome_from_prices(
        prediction,
        latest_price,
        price_context=ctx,
    )
    if outcome_payload:
        return 'would_resolve'
    return 'no_price_evidence'


def run_audit(
    *,
    limit: int | None = None,
    ticker: str | None = None,
    verbose: bool = False,
    market_data: dict | None = None,
    market_data_path: Path | str | None = None,
    allow_stale: bool = False,
    max_age_hours: float = 24.0,
    max_latest_vs_entry_pct: float = DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
    max_target_vs_entry_pct: float = DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
    max_stop_vs_entry_pct: float = DEFAULT_MAX_STOP_VS_ENTRY_PCT,
    holding_period: str = DEFAULT_PRICE_HOLDING_PERIOD,
) -> dict[str, Any]:
    data = market_data if market_data is not None else load_latest_market_data(
        market_data_path,
    )
    if not data:
        raise RuntimeError('price file missing or invalid')

    stale = is_latest_market_data_stale(
        data,
        max_age_hours=max_age_hours,
        allow_stale=allow_stale,
    )
    if stale:
        raise RuntimeError('market data is stale or has no parseable timestamp')

    ts = get_latest_market_data_timestamp(data)
    ts_text = ts.isoformat() if ts is not None else None

    predictions = fetch_predictions(limit=limit, ticker=ticker)

    would_resolve_rows: list[dict[str, Any]] = []
    counts = {
        'missing_context': 0,
        'missing_latest_price': 0,
        'suspicious_skipped': 0,
        'no_price_evidence': 0,
        'target_hits': 0,
        'stop_hits': 0,
    }
    anomaly_counts: dict[str, int] = {}

    for prediction in predictions:
        skip_reason = classify_prediction_skip(
            prediction,
            data,
            max_latest_vs_entry_pct=max_latest_vs_entry_pct,
            max_target_vs_entry_pct=max_target_vs_entry_pct,
            max_stop_vs_entry_pct=max_stop_vs_entry_pct,
        )
        if skip_reason != 'would_resolve':
            if skip_reason in counts:
                counts[skip_reason] += 1
            continue

        row = build_candidate_row(
            prediction,
            data,
            holding_period=holding_period,
            max_latest_vs_entry_pct=max_latest_vs_entry_pct,
            max_target_vs_entry_pct=max_target_vs_entry_pct,
            max_stop_vs_entry_pct=max_stop_vs_entry_pct,
            latest_market_data_timestamp=ts_text,
        )
        if row is None:
            counts['no_price_evidence'] += 1
            continue

        would_resolve_rows.append(row)
        expiry_result = row.get('would_expiry_result')
        if expiry_result == 'TARGET_HIT_BY_PRICE':
            counts['target_hits'] += 1
        elif expiry_result == 'STOP_LOSS_HIT_BY_PRICE':
            counts['stop_hits'] += 1

        if verbose:
            parts = [f'{col}={_format_cell(row.get(col))}' for col in ROW_COLUMNS]
            anomalies = row.get('anomalies') or []
            if anomalies:
                parts.append(f'anomalies={",".join(anomalies)}')
            print('[PRICE_RESOLUTION_AUDIT] ' + ' '.join(parts))

        for flag in row.get('anomalies') or []:
            anomaly_counts[flag] = anomaly_counts.get(flag, 0) + 1

    return {
        'checked': len(predictions),
        'would_resolve': len(would_resolve_rows),
        'target_hits': counts['target_hits'],
        'stop_hits': counts['stop_hits'],
        'suspicious_skipped': counts['suspicious_skipped'],
        'missing_context': counts['missing_context'],
        'no_price_evidence': counts['no_price_evidence'],
        'missing_latest_price': counts['missing_latest_price'],
        'rows': would_resolve_rows,
        'anomaly_counts': anomaly_counts,
    }


def print_rows_table(rows: list[dict[str, Any]], *, verbose: bool = False) -> None:
    if not rows:
        return

    columns = list(ROW_COLUMNS)
    if verbose:
        columns = columns + ['anomalies']

    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            widths[col] = max(widths[col], len(_format_cell(row.get(col))))

    header = ' | '.join(col.ljust(widths[col]) for col in columns)
    print(header)
    print('-' * len(header))
    for row in rows:
        print(' | '.join(
            _format_cell(row.get(col)).ljust(widths[col])
            for col in columns
        ))


def print_summary(summary: dict[str, Any]) -> None:
    print(f'[PRICE_RESOLUTION_AUDIT] checked={summary.get("checked", 0)}')
    print(f'[PRICE_RESOLUTION_AUDIT] would_resolve={summary.get("would_resolve", 0)}')
    print(f'[PRICE_RESOLUTION_AUDIT] target_hits={summary.get("target_hits", 0)}')
    print(f'[PRICE_RESOLUTION_AUDIT] stop_hits={summary.get("stop_hits", 0)}')
    print(f'[PRICE_RESOLUTION_AUDIT] suspicious_skipped={summary.get("suspicious_skipped", 0)}')
    print(f'[PRICE_RESOLUTION_AUDIT] missing_context={summary.get("missing_context", 0)}')
    print(f'[PRICE_RESOLUTION_AUDIT] no_price_evidence={summary.get("no_price_evidence", 0)}')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Audit predictions that would resolve from market prices (read-only)',
    )
    parser.add_argument(
        '--price-file',
        default=str(DEFAULT_PRICE_FILE),
        help='Market price JSON to audit against (default: enriched memory file)',
    )
    parser.add_argument('--limit', type=int, default=None, help='Max predictions to examine')
    parser.add_argument('--ticker', default=None, help='Filter to one ticker symbol')
    parser.add_argument('--verbose', action='store_true', help='Print per-row details')
    parser.add_argument('--json', action='store_true', help='Emit JSON instead of table output')
    parser.add_argument(
        '--allow-stale',
        action='store_true',
        help='Allow audit even when market data is stale',
    )
    parser.add_argument(
        '--max-age-hours',
        type=float,
        default=24.0,
        help='Reject market data older than this many hours unless --allow-stale',
    )
    parser.add_argument(
        '--holding-period',
        default=DEFAULT_PRICE_HOLDING_PERIOD,
        help=f'Holding period label for resolution (default: {DEFAULT_PRICE_HOLDING_PERIOD})',
    )
    parser.add_argument(
        '--max-latest-vs-entry-pct',
        type=float,
        default=DEFAULT_MAX_LATEST_VS_ENTRY_PCT,
        help='Reject when |latest vs entry| exceeds this pct (default: 20)',
    )
    parser.add_argument(
        '--max-target-vs-entry-pct',
        type=float,
        default=DEFAULT_MAX_TARGET_VS_ENTRY_PCT,
        help='Reject when |target vs entry| exceeds this pct (default: 30)',
    )
    parser.add_argument(
        '--max-stop-vs-entry-pct',
        type=float,
        default=DEFAULT_MAX_STOP_VS_ENTRY_PCT,
        help='Reject when |stop vs entry| exceeds this pct (default: 30)',
    )
    args = parser.parse_args()

    price_file = Path(args.price_file)
    print(f'[PRICE_RESOLUTION_AUDIT] price_file={price_file}')

    data = load_latest_market_data(price_file)
    if not data:
        print(
            f'[PRICE_RESOLUTION_AUDIT] price file missing or invalid: {price_file}',
            file=sys.stderr,
        )
        return 1

    try:
        summary = run_audit(
            limit=args.limit,
            ticker=args.ticker,
            verbose=args.verbose,
            market_data=data,
            allow_stale=args.allow_stale,
            max_age_hours=args.max_age_hours,
            max_latest_vs_entry_pct=args.max_latest_vs_entry_pct,
            max_target_vs_entry_pct=args.max_target_vs_entry_pct,
            max_stop_vs_entry_pct=args.max_stop_vs_entry_pct,
            holding_period=args.holding_period,
        )
    except RuntimeError as exc:
        print(f'[PRICE_RESOLUTION_AUDIT] audit failed: {exc}', file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    elif not args.verbose:
        print_rows_table(summary['rows'])

    print_summary(summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
