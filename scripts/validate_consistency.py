#!/usr/bin/env python3
"""Validate unified metrics consistency across all surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    errors = []
    from backend.lifecycle.unified_metrics import (
        get_calibration_metrics,
        get_metrics_for_telegram,
        get_outcome_metrics,
        get_prediction_metrics,
        get_unified_snapshot,
        format_outcomes_telegram,
        format_stats_telegram,
        format_calibration_telegram,
    )
    from backend.storage.stats_exporter import export_stats
    from backend.api.api_server import _build_runtime_snapshot

    sqlite = get_outcome_metrics('all_time')
    pred = get_prediction_metrics('all_time')
    cal = get_calibration_metrics()
    bundle = get_metrics_for_telegram()
    exported = export_stats()
    exp = exported.get('metrics_all_time') or {}
    runtime = _build_runtime_snapshot()
    rt_metrics = ((runtime.get('data') or {}).get('stats') or {}).get('metrics_all_time') or {}

    checks = [
        ('sqlite vs predictions.evaluated', sqlite['evaluated'], pred['evaluated']),
        ('sqlite vs predictions.pending', sqlite['pending'], pred['pending']),
        ('sqlite vs calibration.evaluated', sqlite['evaluated'], cal['evaluated']),
        ('sqlite vs calibration.pending', sqlite['pending'], cal['pending']),
        ('sqlite vs export.evaluated', sqlite['evaluated'], exp.get('evaluated', exp.get('total_evaluated'))),
        ('sqlite vs export.pending', sqlite['pending'], exp.get('pending')),
        ('sqlite vs export.wins', sqlite['wins'], exp.get('wins')),
        ('sqlite vs export.losses', sqlite['losses'], exp.get('losses')),
        ('sqlite vs runtime.evaluated', sqlite['evaluated'], rt_metrics.get('evaluated', rt_metrics.get('total_evaluated'))),
        ('sqlite vs runtime.pending', sqlite['pending'], rt_metrics.get('pending')),
        ('prediction_total rule', sqlite['prediction_total'], sqlite['evaluated'] + sqlite['pending']),
        ('bundle identity', bundle['metrics']['evaluated'], sqlite['evaluated']),
    ]
    for label, a, b in checks:
        if a != b:
            errors.append(f"{label}: {a} != {b}")

    stats_msg = format_stats_telegram(sqlite)
    out_msg = format_outcomes_telegram(sqlite)
    cal_msg = format_calibration_telegram(cal)
    for field, val in [('wins', sqlite['wins']), ('losses', sqlite['losses']), ('pending', sqlite['pending'])]:
        if str(val) not in stats_msg:
            errors.append(f'/stats missing {field}={val}')
        if str(val) not in out_msg:
            errors.append(f'/outcomes missing {field}={val}')
    if str(sqlite['evaluated']) not in cal_msg:
        errors.append('/calibration missing evaluated count')

    lc_path = ROOT / 'data' / 'lifecycle_state.json'
    from backend.lifecycle.prediction_lifecycle_engine import load_lifecycle_state, save_lifecycle_state
    save_lifecycle_state(load_lifecycle_state())
    if lc_path.exists():
        lc = json.loads(lc_path.read_text(encoding='utf-8'))
        um = lc.get('unified_metrics') or {}
        if um and um.get('evaluated') != sqlite['evaluated']:
            errors.append(f"lifecycle_state unified_metrics evaluated mismatch: {um.get('evaluated')} != {sqlite['evaluated']}")

    print('=== UNIFIED METRICS CONSISTENCY ===')
    print(f"SQLite: predictions={sqlite['prediction_total']} evaluated={sqlite['evaluated']} pending={sqlite['pending']} wins={sqlite['wins']} losses={sqlite['losses']} win_rate={sqlite['win_rate']}")
    print(f"Export: evaluated={exp.get('evaluated', exp.get('total_evaluated'))} pending={exp.get('pending')} wins={exp.get('wins')} losses={exp.get('losses')}")
    print(f"Runtime: evaluated={rt_metrics.get('evaluated', rt_metrics.get('total_evaluated'))} pending={rt_metrics.get('pending')}")
    print(f"Calibration: evaluated={cal['evaluated']} pending={cal['pending']} wins={cal['wins']} losses={cal['losses']}")

    if errors:
        print('FAILURES:')
        for e in errors:
            print(f'  - {e}')
        return 1

    print('UNIFIED METRICS CONSISTENCY VERIFIED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
