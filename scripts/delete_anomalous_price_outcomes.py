#!/usr/bin/env python3
"""
Delete anomalous price-resolved market memory outcomes.

Default is dry-run; pass --confirm to delete rows.

Usage:
  python scripts/delete_anomalous_price_outcomes.py
  python scripts/delete_anomalous_price_outcomes.py --confirm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.storage.price_outcome_sanity import (
    PRICE_EXPIRY_RESULTS,
    fetch_price_outcomes,
)


def _format_cell(value: Any) -> str:
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.4f}'
    return str(value)


def _print_delete_candidates(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        anomalies = ','.join(row.get('anomalies') or [])
        print(
            f'prediction_id={row["prediction_id"]} '
            f'ticker={row.get("ticker")} '
            f'actual_move={_format_cell(row.get("actual_move"))} '
            f'latest_price={_format_cell(row.get("latest_price"))} '
            f'entry_price={_format_cell(row.get("entry_price"))} '
            f'anomalies={anomalies}',
        )


def delete_anomalous_price_outcomes(
    *,
    confirm: bool = False,
    only_prediction_ids: set[str] | None = None,
) -> dict[str, Any]:
    from backend.storage.market_memory_db import get_connection, init_market_memory_db

    init_market_memory_db()
    conn = get_connection()
    try:
        rows = fetch_price_outcomes(conn)
        anomalous = [row for row in rows if row.get('anomalies')]
        if only_prediction_ids is not None:
            anomalous = [
                row for row in anomalous
                if row['prediction_id'] in only_prediction_ids
            ]

        if anomalous:
            _print_delete_candidates(anomalous)

        deleted = 0
        if confirm:
            for row in anomalous:
                cur = conn.execute(
                    """
                    DELETE FROM outcomes
                    WHERE prediction_id = ?
                      AND holding_period = ?
                      AND expiry_result IN (?, ?)
                    """,
                    (
                        row['prediction_id'],
                        row['holding_period'],
                        PRICE_EXPIRY_RESULTS[0],
                        PRICE_EXPIRY_RESULTS[1],
                    ),
                )
                deleted += cur.rowcount
            conn.commit()
    finally:
        conn.close()

    checked = len(rows)
    if only_prediction_ids is not None:
        checked = len([row for row in rows if row['prediction_id'] in only_prediction_ids])

    return {
        'checked': checked,
        'anomalous': len(anomalous),
        'deleted': deleted,
        'dry_run': not confirm,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Delete anomalous price-resolved market memory outcomes',
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Actually delete anomalous rows (default: dry-run only)',
    )
    args = parser.parse_args()

    summary = delete_anomalous_price_outcomes(confirm=args.confirm)

    print(f'[DELETE_ANOMALOUS_OUTCOMES] checked={summary["checked"]}')
    print(f'[DELETE_ANOMALOUS_OUTCOMES] anomalous={summary["anomalous"]}')
    print(f'[DELETE_ANOMALOUS_OUTCOMES] deleted={summary["deleted"]}')
    print(f'[DELETE_ANOMALOUS_OUTCOMES] dry_run={summary["dry_run"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
