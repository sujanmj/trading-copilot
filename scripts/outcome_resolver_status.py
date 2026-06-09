#!/usr/bin/env python3
"""
Outcome resolver status snapshot — Stage 49B.

Usage:
  python scripts/outcome_resolver_status.py
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


def main() -> int:
    try:
        from backend.storage.outcome_resolver import get_outcome_resolver_status

        status = get_outcome_resolver_status()
    except Exception:
        status = {
            'resolver_active': False,
            'last_run': None,
            'resolved_total': 0,
            'pending_total': 0,
            'skipped_no_price': 0,
            'skipped_missing_reference': 0,
            'skipped_missing_evaluation': 0,
            'skipped_not_due': 0,
            'errors': 0,
        }

    active = status.get('resolver_active')
    last_run = status.get('last_run') or 'none'
    print('OUTCOME_RESOLVER_STATUS_OK', flush=True)
    print(f"resolver_active={'true' if active else 'false'}", flush=True)
    print(f'last_run={last_run}', flush=True)
    print(f"resolved_total={int(status.get('resolved_total') or 0)}", flush=True)
    print(f"pending_total={int(status.get('pending_total') or 0)}", flush=True)
    print(f"skipped_no_price={int(status.get('skipped_no_price') or 0)}", flush=True)
    print(f"skipped_missing_reference={int(status.get('skipped_missing_reference') or 0)}", flush=True)
    print(f"skipped_missing_evaluation={int(status.get('skipped_missing_evaluation') or 0)}", flush=True)
    print(f"skipped_not_due={int(status.get('skipped_not_due') or 0)}", flush=True)
    print(f"errors={int(status.get('errors') or 0)}", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
