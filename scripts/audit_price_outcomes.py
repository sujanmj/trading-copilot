#!/usr/bin/env python3
"""
Read-only audit of price-resolved market memory outcomes.

Usage:
  python scripts/audit_price_outcomes.py
  python scripts/audit_price_outcomes.py --verbose
  python scripts/audit_price_outcomes.py --json
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

from backend.storage.price_outcome_sanity import fetch_price_outcomes

TABLE_COLUMNS = (
    'prediction_id',
    'ticker',
    'direction',
    'entry_price',
    'target_price',
    'stop_loss',
    'latest_price',
    'actual_move',
    'expiry_result',
    'resolved_as',
    'timestamp',
)


def _format_cell(value: Any) -> str:
    if value is None:
        return '-'
    if isinstance(value, float):
        if abs(value) >= 100:
            return f'{value:.2f}'
        if abs(value) >= 10:
            return f'{value:.4f}'
        return f'{value:.4f}'
    return str(value)


def _print_table(rows: list[dict[str, Any]], *, verbose: bool = False) -> None:
    widths = {col: len(col) for col in TABLE_COLUMNS}
    widths['anomalies'] = len('anomalies')

    for row in rows:
        for col in TABLE_COLUMNS:
            widths[col] = max(widths[col], len(_format_cell(row.get(col))))
        if verbose:
            anomaly_text = ','.join(row.get('anomalies') or [])
            widths['anomalies'] = max(widths['anomalies'], len(anomaly_text))

    header = ' | '.join(col.ljust(widths[col]) for col in TABLE_COLUMNS)
    if verbose:
        header += ' | ' + 'anomalies'.ljust(widths['anomalies'])
    print(header)
    print('-' * len(header))

    for row in rows:
        line = ' | '.join(
            _format_cell(row.get(col)).ljust(widths[col])
            for col in TABLE_COLUMNS
        )
        if verbose:
            anomaly_text = ','.join(row.get('anomalies') or [])
            line += ' | ' + anomaly_text.ljust(widths['anomalies'])
        print(line)


def run_audit(*, verbose: bool = False) -> dict[str, Any]:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    init_market_memory_db()
    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = fetch_price_outcomes(conn)
    finally:
        conn.close()

    anomaly_ids = sorted(
        {
            row['prediction_id']
            for row in rows
            if row.get('anomalies')
        },
    )

    return {
        'outcomes_checked': len(rows),
        'anomalies': len(anomaly_ids),
        'anomaly_ids': anomaly_ids,
        'rows': rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Audit price-resolved market memory outcomes (read-only)',
    )
    parser.add_argument('--verbose', action='store_true', help='Include anomaly flags per row')
    parser.add_argument('--json', action='store_true', help='Emit JSON instead of table output')
    args = parser.parse_args()

    summary = run_audit(verbose=args.verbose)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        _print_table(summary['rows'], verbose=args.verbose)

    print(f'[OUTCOME_AUDIT] outcomes_checked={summary["outcomes_checked"]}')
    print(f'[OUTCOME_AUDIT] anomalies={summary["anomalies"]}')
    print(f'[OUTCOME_AUDIT] anomaly_ids={summary["anomaly_ids"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
