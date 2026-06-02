#!/usr/bin/env python3
"""
Audit broker_predictions table for write-safe eligibility.

Prints BROKER_PREDICTIONS_DB_AUDIT_OK on success.
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
    print(f'BROKER_PREDICTIONS_DB_AUDIT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_db_audit import audit_all_broker_predictions

    audit = audit_all_broker_predictions()
    if audit.get('ok') is not True:
        return _fail('audit failed')

    counts = audit.get('counts') or {}
    total = int(audit.get('total') or 0)
    safe = int(counts.get('safe') or 0)
    review_only = int(counts.get('review_only') or 0)
    unsafe = int(counts.get('unsafe') or 0)
    duplicates = int(counts.get('duplicate') or 0)

    print(f'[BROKER_DB_AUDIT] total={total}')
    print(f'[BROKER_DB_AUDIT] safe={safe}')
    print(f'[BROKER_DB_AUDIT] review_only={review_only}')
    print(f'[BROKER_DB_AUDIT] unsafe={unsafe}')
    print(f'[BROKER_DB_AUDIT] duplicates={duplicates}')

    for row in audit.get('rows') or []:
        if row.get('safety') != 'unsafe':
            continue
        print(
            f"  UNSAFE id={row.get('id')} | {row.get('ticker')} | "
            f"{row.get('broker_source')} | bucket={row.get('bucket')} | "
            f"reasons={row.get('reasons')} | {(row.get('title') or '')[:70]}"
        )

    print('BROKER_PREDICTIONS_DB_AUDIT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
