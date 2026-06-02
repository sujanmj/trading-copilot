#!/usr/bin/env python3
"""
One-time prediction lifecycle state backfill across SQLite and JSON caches.

Usage:
  python scripts/migrate_prediction_states.py           # full migration + export rebuild
  python scripts/migrate_prediction_states.py --dry-run # report only
  python scripts/migrate_prediction_states.py --no-rebuild
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description='Backfill canonical prediction lifecycle states')
    parser.add_argument('--dry-run', action='store_true', help='Report changes without writing')
    parser.add_argument('--no-rebuild', action='store_true', help='Skip history/stats export rebuild')
    args = parser.parse_args()

    from backend.lifecycle.prediction_state_migration import run_full_migration
    from backend.lifecycle.prediction_reconciliation import validate_prediction_totals
    from backend.lifecycle.unified_metrics import _validate_sqlite_lifecycle

    print('[migrate_prediction_states] starting', flush=True)
    report = run_full_migration(dry_run=args.dry_run, rebuild=not args.no_rebuild)

    print('\n[migrate_prediction_states] summary', flush=True)
    print(json.dumps({
        'dry_run': report.get('dry_run'),
        'sqlite': report.get('sqlite'),
        'json_files': report.get('json_files'),
        'exports': report.get('exports'),
        'before': {k: report['before'][k] for k in ('total', 'wins', 'losses', 'expired', 'neutralized', 'pending')},
        'after': {k: report['after'][k] for k in ('total', 'wins', 'losses', 'expired', 'neutralized', 'pending')},
        'last_week': report.get('last_week'),
    }, indent=2))

    lifecycle = _validate_sqlite_lifecycle()
    print('\n[migrate_prediction_states] validate_prediction_lifecycle (SQLite)', flush=True)
    print(json.dumps({
        'valid': lifecycle.get('valid'),
        'total': lifecycle.get('total'),
        'counts': lifecycle.get('counts'),
        'issues': lifecycle.get('issues'),
    }, indent=2))

    ok = (
        bool(lifecycle.get('valid'))
        and validate_prediction_totals(report['after'], source='migration_after')
        and validate_prediction_totals(report['last_week']['after'], source='migration_last_week')
    )
    print(f'\n[migrate_prediction_states] overall_ok={ok}', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
