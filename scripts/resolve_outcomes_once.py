#!/usr/bin/env python3
"""
One-shot signal-quality outcome resolver — Stage 49A.

Usage:
  python scripts/resolve_outcomes_once.py
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
    from backend.storage.outcome_resolver import run_outcome_resolver_once

    try:
        summary = run_outcome_resolver_once(refresh_cache=True)
    except Exception as exc:
        print('OUTCOME_RESOLVER_RUN_OK', flush=True)
        print(f'pending_before=0', flush=True)
        print(f'resolved_new=0', flush=True)
        print(f'pending_after=0', flush=True)
        print(f'skipped_no_price=0', flush=True)
        print(f'skipped_not_due=0', flush=True)
        print(f'errors=1', flush=True)
        print(f'error_detail={str(exc)[:200]}', file=sys.stderr, flush=True)
        return 1

    print('OUTCOME_RESOLVER_RUN_OK', flush=True)
    print(f"pending_before={summary.get('pending_before', 0)}", flush=True)
    print(f"resolved_new={summary.get('resolved_new', 0)}", flush=True)
    print(f"pending_after={summary.get('pending_after', 0)}", flush=True)
    print(f"skipped_no_price={summary.get('skipped_no_price', 0)}", flush=True)
    print(f"skipped_missing_reference={summary.get('skipped_missing_reference', 0)}", flush=True)
    print(f"skipped_missing_evaluation={summary.get('skipped_missing_evaluation', 0)}", flush=True)
    print(f"skipped_not_due={summary.get('skipped_not_due', 0)}", flush=True)
    print(f"errors={summary.get('errors', 0)}", flush=True)
    return 0 if int(summary.get('errors') or 0) == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
