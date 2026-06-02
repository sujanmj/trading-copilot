#!/usr/bin/env python3
"""
Resolve market memory outcomes from existing prediction raw_payload fields.

Usage:
  python scripts/resolve_market_memory_outcomes_from_payload.py --dry-run --limit 20
  python scripts/resolve_market_memory_outcomes_from_payload.py --limit 143
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


def main() -> int:
    from backend.storage.market_memory_db import init_market_memory_db
    from backend.storage.market_memory_outcomes import (
        DEFAULT_PAYLOAD_HOLDING_PERIOD,
        resolve_outcomes_from_payloads,
    )

    parser = argparse.ArgumentParser(
        description='Resolve canonical market memory outcomes from prediction raw_payload',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Do not write outcomes (default: writes when evidence exists)',
    )
    parser.add_argument('--limit', type=int, default=100, help='Max predictions to examine')
    parser.add_argument('--verbose', action='store_true', help='Print per-prediction resolution details')
    parser.add_argument(
        '--holding-period',
        default=DEFAULT_PAYLOAD_HOLDING_PERIOD,
        help=f'Holding period for outcomes (default: {DEFAULT_PAYLOAD_HOLDING_PERIOD})',
    )
    args = parser.parse_args()

    if not init_market_memory_db():
        print('[PAYLOAD_OUTCOMES] init_market_memory_db failed', file=sys.stderr)
        return 1

    summary = resolve_outcomes_from_payloads(
        limit=args.limit,
        dry_run=args.dry_run,
        holding_period=args.holding_period,
        verbose=args.verbose,
    )

    print(f'[PAYLOAD_OUTCOMES] predictions_checked={summary.get("predictions_checked", 0)}')
    print(f'[PAYLOAD_OUTCOMES] resolved={summary.get("resolved", 0)}')
    print(f'[PAYLOAD_OUTCOMES] skipped={summary.get("skipped", 0)}')
    print(f'[PAYLOAD_OUTCOMES] written={summary.get("written", 0)}')
    print(f'[PAYLOAD_OUTCOMES] dry_run={summary.get("dry_run", False)}')
    print('[PAYLOAD_OUTCOMES] stats=' + json.dumps(summary, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
