#!/usr/bin/env python3
"""
Audit historical_prices quality in historical_market_memory.db.

Prints HISTORICAL_PRICE_QUALITY_OK on success.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'HISTORICAL_PRICE_QUALITY_FAIL: {msg}', file=sys.stderr)
    return 1


def _print_anomaly(item: dict) -> None:
    print(
        '[HIST_PRICE_AUDIT] anomaly '
        f'ticker={item.get("ticker")} '
        f'date={item.get("date")} '
        f'open={item.get("open")} '
        f'high={item.get("high")} '
        f'low={item.get("low")} '
        f'close={item.get("close")} '
        f'volume={item.get("volume")} '
        f'source={item.get("source")} '
        f'reason={item.get("reason") or item.get("type")} '
        f'severity={item.get("severity")}'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit historical price quality.')
    parser.add_argument('--verbose', action='store_true', help='Print anomaly row details')
    parser.add_argument('--export', metavar='PATH', help='Export audit JSON to PATH')
    parser.add_argument('--ticker', help='Filter audit to one ticker')
    parser.add_argument(
        '--write-anomalies',
        action='store_true',
        help='Upsert anomalies to historical_price_anomalies (no candle deletion)',
    )
    parser.add_argument(
        '--exclude-scale-discontinuity',
        action='store_true',
        help='Detect day-over-day close scale discontinuities (>10x or <0.1x)',
    )
    parser.add_argument('--json', action='store_true', help='Print full audit JSON to stdout')
    args = parser.parse_args()

    from backend.analytics.historical_price_audit import audit_and_build_anomaly_records
    from backend.storage.historical_market_store import get_historical_db_path, init_db, upsert_price_anomalies

    if not init_db():
        return _fail('init_db failed')

    db_path = get_historical_db_path()
    if not db_path.exists():
        return _fail(f'database missing: {db_path}')

    audit, records = audit_and_build_anomaly_records(
        ticker=args.ticker,
        exclude_scale_discontinuity=args.exclude_scale_discontinuity,
    )

    if args.json:
        print(json.dumps(audit, indent=2, default=str))

    print(f'[HIST_PRICE_AUDIT] rows={audit["rows"]}')
    print(f'[HIST_PRICE_AUDIT] tickers={audit["tickers"]}')
    print(f'[HIST_PRICE_AUDIT] anomalies={audit["anomalies"]}')
    print(f'[HIST_PRICE_AUDIT] fake_prices={audit["fake_prices"]}')

    if audit.get('missing_volume_warned', 0) > 0:
        print(f'[HIST_PRICE_AUDIT] missing_volume_warned={audit["missing_volume_warned"]}')

    details = audit.get('anomaly_details') or []
    if args.verbose and details:
        for item in details:
            _print_anomaly(item)

    if args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(audit, indent=2, default=str), encoding='utf-8')
        print(f'[HIST_PRICE_AUDIT] export={export_path}')

    if args.write_anomalies:
        written = upsert_price_anomalies(records)
        print(f'[HIST_PRICE_AUDIT] anomalies_written={written}')

    if audit['fake_prices'] != 0:
        return _fail('fake_prices must be 0')

    if not args.write_anomalies:
        blocking = [
            item for item in details
            if item.get('severity') == 'exclude_from_simulation'
            or item.get('type') in (
                'nan_ohlc',
                'high_lt_low',
                'open_outside_range',
                'close_outside_range',
                'fake_prices_flag',
                'scale_discontinuity',
            )
        ]
        if blocking:
            return _fail(f'blocking anomalies={len(blocking)} (use --write-anomalies to quarantine)')

    print('HISTORICAL_PRICE_QUALITY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
