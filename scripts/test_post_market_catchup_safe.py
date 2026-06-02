#!/usr/bin/env python3
"""
Safety tests for scripts/post_market_catchup.py.

Usage:
  python scripts/test_post_market_catchup_safe.py

Prints exactly POST_MARKET_CATCHUP_SAFE_OK on success; exits 1 on failure.
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
    print(f'POST_MARKET_CATCHUP_SAFE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    try:
        import scripts.post_market_catchup as catchup
    except Exception as exc:
        return _fail(f'import post_market_catchup failed: {exc}')

    routing_ok, routing_detail = catchup.validate_db_routing()
    if not routing_ok:
        return _fail(f'db routing before dry-run: {routing_detail}')

    available, skipped = catchup.discover_eod_steps()
    if not isinstance(available, dict) or not isinstance(skipped, dict):
        return _fail('discover_eod_steps returned unexpected shape')

    preds_before, outcomes_before = catchup._memory_counts()

    code = catchup.run_catchup(
        dry_run=True,
        skip_eod=True,
        capture_only=True,
        limit=50,
    )
    if code != 0:
        return _fail(f'run_catchup dry-run exited {code}')

    preds_after, outcomes_after = catchup._memory_counts()
    if preds_after != preds_before:
        return _fail(
            f'dry-run changed prediction count: before={preds_before} after={preds_after}'
        )
    if outcomes_after != outcomes_before:
        return _fail(
            f'dry-run changed outcome count: before={outcomes_before} after={outcomes_after}'
        )

    routing_ok_after, routing_detail_after = catchup.validate_db_routing()
    if not routing_ok_after:
        return _fail(f'db routing after dry-run: {routing_detail_after}')

    required_steps = {
        'stats_export',
        'history_export',
        'calibration_export',
        'snapshot_export',
    }
    missing = required_steps - set(available)
    if missing:
        return _fail(f'required EOD steps not discovered: {sorted(missing)}')
    if 'outcome_tracker' not in available:
        return _fail('outcome_tracker step not wired (direct or runner fallback)')

    if 'eod_lifecycle' not in skipped:
        return _fail('eod_lifecycle skip reason missing')

    print('POST_MARKET_CATCHUP_SAFE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
