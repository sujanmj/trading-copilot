#!/usr/bin/env python3
"""Validate SQLite ↔ export ↔ Telegram formatter consistency."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    errors = []
    from backend.storage.stats_aggregates import (
        aggregate_outcomes,
        aggregate_calibration,
        aggregate_stats,
        format_outcomes_telegram,
        format_stats_telegram,
    )
    from backend.storage.stats_exporter import export_stats
    from backend.orchestration.opportunity_filter import rank_opportunities, DEFAULT_OPPS_LIMIT
    from backend.utils.market_hours import get_operational_status
    from backend.orchestration.telegram_brain_pusher import check_intel_file_stale, stale_warning
    from backend.orchestration.telegram_command_guard import begin_command, finish_command

    live = aggregate_outcomes('all_time')
    cal = aggregate_calibration()
    exported = export_stats()
    exp_metrics = exported.get('metrics_all_time') or {}

    for label, key in [
        ('wins', 'wins'),
        ('losses', 'losses'),
        ('pending', 'pending'),
        ('total_evaluated', 'total_evaluated'),
    ]:
        if live.get(key) != exp_metrics.get(key):
            errors.append(f"export mismatch {label}: live={live.get(key)} export={exp_metrics.get(key)}")

    if cal.get('wins') != live.get('wins'):
        errors.append(f"calibration wins mismatch: cal={cal.get('wins')} live={live.get('wins')}")
    if cal.get('pending') != live.get('pending'):
        errors.append(f"calibration pending mismatch: cal={cal.get('pending')} live={live.get('pending')}")

    stats_msg = format_stats_telegram(live)
    if str(live.get('wins', 0)) not in stats_msg and live.get('wins'):
        errors.append('stats telegram missing wins count')
    if str(live.get('pending', 0)) not in stats_msg:
        errors.append('stats telegram missing pending count')

    opps = rank_opportunities(limit=DEFAULT_OPPS_LIMIT)
    if len(opps) > DEFAULT_OPPS_LIMIT:
        errors.append(f'opps cap exceeded: {len(opps)}')

    op = get_operational_status()
    is_stale, _ = check_intel_file_stale()
    if op.get('expect_quiet_collectors') and is_stale:
        errors.append('night mode still marks intel stale in check_intel_file_stale')

    sw = stale_warning({})
    if op.get('expect_quiet_collectors') and 'stale' in sw.lower() and 'night mode' not in sw.lower():
        errors.append('stale_warning not night-safe')

    skip1, _, k1 = begin_command('stats', '', 'test')
    skip2, _, k2 = begin_command('stats', '', 'test')
    finish_command(k1)
    finish_command(k2)
    if not skip2:
        errors.append('debounce did not suppress duplicate stats command')

    print('=== CONSISTENCY VALIDATION ===')
    print(f"SQLite: wins={live.get('wins')} losses={live.get('losses')} pending={live.get('pending')} evaluated={live.get('total_evaluated')}")
    print(f"Export: wins={exp_metrics.get('wins')} losses={exp_metrics.get('losses')} pending={exp_metrics.get('pending')}")
    print(f"Night mode: {op.get('display_status')} intel_stale={is_stale}")
    print(f"Opps cap: {len(opps)}/{DEFAULT_OPPS_LIMIT}")
    print(f"Debounce: first={skip1} second={skip2}")

    if errors:
        print('FAILURES:')
        for e in errors:
            print(f'  - {e}')
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
