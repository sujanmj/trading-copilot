#!/usr/bin/env python3
"""
Inspect latest broker_predictions DB writes.

Prints RECENT_BROKER_DB_WRITES_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'RECENT_BROKER_DB_WRITES_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_db_audit import (
        _parse_raw_payload,
        _row_source_type,
        _row_source_url,
        _row_title,
        fetch_all_broker_prediction_rows,
    )

    rows = fetch_all_broker_prediction_rows()
    recent = sorted(rows, key=lambda r: int(r.get('id') or 0), reverse=True)[:25]

    print(f'[RECENT_BROKER_DB_WRITES] total={len(rows)} showing={len(recent)}')
    for row in recent:
        raw = _parse_raw_payload(row.get('raw_payload'))
        title = _row_title(row, raw)
        reason = raw.get('classification_reason') or raw.get('direction_reason') or ''
        print(
            f"  id={row.get('id')} | ticker={row.get('ticker')} | "
            f"broker_source={row.get('broker_source')} | stance={row.get('bullish_or_bearish')} | "
            f"title={title[:80]!r} | reason={str(reason)[:60]} | "
            f"created_at={row.get('created_at')} | source_type={_row_source_type(row, raw)} | "
            f"source_url={_row_source_url(row, raw)[:120]}"
        )

    print('RECENT_BROKER_DB_WRITES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
